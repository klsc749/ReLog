#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
DEFAULT_CACHE_DIR = (ROOT_DIR / ".cache" / "cache").resolve()
DEFAULT_DATASET_DIR = (ROOT_DIR.parent / "datasets").resolve()
DEFAULT_DIRECT_META_FILE = DEFAULT_DATASET_DIR / "direct_debugging.json"
DEFAULT_INDIRECT_META_FILE = DEFAULT_DATASET_DIR / "indirect_debugging.json"
DEFAULT_OUTPUT_ROOT = (ROOT_DIR / ".cache" / "comprehensive").resolve()


@dataclass(frozen=True)
class TestCase:
	case_no: int
	entry_id: int
	caller_index: int
	jira_id: str
	project: str
	bug_num: int
	buggy_code: str
	method_signature: str
	method_path: str = ""
	test_method: str = ""


def inject_hello_world_log(code: str, signature: str) -> str:
	lines = code.splitlines(keepends=True)
	brace_line = -1
	for i, line in enumerate(lines):
		if "{" in line:
			brace_line = i
			break
	if brace_line == -1:
		print(f"skip injection: {signature[:50]}")
		return code
	insert_after = brace_line
	in_block_comment = False
	for i in range(brace_line + 1, len(lines)):
		stripped = lines[i].strip()
		if not stripped:
			continue
		if in_block_comment:
			if "*/" in stripped:
				in_block_comment = False
			continue
		if stripped.startswith("/*"):
			if "*/" not in stripped:
				in_block_comment = True
			continue
		if stripped.startswith("//"):
			continue
		if stripped.startswith("this(") or stripped.startswith("super("):
			insert_after = i
			continue
		break
	indent = ""
	if insert_after + 1 < len(lines):
		line = lines[insert_after + 1]
		indent = line[: len(line) - len(line.lstrip())]
	lines.insert(insert_after + 1, f'{indent}System.out.println("HelloWorld");\n')
	return "".join(lines)


def _safe_int(value: Any, default: int = -1) -> int:
	try:
		return int(value)
	except Exception:
		return default


def load_dataset(meta_file: Path) -> List[Dict[str, Any]]:
	return json.loads(meta_file.read_text(encoding="utf-8"))


def _sanitize_for_path(value: str) -> str:
	s = "".join(ch if ch.isalnum() or ch in ("-", "_", ".", "@") else "_" for ch in (value or ""))
	return s[:120] if len(s) > 120 else s


def generate_direct_cases(dataset: List[Dict[str, Any]], limit: Optional[int]) -> List[TestCase]:
	out: List[TestCase] = []
	case_no = 0
	entries = dataset[:limit] if limit else dataset
	for entry in entries:
		buggy_code = entry.get("buggy_code") or ""
		project = entry.get("defects4j_project") or ""
		bug_num = entry.get("defects4j_bug_num")
		if not buggy_code or not project or not bug_num:
			continue
		case_no += 1
		out.append(
			TestCase(
				case_no=case_no,
				entry_id=_safe_int(entry.get("id", -1)),
				caller_index=-1,
				jira_id=str(entry.get("jira_id", "")),
				project=str(project),
				bug_num=_safe_int(bug_num),
				buggy_code=str(buggy_code),
				method_signature=str(entry.get("main_method_signature", "")),
			)
		)
	return out


def generate_indirect_cases(
	dataset: List[Dict[str, Any]],
	limit: Optional[int],
	caller_limit: Optional[int],
) -> List[TestCase]:
	out: List[TestCase] = []
	case_no = 0
	entries = dataset[:limit] if limit else dataset
	for entry in entries:
		project = entry.get("defects4j_project") or ""
		bug_num = entry.get("defects4j_bug_num")
		jira_id = str(entry.get("jira_id", ""))
		entry_id = _safe_int(entry.get("id", -1))
		trigger_tests = entry.get("trigger_test_methods") or []
		test_method = str(trigger_tests[0]) if trigger_tests else ""
		if not project or not bug_num or not test_method:
			continue
		callers = entry.get("caller_methods") or []
		if caller_limit is not None:
			callers = callers[:caller_limit]
		for idx, caller in enumerate(callers):
			if not isinstance(caller, dict):
				continue
			code = caller.get("code") or ""
			signature = caller.get("signature") or ""
			method_path = caller.get("file_path") or caller.get("class_name") or ""
			if not code or not signature or not method_path:
				continue
			case_no += 1
			out.append(
				TestCase(
					case_no=case_no,
					entry_id=entry_id,
					caller_index=idx,
					jira_id=jira_id,
					project=str(project),
					bug_num=_safe_int(bug_num),
					buggy_code=str(code),
					method_signature=str(signature),
					method_path=str(method_path),
					test_method=test_method,
				)
			)
	return out


def _run_job(
	case: TestCase,
	*,
	output_root: Path,
	image: str,
	runtime: str,
	cache_dir: Path,
	dataset_dir: Path,
	mode: str,
	network: str,
	proxy: str,
	no_proxy: str,
) -> Dict[str, Any]:
	start = time.time()
	case_key = f"{case.project}-{case.bug_num}"
	case_name = f"case_{case.case_no}_{case.entry_id}_{_sanitize_for_path(case.jira_id)}_{case_key}"
	if mode == "indirect":
		case_name += f"_caller_{case.caller_index}_{_sanitize_for_path(case.method_path)}"
	case_dir = output_root / case_name
	case_dir.mkdir(parents=True, exist_ok=True)
	injected = inject_hello_world_log(case.buggy_code, case.method_signature)
	input_json = {
		"defects4j_bug_num": case.bug_num,
		"defects4j_project": case.project,
		"buggy_code_with_logging_code": injected,
	}
	if case.method_path:
		input_json["method_path"] = case.method_path
	if case.method_signature:
		input_json["method_signature"] = case.method_signature
	if case.test_method:
		input_json["test_method"] = case.test_method
	input_path = case_dir / "input.json"
	input_path.write_text(json.dumps(input_json, indent=2, ensure_ascii=False), encoding="utf-8")
	cmd = [
		"bash",
		str(ROOT_DIR / "scripts" / "run_job.sh"),
		"--runtime",
		runtime,
		"--image",
		image,
		"--cache",
		str(cache_dir),
		"--out",
		str(case_dir),
		"--input",
		str(input_path),
	]
	if mode == "direct":
		cmd += ["--dataset", str(dataset_dir)]
	else:
		cmd += ["--no-dataset"]
	if network:
		cmd += ["--network", network]
	if proxy:
		cmd += ["--proxy", proxy, "--no-proxy", no_proxy]
	proc = subprocess.run(cmd, capture_output=True, text=True)
	(case_dir / "orchestrator_stdout.txt").write_text(proc.stdout, encoding="utf-8")
	(case_dir / "orchestrator_stderr.txt").write_text(proc.stderr, encoding="utf-8")
	output_path = case_dir / "output.json"
	status = "fatal_error"
	message = ""
	has_hello = False
	if output_path.exists():
		try:
			data = json.loads(output_path.read_text(encoding="utf-8"))
			status = data.get("status", "fatal_error")
			message = str(data.get("message", ""))
			logs = str(data.get("buggy_code_runtime_logs", "") or "")
			has_hello = "HelloWorld" in logs
		except Exception as exc:
			status = "fatal_error"
			message = f"Failed to parse output.json: {exc}"
	duration = time.time() - start
	success = status == "success" and has_hello
	return {
		"case_no": case.case_no,
		"entry_id": case.entry_id,
		"caller_index": case.caller_index,
		"jira_id": case.jira_id,
		"project": case.project,
		"bug_num": case.bug_num,
		"status": status,
		"has_hello_world": has_hello,
		"success": success,
		"message": message,
		"duration": duration,
		"returncode": proc.returncode,
		"case_dir": str(case_dir),
	}


def _print_summary(stats: Dict[str, Any]) -> None:
	print("=" * 80)
	print("container test summary")
	print("=" * 80)
	print(f"total: {stats['total_tests']}")
	print(f"success: {stats['success_count']} ({stats['success_rate']})")
	print(f"fail: {stats['fail_count']}")
	print(f"duration: {stats['total_duration']}")
	print(f"avg: {stats['avg_duration']}")
	failed = [r for r in stats["results"] if not r["success"]]
	if failed:
		print("failed cases:")
		for result in failed[:10]:
			print(
				f"[{result['case_no']}] {result['project']}-{result['bug_num']} status={result['status']} hello={result['has_hello_world']} rc={result['returncode']} dir={result['case_dir']}"
			)


def main() -> int:
	parser = argparse.ArgumentParser()
	parser.add_argument("--mode", choices=["direct", "indirect"], default="direct")
	parser.add_argument("--meta-file", type=Path, default=None)
	parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
	parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET_DIR)
	parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
	parser.add_argument("--image", default="localhost/d4j-runner:latest")
	parser.add_argument("--runtime", default=os.environ.get("CONTAINER_RUNTIME", "podman"))
	parser.add_argument("--workers", type=int, default=8)
	parser.add_argument("--limit", type=int, default=0)
	parser.add_argument("--caller-limit", type=int, default=0)
	parser.add_argument("--network", default=os.environ.get("RUN_NETWORK", ""))
	parser.add_argument("--proxy", default=os.environ.get("PROXY", ""))
	parser.add_argument("--no-proxy", default=os.environ.get("NO_PROXY", "localhost,127.0.0.1"))
	args = parser.parse_args()
	meta_file = args.meta_file.resolve() if args.meta_file else (
		DEFAULT_DIRECT_META_FILE if args.mode == "direct" else DEFAULT_INDIRECT_META_FILE
	)
	cache_dir = args.cache_dir.resolve()
	dataset_dir = args.dataset_dir.resolve()
	output_root = args.output_root.resolve()
	if not meta_file.exists():
		print(f"missing meta file: {meta_file}")
		return 2
	if not dataset_dir.exists():
		print(f"missing dataset dir: {dataset_dir}")
		return 2
	cache_dir.mkdir(parents=True, exist_ok=True)
	output_root.mkdir(parents=True, exist_ok=True)
	limit = args.limit if args.limit > 0 else None
	caller_limit = args.caller_limit if args.caller_limit > 0 else None
	dataset = load_dataset(meta_file)
	if args.mode == "direct":
		cases = generate_direct_cases(dataset, limit)
	else:
		cases = generate_indirect_cases(dataset, limit, caller_limit)
	if not cases:
		print("no cases generated")
		return 2
	run_dir = output_root / f"run_{args.mode}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
	run_dir.mkdir(parents=True, exist_ok=True)
	results: List[Dict[str, Any]] = []
	start = time.time()
	with ProcessPoolExecutor(max_workers=args.workers) as pool:
		futures = [
			pool.submit(
				_run_job,
				case,
				output_root=run_dir,
				image=args.image,
				runtime=args.runtime,
				cache_dir=cache_dir,
				dataset_dir=dataset_dir,
				mode=args.mode,
				network=args.network,
				proxy=args.proxy,
				no_proxy=args.no_proxy,
			)
			for case in cases
		]
		total = len(futures)
		done = 0
		for future in as_completed(futures):
			done += 1
			result = future.result()
			results.append(result)
			print(
				f"[{done}/{total}] {result['project']}-{result['bug_num']} status={result['status']} hello={result['has_hello_world']} rc={result['returncode']} ({result['duration']:.2f}s)"
			)
	total_duration = time.time() - start
	success_count = sum(1 for result in results if result["success"])
	total_tests = len(results)
	fail_count = total_tests - success_count
	stats: Dict[str, Any] = {
		"total_tests": total_tests,
		"success_count": success_count,
		"fail_count": fail_count,
		"success_rate": f"{(success_count / total_tests * 100):.1f}%" if total_tests else "0%",
		"total_duration": f"{total_duration:.2f}s",
		"avg_duration": f"{(total_duration / total_tests):.2f}s" if total_tests else "0s",
		"mode": args.mode,
		"meta_file": str(meta_file),
		"cache_dir": str(cache_dir),
		"dataset_dir": str(dataset_dir),
		"output_root": str(output_root),
		"run_dir": str(run_dir),
		"results": results,
	}
	report = run_dir / "test_report.json"
	report.write_text(json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")
	_print_summary(stats)
	print(f"report: {report}")
	return 0 if fail_count == 0 else 1


if __name__ == "__main__":
	raise SystemExit(main())
