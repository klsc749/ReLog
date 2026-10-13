from __future__ import annotations

import json
import sys
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXECUTOR_ROOT = PROJECT_ROOT / "executor"
sys.path.insert(0, str(EXECUTOR_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))

import dspy

from d4j_executor.models import MetadataEntry
from d4j_executor.run import RunnerConfig, _run_test_and_collect, _ensure_cache_ready, _cache_entry_dir
from relog.code_runner import CodeRunner
from relog.evaluator.direct import _prepare_items as prepare_direct
from relog.evaluator.indirect import _prepare_items as prepare_indirect
from relog.evaluator.base_source3_evaluator import calculate_statistics
from relog.direct import process_items_concurrent
from relog.roles.initial_logger import InitialLogger
from relog.roles.logging_code_refiner import LoggingCodeRefiner
from relog.roles.log_sufficient_evaluator import LogSufficientEvaluator
from relog.roles.code_compilation_fixer import DirectCompilationFixer
from relog.utils import LogInstructionApplier, save_checkpoint
from relog.evaluator.llm.base_detect_and_repair import BaseDetectorAndRepairer
from relog.evaluator.llm.base_black_box_detect import IndirectBugDetector
from relog.evaluator.llm.verify_bug_detect import BugDetectionVerifier
from relog.evaluator.llm.verify_repair_code import CodeRepairVerifier


def make_role(role_type):
	role = role_type.__new__(role_type)
	role.llm = dspy.LM("openai/gpt-4o-mini", api_key="unused-unit-test-key")
	role._post_init()
	return role


class ProjectIntegrityTest(unittest.TestCase):
	def setUp(self):
		cache_dir = EXECUTOR_ROOT / ".cache/tmp"
		cache_dir.mkdir(parents=True, exist_ok=True)
		self.workspace = tempfile.TemporaryDirectory(dir=cache_dir)
		self.addCleanup(self.workspace.cleanup)
		self.root = Path(self.workspace.name)

	def test_before_and_after_insertions_preserve_order_and_original_line(self):
		instructions = [
			{"line_number": 1, "position": position, "log_statement": label}
			for position, label in [("before", "B1"), ("before", "B2"), ("after", "A1"), ("after", "A2")]
		]
		code, _ = LogInstructionApplier.apply_instructions("original\nnext", instructions)
		self.assertEqual(code, "B1\nB2\noriginal\nA1\nA2\nnext")

	def test_insertion_order_across_adjacent_original_lines(self):
		instructions = [
			{"line_number": 1, "position": "after", "log_statement": "after-first"},
			{"line_number": 2, "position": "before", "log_statement": "before-second"},
		]
		code, _ = LogInstructionApplier.apply_instructions("first\nsecond", instructions)
		self.assertEqual(code, "first\nafter-first\nbefore-second\nsecond")

	def test_invalid_instruction_is_not_silently_dropped(self):
		with self.assertRaises(ValueError):
			LogInstructionApplier.parse_instructions([{"line_number": 1}])
		with self.assertRaises(json.JSONDecodeError):
			LogInstructionApplier.parse_instructions("broken JSON")

	def test_out_of_range_instruction_does_not_return_partial_code(self):
		with self.assertRaises(ValueError):
			LogInstructionApplier.apply_instructions("one", [
				{"line_number": 3, "position": "after", "log_statement": "log"},
			])

	def test_default_openrouter_model_keeps_provider_and_omitted_temperature(self):
		from litellm.litellm_core_utils.get_llm_provider_logic import get_llm_provider
		role = InitialLogger(model_name="gpt-5-mini", temperature=0, cache=False)
		model, provider, _, _ = get_llm_provider(model=role.llm.model, api_base=role.llm.kwargs["api_base"])
		self.assertEqual((model, provider), ("openai/gpt-5-mini", "openrouter"))
		self.assertIsNone(role.llm.kwargs["temperature"])
		self.assertNotIn("api_provider", role.llm.kwargs)

	def test_model_context_restores_none_after_exception(self):
		role = make_role(InitialLogger)
		with dspy.context(lm=None):
			with self.assertRaises(RuntimeError):
				with role.use_model():
					self.assertIs(dspy.settings.lm, role.llm)
					raise RuntimeError("abort")
			self.assertIsNone(dspy.settings.lm)

	def test_nested_model_context_restores_outer_model(self):
		outer = make_role(InitialLogger)
		inner = make_role(InitialLogger)
		with outer.use_model():
			with inner.use_model():
				self.assertIs(dspy.settings.lm, inner.llm)
			self.assertIs(dspy.settings.lm, outer.llm)

	def test_role_api_failures_raise_instead_of_returning_old_code(self):
		cases = [
			(InitialLogger, "add_initial_logging_code", ("code", "outcome")),
			(LoggingCodeRefiner, "refine_logging_code", ("code", [], "add logs")),
			(LogSufficientEvaluator, "evaluate_log_sufficiency", ("code", [], "logs", "outcome")),
			(DirectCompilationFixer, "fix_compilation_error", ("code", [], "compile error")),
		]
		for role_type, method, args in cases:
			with self.subTest(role=role_type.__name__):
				role = make_role(role_type)
				failed_call = Mock(side_effect=ConnectionError("API unavailable"))
				with patch("dspy.ChainOfThought", return_value=failed_call):
					with self.assertRaises(RuntimeError) as raised:
						getattr(role, method)(*args, max_llm_retries=2)
				self.assertIsInstance(raised.exception.__cause__, ConnectionError)
				self.assertEqual(failed_call.call_count, 2)

	def test_evaluator_api_failure_preserves_exception_cause(self):
		cases = [
			(BaseDetectorAndRepairer, "detect", ("code",)),
			(BaseDetectorAndRepairer, "repair", ("code", "bug")),
			(IndirectBugDetector, "detect_with_general_logs", ([{"caller_code_snippet": "code", "runtime_log": "log"}], "method()")),
			(BugDetectionVerifier, "verify", ("bug", "code", "ground truth")),
			(CodeRepairVerifier, "verify", ("code", "bug", "repair", "ground truth")),
		]
		for role_type, method, args in cases:
			with self.subTest(role=role_type.__name__, method=method):
				role = make_role(role_type)
				failed_call = Mock(side_effect=ConnectionError("API unavailable"))
				with patch("dspy.ChainOfThought", return_value=failed_call):
					with self.assertRaises(RuntimeError) as raised:
						getattr(role, method)(*args, max_tries=2)
				self.assertIsInstance(raised.exception.__cause__, ConnectionError)
				self.assertEqual(failed_call.call_count, 2)

	def test_failed_container_launch_does_not_reuse_old_output(self):
		out_dir = self.root / "output"
		out_dir.mkdir()
		(out_dir / "input.json").write_text("{}")
		(out_dir / "output.json").write_text('{"status":"success"}')
		proc = subprocess.run([
			"bash", str(EXECUTOR_ROOT / "scripts/run_job.sh"),
			"--runtime", "/usr/bin/false", "--cache", str(self.root / "cache"),
			"--dataset", str(EXECUTOR_ROOT.parent / "datasets"),
			"--out", str(out_dir), "--input", str(out_dir / "input.json"),
		], capture_output=True, text=True)
		self.assertNotEqual(proc.returncode, 0)
		self.assertFalse((out_dir / "output.json").exists())

	def test_repeated_tail_is_reported(self):
		lines = ["start"] + ["repeat"] * 20
		logs = CodeRunner._collapse_repetitive_logs(lines, CodeRunner._detect_repetitive_logs(lines))
		self.assertIn("18 additional times", logs)
		self.assertTrue(logs.endswith("repeat"))

	def test_short_repeated_runs_are_not_dropped(self):
		lines = [line for _ in range(10) for line in ["repeat", "repeat", "other"]]
		logs = CodeRunner._collapse_repetitive_logs(lines, CodeRunner._detect_repetitive_logs(lines))
		self.assertEqual(logs, "\n".join(lines))

	def test_single_long_log_line_has_bounded_nonoverlapping_excerpt(self):
		logs = CodeRunner._process_runtime_logs("x" * 12000, "compile_success")
		self.assertLess(len(logs), CodeRunner.MAX_RUNTIME_LOGS_LENGTH)
		self.assertIn("4500 characters omitted", logs)
		self.assertNotIn("lines omitted", logs)

	def test_checkpoint_write_failure_is_exposed(self):
		output = self.root / "results.json"
		(output.with_name("results.json.tmp")).mkdir()
		with self.assertRaises(IsADirectoryError):
			save_checkpoint(output, [])

	def test_corrupted_checkpoint_is_not_overwritten(self):
		dataset_path = self.root / "dataset.json"
		dataset_path.write_text("[]")
		output = self.root / "results.json"
		output.write_text("corrupted")
		with self.assertRaises(json.JSONDecodeError):
			process_items_concurrent(str(dataset_path), str(output), max_workers=1)
		self.assertEqual(output.read_text(), "corrupted")

	def test_failed_checkpoint_is_retried_with_real_subprocess_failure(self):
		data = json.loads((EXECUTOR_ROOT.parent / "datasets/direct_debugging.json").read_text())
		item = next(x for x in data if x["defects4j_project"] == "Cli" and int(x["defects4j_bug_num"]) == 3)
		dataset_path = self.root / "dataset.json"
		dataset_path.write_text(json.dumps([item]))
		output = self.root / "results.json"
		output.write_text(json.dumps([{
			"metadata": {"defect4j_project": "Cli", "defect4j_bug_num": 3},
			"final_data": {"error": "previous failed attempt"},
		}]))
		process_items_concurrent(str(dataset_path), str(output), max_workers=1, save_interval=1,
			code_runner_config={"script_file_path": str(self.root / "missing-runner.sh"),
				"base_output_dir": str(self.root / "jobs")})
		results = json.loads(output.read_text())
		self.assertEqual(len(results), 1)
		self.assertIn("initial_data", results[0])
		self.assertIn("error", results[0]["final_data"])
		self.assertEqual(results[0]["initial_data"]["normalized_status"], "fatal_error")

	def test_direct_generation_error_is_not_counted_as_compilation_failure(self):
		rows = [{"metadata": {}, "final_data": {"error": "API failed"}}]
		items, _, compilation_failed, generation_failed = prepare_direct(rows, {})
		self.assertEqual(items, [])
		self.assertEqual((compilation_failed, generation_failed), (0, 1))

	def test_indirect_no_logs_is_not_a_compilation_failure(self):
		meta = {"jira_id": "issue", "commit_hash": "commit", "defect4j_project": "Cli", "defect4j_bug_num": 3}
		finals = [
			{"instrumented_code": "code", "runtime_logs": "No logs produced during execution.", "normalized_status": "compile_success"},
			{"instrumented_code": "broken", "runtime_logs": "", "normalized_status": "compile_failed"},
			{"instrumented_code": "old", "error": "API failed", "normalized_status": "fatal_error"},
		]
		data = [{"metadata": meta, "caller_methods_results": [{"result": {"final_data": final}} for final in finals]}]
		truth = {"issue_commit": {"signature": "method()", "bug_description": "bug", "code": "buggy"}}
		items, code, total, compilation_failed, generation_failed = prepare_indirect(data, truth)
		self.assertEqual((total, compilation_failed, generation_failed), (3, 1, 1))
		self.assertEqual(code, ["code"])
		self.assertEqual(len(items[0]["caller_code_snippet_2_log_map"]), 1)

	def test_missing_verification_is_separate_from_incorrect_detection(self):
		results = [{"detection": {"status": "success", "has_bug": True}, "bug_verification": None}]
		stats = calculate_statistics(results, 1, 0)
		self.assertEqual(stats["verification_failed_count"], 1)
		self.assertEqual(stats["incorrect_detect_count"], 0)

	def test_actual_nonzero_test_process_is_not_success(self):
		config = RunnerConfig(cache_root=self.root, dataset_metadata_path=self.root / "dataset.json",
			out_dir=self.root / "out", work_root=self.root, defects4j_cmd="/usr/bin/false",
			java_agent_path=self.root / "agent.jar")
		metadata = MetadataEntry(3, "Cli", "org.apache.commons.cli.TypeHandler", "method()", "test")
		output, _ = _run_test_and_collect(config, self.root, metadata)
		self.assertEqual(output.status, "fatal_error")
		self.assertIn("exited with code 1", output.message)

	def test_cache_waiter_reacquires_released_lock_after_failed_preparation(self):
		config = RunnerConfig(cache_root=self.root, dataset_metadata_path=self.root / "dataset.json",
			out_dir=self.root / "out", work_root=self.root, defects4j_cmd="/usr/bin/false",
			java_agent_path=self.root / "agent.jar", cache_lock_wait_seconds=1)
		entry = _cache_entry_dir(self.root, "Cli", 3)
		lock = entry / ".lock"
		lock.mkdir(parents=True)
		release = threading.Timer(0.05, lock.rmdir)
		release.start()
		self.addCleanup(release.join)
		# Reacquiring the lock must expose the checkout failure rather than time out.
		with self.assertRaisesRegex(RuntimeError, "checkout failed with code 1"):
			_ensure_cache_ready(config, "Cli", 3)
		self.assertFalse(lock.exists())

	def test_fatal_message_reaches_relog(self):
		outcome, status = CodeRunner._build_execution_outcome("fatal_error", "", "", "test process terminated")
		self.assertEqual(status, "fatal_error")
		self.assertIn("test process terminated", outcome)


if __name__ == "__main__":
	unittest.main()
