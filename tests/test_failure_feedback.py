from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXECUTOR_ROOT = PROJECT_ROOT / "executor"
sys.path.insert(0, str(EXECUTOR_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))

from d4j_executor.run import _extract_exception_stack_trace, _truncate_content
from relog.code_runner import CodeRunner


TARGET_TEST = "org.apache.commons.cli.PatternOptionBuilderTest::testSimplePattern"
ASSERTION_TRACE = "\n".join(
	[
		"junit.framework.AssertionFailedError: number flag n expected:<4.5> but was:<4.5>",
		"\tat junit.framework.Assert.fail(Assert.java:57)",
		"\tat junit.framework.Assert.failNotEquals(Assert.java:329)",
		"\tat junit.framework.Assert.assertEquals(Assert.java:78)",
		"\tat junit.framework.TestCase.assertEquals(TestCase.java:244)",
		"\tat org.apache.commons.cli.PatternOptionBuilderTest.testSimplePattern(PatternOptionBuilderTest.java:70)",
	]
)


class FailureFeedbackTest(unittest.TestCase):
	def setUp(self) -> None:
		cache_dir = EXECUTOR_ROOT / ".cache" / "tmp"
		cache_dir.mkdir(parents=True, exist_ok=True)
		self.workspace = tempfile.TemporaryDirectory(dir=cache_dir)
		self.addCleanup(self.workspace.cleanup)
		self.project_dir = Path(self.workspace.name)

	def write_failure(self, content: str) -> None:
		(self.project_dir / "failing_tests").write_text(content, encoding="utf-8")

	def test_assertion_after_target_method_returns_is_preserved(self) -> None:
		self.assertNotIn("org.apache.commons.cli.TypeHandler", ASSERTION_TRACE)
		self.write_failure(f"--- {TARGET_TEST}\n{ASSERTION_TRACE}\n")
		self.assertEqual(
			_extract_exception_stack_trace(self.project_dir, TARGET_TEST), ASSERTION_TRACE
		)

	def test_failure_reaches_relog_as_runtime_error(self) -> None:
		self.write_failure(f"--- {TARGET_TEST}\n{ASSERTION_TRACE}\n")
		trace = _truncate_content(_extract_exception_stack_trace(self.project_dir, TARGET_TEST))
		outcome, status = CodeRunner._build_execution_outcome("success", "", trace)
		self.assertEqual(status, "runtime_error")
		self.assertIn("AssertionFailedError", outcome)
		self.assertNotIn("Execution completed without exceptions", outcome)

	def test_exact_test_name_selects_only_its_failure(self) -> None:
		self.write_failure(
			f"--- {TARGET_TEST}Extra\njava.lang.IllegalStateException: unrelated\n"
			f"--- {TARGET_TEST}\n{ASSERTION_TRACE}\n"
			"--- other.Test::testOther\njava.lang.RuntimeException: other failure\n"
		)
		self.assertEqual(
			_extract_exception_stack_trace(self.project_dir, TARGET_TEST), ASSERTION_TRACE
		)

	def test_stack_frames_after_target_class_are_preserved(self) -> None:
		trace = (
			"java.lang.IllegalArgumentException: invalid number\n"
			"\tat org.apache.commons.cli.TypeHandler.createNumber(TypeHandler.java:40)\n"
			"\tat org.apache.commons.cli.PatternOptionBuilderTest.testSimplePattern(PatternOptionBuilderTest.java:70)"
		)
		self.write_failure(f"--- {TARGET_TEST}\n{trace}\n")
		self.assertEqual(_extract_exception_stack_trace(self.project_dir, TARGET_TEST), trace)

	def test_missing_failure_file_returns_no_exception(self) -> None:
		self.assertEqual(_extract_exception_stack_trace(self.project_dir, TARGET_TEST), "")

	def test_successful_test_does_not_inherit_other_test_failure(self) -> None:
		self.write_failure("--- other.Test::testOther\njava.lang.RuntimeException: unrelated\n")
		trace = _extract_exception_stack_trace(self.project_dir, TARGET_TEST)
		self.assertEqual(trace, "")
		_, status = CodeRunner._build_execution_outcome("success", "", trace)
		self.assertEqual(status, "compile_success")

	def test_failure_file_read_error_is_exposed(self) -> None:
		(self.project_dir / "failing_tests").mkdir()
		with self.assertRaises(IsADirectoryError):
			_extract_exception_stack_trace(self.project_dir, TARGET_TEST)


if __name__ == "__main__":
	unittest.main()
