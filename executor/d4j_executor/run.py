from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .java_path_converter import class_path_to_file_path, file_path_to_class_path
from .models import InputData, MetadataEntry, OutputData
from .patcher import JavaPatcher


@dataclass(frozen=True)
class RunnerConfig:
	cache_root: Path
	dataset_metadata_path: Path
	out_dir: Path
	work_root: Path

	defects4j_cmd: str
	java_agent_path: Path
	cache_include_git: bool = False
	build_cache_home: Optional[Path] = None

	auto_capture_log_name: str = "auto_capture.log"
	max_log_lines: int = 100
	test_timeout_seconds: int = 300
	log_check_interval_seconds: int = 2
	cache_lock_wait_seconds: int = 1800

	@staticmethod
	def from_env() -> "RunnerConfig":
		cache_root = Path(os.environ.get("D4J_CACHE_ROOT", "/cache")).resolve()
		out_dir = Path(os.environ.get("D4J_OUT_DIR", "/out")).resolve()
		work_root = Path(os.environ.get("D4J_WORK_ROOT", "/work")).resolve()
		dataset_metadata_path = Path(
			os.environ.get("D4J_METADATA_PATH", "/dataset/direct_debugging.json")
		).resolve()

		defects4j_cmd = os.environ.get("DEFECTS4J_CMD", "defects4j")
		java_agent_path = Path(
			os.environ.get("D4J_JAVA_AGENT_PATH", "/opt/agent/SystemOutHookAgent.jar")
		).resolve()
		cache_include_git = os.environ.get("D4J_CACHE_INCLUDE_GIT", "0") in (
			"1",
			"true",
			"TRUE",
			"yes",
			"YES",
		)
		build_cache_home_env = os.environ.get("D4J_BUILD_CACHE_HOME", "").strip()
		build_cache_home = Path(build_cache_home_env).resolve() if build_cache_home_env else None

		return RunnerConfig(
			cache_root=cache_root,
			dataset_metadata_path=dataset_metadata_path,
			out_dir=out_dir,
			work_root=work_root,
			defects4j_cmd=defects4j_cmd,
			java_agent_path=java_agent_path,
			cache_include_git=cache_include_git,
			build_cache_home=build_cache_home,
			auto_capture_log_name=os.environ.get("D4J_AUTO_CAPTURE_LOG", "auto_capture.log"),
			max_log_lines=int(os.environ.get("D4J_MAX_LOG_LINES", "100")),
			test_timeout_seconds=int(os.environ.get("D4J_TEST_TIMEOUT_SECONDS", "300")),
			log_check_interval_seconds=int(os.environ.get("D4J_LOG_CHECK_INTERVAL_SECONDS", "2")),
			cache_lock_wait_seconds=int(os.environ.get("D4J_CACHE_LOCK_WAIT_SECONDS", "1800")),
		)


def _sha256_file(path: Path) -> str:
	hasher = hashlib.sha256()
	with open(path, "rb") as f:
		for chunk in iter(lambda: f.read(1024 * 1024), b""):
			hasher.update(chunk)
	return hasher.hexdigest()


def _write_text_atomic(path: Path, content: str, encoding: str = "utf-8") -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	tmp = path.with_name(path.name + f".tmp.{os.getpid()}.{uuid.uuid4().hex}")
	tmp.write_text(content, encoding=encoding)
	os.replace(tmp, path)


def _write_json_atomic(path: Path, data: Dict[str, Any]) -> None:
	_write_text_atomic(path, json.dumps(data, indent=2, ensure_ascii=False))


def _cache_entry_dir(cache_root: Path, project: str, bug_num: int) -> Path:
	return cache_root / "d4j-src" / project.lower() / f"{bug_num}b"


def _load_metadata_map(metadata_path: Path) -> Dict[str, MetadataEntry]:
	if not metadata_path.exists():
		raise FileNotFoundError(f"Metadata file not found: {metadata_path}")

	data = json.loads(metadata_path.read_text(encoding="utf-8"))
	out: Dict[str, MetadataEntry] = {}
	for item in data:
		entry = MetadataEntry.from_dict(item)
		key = f"{entry.defects4j_project.lower()}-{entry.defects4j_bug_num}"
		out[key] = entry
	return out


def _find_metadata(metadata_map: Dict[str, MetadataEntry], project: str, bug_num: int) -> Optional[MetadataEntry]:
	return metadata_map.get(f"{project.lower()}-{bug_num}")


def _run_cmd(
	cmd: list[str],
	*,
	cwd: Optional[Path] = None,
	env: Optional[Dict[str, str]] = None,
	stdout_path: Optional[Path] = None,
) -> int:
	if stdout_path is None:
		return subprocess.run(cmd, cwd=str(cwd) if cwd else None, env=env, check=False).returncode

	stdout_path.parent.mkdir(parents=True, exist_ok=True)
	with open(stdout_path, "w", encoding="utf-8") as fp:
		proc = subprocess.Popen(
			cmd,
			cwd=str(cwd) if cwd else None,
			env=env,
			stdout=fp,
			stderr=subprocess.STDOUT,
			text=True,
		)
		return proc.wait()


def _ensure_cache_ready(config: RunnerConfig, project: str, bug_num: int) -> Tuple[Path, bool]:
	entry_dir = _cache_entry_dir(config.cache_root, project, bug_num)
	ready_flag = entry_dir / ".ready"
	archive_path = entry_dir / "src.tar.zst"
	lock_dir = entry_dir / ".lock"

	if ready_flag.exists() and archive_path.exists():
		return entry_dir, True

	entry_dir.mkdir(parents=True, exist_ok=True)

	start = time.monotonic()
	while True:
		if ready_flag.exists() and archive_path.exists():
			return entry_dir, True
		try:
			lock_dir.mkdir()
		except FileExistsError:
			if time.monotonic() - start >= config.cache_lock_wait_seconds:
				raise TimeoutError(
					f"Cache prepare timeout waiting for {project}-{bug_num}b under {entry_dir}"
				)
			time.sleep(1)
			continue
		try:
			if ready_flag.exists() and archive_path.exists():
				return entry_dir, True
			_prepare_cache_entry(config, entry_dir, project, bug_num)
			return entry_dir, False
		finally:
			lock_dir.rmdir()


def _prepare_cache_entry(config: RunnerConfig, entry_dir: Path, project: str, bug_num: int) -> None:
	archive_path = entry_dir / "src.tar.zst"
	manifest_path = entry_dir / "manifest.json"
	ready_flag = entry_dir / ".ready"

	ready_flag.unlink(missing_ok=True)

	prepare_id = uuid.uuid4().hex[:12]
	checkout_dir = config.work_root / f"prepare_{project.lower()}_{bug_num}b_{prepare_id}"
	if checkout_dir.exists():
		shutil.rmtree(checkout_dir, ignore_errors=True)
	checkout_dir.mkdir(parents=True, exist_ok=True)

	try:
		cmd = [
			config.defects4j_cmd,
			"checkout",
			"-p",
			project,
			"-v",
			f"{bug_num}b",
			"-w",
			str(checkout_dir),
		]
		ret = _run_cmd(cmd)
		if ret != 0:
			raise RuntimeError(f"defects4j checkout failed with code {ret}: {' '.join(cmd)}")

		if not config.cache_include_git:
			shutil.rmtree(checkout_dir / ".git", ignore_errors=True)

		tmp_archive = archive_path.with_name(archive_path.name + f".tmp.{os.getpid()}.{uuid.uuid4().hex}")
		entry_dir.mkdir(parents=True, exist_ok=True)

		tar_cmd = [
			"tar",
			"--zstd",
			"-cf",
			str(tmp_archive),
			"-C",
			str(checkout_dir),
			".",
		]
		ret = _run_cmd(tar_cmd)
		if ret != 0:
			raise RuntimeError(f"tar zstd failed with code {ret}: {' '.join(tar_cmd)}")

		sha256 = _sha256_file(tmp_archive)
		manifest = {
			"project": project,
			"bug_num": bug_num,
			"version": f"{bug_num}b",
			"archive": "src.tar.zst",
			"sha256": sha256,
			"created_at_epoch": int(time.time()),
		}

		tmp_manifest = manifest_path.with_name(manifest_path.name + f".tmp.{os.getpid()}.{uuid.uuid4().hex}")
		_write_json_atomic(tmp_manifest, manifest)

		os.replace(tmp_archive, archive_path)
		os.replace(tmp_manifest, manifest_path)
		ready_flag.touch()
	finally:
		shutil.rmtree(checkout_dir, ignore_errors=True)


def _extract_archive_to_workspace(archive_path: Path, work_dir: Path) -> None:
	work_dir.mkdir(parents=True, exist_ok=True)
	cmd = ["tar", "--zstd", "-xf", str(archive_path), "-C", str(work_dir)]
	ret = _run_cmd(cmd)
	if ret != 0:
		raise RuntimeError(f"tar extract failed with code {ret}: {' '.join(cmd)}")


def _normalize_runtime_logs(logs: str) -> str:
	lines = logs.splitlines()
	return "\n".join(line.replace("    [junit] ", "") for line in lines)


def _check_compilation_failed(defects4j_logs: str) -> bool:
	if not defects4j_logs:
		return False
	if "Running ant (compile.tests)....FAIL" in defects4j_logs:
		return True
	if "Running ant (compile)....FAIL" in defects4j_logs:
		return True
	if "Compile failed" in defects4j_logs or "compilation failed" in defects4j_logs:
		return True
	return False


def _get_compilation_error_info(defects4j_logs: str) -> str:
	if not defects4j_logs:
		return ""
	lines = defects4j_logs.split("\n")
	out: list[str] = []
	for i, line in enumerate(lines):
		if "[javac]" in line and "error:" in line:
			out.append(line)
			for j in range(i + 1, min(i + 5, len(lines))):
				if "[javac]" in lines[j] or lines[j].strip() == "" or "^" in lines[j]:
					out.append(lines[j])
				else:
					break
			out.append("")
		if "[javac]" in line and (" error" in line or " errors" in line):
			out.append(line)
	if not out:
		for line in lines:
			if "BUILD FAILED" in line or "Compile failed" in line:
				out.append(line)
	return "\n".join(out).strip()


def _extract_exception_stack_trace(project_dir: Path, target_test: str) -> str:
	failing_tests = project_dir / "failing_tests"
	if not failing_tests.exists():
		return ""
	lines = failing_tests.read_text(encoding="utf-8").splitlines()
	for start_idx, line in enumerate(lines):
		if line.strip() != f"--- {target_test}":
			continue
		end_idx = len(lines)
		for i in range(start_idx + 1, len(lines)):
			if lines[i].startswith("---"):
				end_idx = i
				break
		# Assertions may fail after the target method returns, without its class on the stack.
		return "\n".join(lines[start_idx + 1 : end_idx]).strip()
	return ""


def _truncate_content(content: str, core_char_limit: int = 500, stack_char_limit: int = 200) -> str:
	if not content:
		return ""
	lines = content.splitlines()
	core_lines: list[str] = []
	stack_lines: list[str] = []
	i = 0
	while i < len(lines):
		if lines[i].startswith("\tat "):
			break
		core_lines.append(lines[i])
		i += 1
	while i < len(lines):
		stack_lines.append(lines[i])
		i += 1
	core = "\n".join(core_lines)
	stack = "\n".join(stack_lines)
	if len(core) > core_char_limit:
		core = core[:core_char_limit] + "[...TRUNCATED]"
	if len(stack) > stack_char_limit:
		stack = stack[:stack_char_limit] + "[...TRUNCATED]"
	if not stack.strip():
		return core
	if not core.strip():
		return stack
	return core + "\n" + stack


def _run_test_and_collect(
	config: RunnerConfig,
	project_dir: Path,
	metadata: MetadataEntry,
) -> Tuple[OutputData, Dict[str, Any]]:
	out_dir = config.out_dir
	out_dir.mkdir(parents=True, exist_ok=True)

	defects4j_stdout_path = out_dir / "defects4j_stdout.txt"
	log_file = project_dir / config.auto_capture_log_name
	failing_tests_path = project_dir / "failing_tests"

	cmd = [
		config.defects4j_cmd,
		"test",
		"-t",
		metadata.test_method,
	]

	env = os.environ.copy()
	if config.build_cache_home is not None:
		env["HOME"] = str(config.build_cache_home)
	env["JAVA_TOOL_OPTIONS"] = f"-javaagent:{config.java_agent_path}={metadata.main_method_path}"

	start_time = time.time()
	timeout_occurred = False
	log_exceeded = False

	with open(defects4j_stdout_path, "w", encoding="utf-8") as stdout_fp:
		proc = subprocess.Popen(
			cmd,
			cwd=str(project_dir),
			env=env,
			stdout=stdout_fp,
			stderr=subprocess.STDOUT,
			text=True,
			start_new_session=True,
		)

		try:
			while True:
				return_code = proc.poll()
				if return_code is not None:
					break
				if time.time() - start_time >= config.test_timeout_seconds:
					timeout_occurred = True
					break
				if log_file.exists():
					with open(log_file, "r", encoding="utf-8") as fp:
						line_count = sum(1 for _ in fp)
					if line_count > config.max_log_lines:
						log_exceeded = True
						break
				time.sleep(config.log_check_interval_seconds)
		finally:
			if proc.poll() is None:
				try:
					os.killpg(proc.pid, signal.SIGKILL)
				except ProcessLookupError:
					pass
			proc.wait()

	defects4j_logs = defects4j_stdout_path.read_text(encoding="utf-8")
	runtime_logs = ""
	if log_file.exists():
		runtime_logs = _normalize_runtime_logs(log_file.read_text(encoding="utf-8"))

	if timeout_occurred:
		output = OutputData(
			buggy_code_runtime_logs=runtime_logs,
			defects4j_logs=defects4j_logs,
			status="test_timeout",
			message=f"Test execution timeout after {config.test_timeout_seconds} seconds",
		)
		return output, {"timeout": True, "log_exceeded": log_exceeded}

	if _check_compilation_failed(defects4j_logs):
		compilation_err = _get_compilation_error_info(defects4j_logs)
		output = OutputData(
			buggy_code_runtime_logs=runtime_logs,
			defects4j_logs=defects4j_logs,
			status="compile_failed",
			message="Java compilation failed",
			compilation_err_info=compilation_err,
		)
		return output, {"timeout": False, "log_exceeded": log_exceeded}

	if log_exceeded or proc.returncode != 0:
		message = (
			f"Test terminated after exceeding the configured runtime log limit ({config.max_log_lines} lines)"
			if log_exceeded
			else f"defects4j test exited with code {proc.returncode}"
		)
		return OutputData(
			buggy_code_runtime_logs=runtime_logs,
			defects4j_logs=defects4j_logs,
			status="fatal_error",
			message=message,
		), {"timeout": False, "log_exceeded": log_exceeded}

	exception_trace = _extract_exception_stack_trace(project_dir, metadata.test_method)

	message = "Successfully collected logs"
	if log_exceeded:
		message = (
			f"Successfully collected logs ({len(runtime_logs.splitlines())} lines, exceeded threshold of {config.max_log_lines})"
		)

	output = OutputData(
		buggy_code_runtime_logs=runtime_logs,
		defects4j_logs=defects4j_logs,
		status="success",
		message=message,
		exception_stack_trace=_truncate_content(exception_trace),
	)
	return output, {"timeout": False, "log_exceeded": log_exceeded, "failing_tests_exists": failing_tests_path.exists()}


def _copy_if_exists(src: Path, dst: Path) -> None:
	if not src.exists():
		return
	dst.parent.mkdir(parents=True, exist_ok=True)
	shutil.copyfile(src, dst)


def _looks_like_file_path(value: str) -> bool:
	if not value:
		return False
	s = value.strip()
	return (
		"/" in s
		or "\\" in s
		or s.endswith(".java")
		or s.startswith("src/")
		or s.startswith("./")
		or s.startswith("../")
	)


def _resolve_workspace_path(work_dir: Path, method_path: str) -> Path:
	root = work_dir.resolve()
	p = Path(method_path)
	if not p.is_absolute():
		p = (root / p).resolve()
	else:
		p = p.resolve()

	try:
		p.relative_to(root)
	except Exception as e:
		raise ValueError(f"method_path points outside workspace: {method_path}") from e
	return p


def main() -> int:
	config = RunnerConfig.from_env()
	config.work_root.mkdir(parents=True, exist_ok=True)
	config.out_dir.mkdir(parents=True, exist_ok=True)

	input_path = Path(os.environ.get("D4J_INPUT_PATH", str(config.out_dir / "input.json")))
	output_path = Path(os.environ.get("D4J_OUTPUT_PATH", str(config.out_dir / "output.json")))
	defects4j_stdout_path = config.out_dir / "defects4j_stdout.txt"
	run_meta_path = config.out_dir / "run_meta.json"

	job_id = os.environ.get("D4J_JOB_ID", uuid.uuid4().hex[:12])

	def fatal(message: str) -> int:
		try:
			if not defects4j_stdout_path.exists():
				_write_text_atomic(defects4j_stdout_path, message + "\n")
		except Exception:
			pass

		try:
			run_meta_min = {"job_id": job_id, "fatal_error": True, "message": message, "ended_at_epoch": int(time.time())}
			_write_json_atomic(run_meta_path, run_meta_min)
		except Exception:
			pass

		out = OutputData(
			buggy_code_runtime_logs="",
			defects4j_logs="",
			status="fatal_error",
			message=message,
		)
		_write_text_atomic(output_path, json.dumps(out.to_dict(), indent=2, ensure_ascii=False))
		return 0

	if not input_path.exists():
		return fatal(f"Input file not found: {input_path}")

	try:
		input_dict = json.loads(input_path.read_text(encoding="utf-8"))
	except Exception as e:
		return fatal(f"Failed to read/parse input.json: {e}")

	try:
		input_data = InputData.from_dict(input_dict)
	except Exception as e:
		return fatal(f"Failed to parse input data: {e}")

	method_path_in = (input_data.method_path or "").strip()
	method_sig_in = (input_data.method_signature or "").strip()
	test_method_in = (input_data.test_method or "").strip()

	need_metadata_fallback = (not method_path_in) or (not method_sig_in) or (not test_method_in)
	metadata_from_dataset: Optional[MetadataEntry] = None
	if need_metadata_fallback:
		try:
			metadata_map = _load_metadata_map(config.dataset_metadata_path)
			metadata_from_dataset = _find_metadata(
				metadata_map, input_data.defects4j_project, input_data.defects4j_bug_num
			)
		except Exception as e:
			return fatal(f"Failed to load dataset metadata: {e}")

		if metadata_from_dataset is None:
			missing_fields = []
			if not method_path_in:
				missing_fields.append("method_path")
			if not method_sig_in:
				missing_fields.append("method_signature")
			if not test_method_in:
				missing_fields.append("test_method")
			return fatal(
				"Missing required fields in input.json and cannot fallback to dataset metadata. "
				f"missing={missing_fields} "
				f"metadata_path={config.dataset_metadata_path}"
			)

	method_path_resolved = method_path_in
	method_sig_resolved = method_sig_in
	test_method_resolved = test_method_in
	if not method_path_resolved or not method_sig_resolved or not test_method_resolved:
		if metadata_from_dataset is None:
			return fatal(
				"Internal error: metadata fallback is required but metadata_from_dataset is None "
				f"(project={input_data.defects4j_project}, bug={input_data.defects4j_bug_num})"
			)
		if not method_path_resolved:
			method_path_resolved = metadata_from_dataset.main_method_path
		if not method_sig_resolved:
			method_sig_resolved = metadata_from_dataset.main_method_signature
		if not test_method_resolved:
			test_method_resolved = metadata_from_dataset.test_method

	if method_path_in and not _looks_like_file_path(method_path_in):
		agent_target = method_path_in
	elif metadata_from_dataset is not None:
		agent_target = metadata_from_dataset.main_method_path
	else:
		agent_target = file_path_to_class_path(method_path_resolved) if _looks_like_file_path(method_path_resolved) else method_path_resolved

	metadata = MetadataEntry(
		defects4j_bug_num=input_data.defects4j_bug_num,
		defects4j_project=input_data.defects4j_project,
		main_method_path=agent_target,
		main_method_signature=method_sig_resolved,
		test_method=test_method_resolved,
	)

	run_meta: Dict[str, Any] = {
		"job_id": job_id,
		"project": input_data.defects4j_project,
		"bug_num": input_data.defects4j_bug_num,
		"started_at_epoch": int(time.time()),
		"method_path_input": method_path_in,
		"method_signature_input": method_sig_in,
		"test_method_input": test_method_in,
		"method_path_resolved": method_path_resolved,
		"method_signature_resolved": method_sig_resolved,
		"test_method_resolved": test_method_resolved,
		"agent_target": agent_target,
	}

	try:
		cache_entry, cache_hit = _ensure_cache_ready(config, input_data.defects4j_project, input_data.defects4j_bug_num)
		run_meta["cache_entry"] = str(cache_entry)
		run_meta["cache_hit"] = cache_hit
	except Exception as e:
		return fatal(f"Failed to ensure cache: {e}")

	archive_path = cache_entry / "src.tar.zst"

	work_dir = config.work_root / f"job_{job_id}"
	if work_dir.exists():
		shutil.rmtree(work_dir, ignore_errors=True)
	work_dir.mkdir(parents=True, exist_ok=True)

	try:
		_extract_archive_to_workspace(archive_path, work_dir)
	except Exception as e:
		return fatal(f"Failed to extract archive: {e}")

	try:
		if _looks_like_file_path(method_path_resolved):
			source_file = _resolve_workspace_path(work_dir, method_path_resolved)
		else:
			source_file = class_path_to_file_path(method_path_resolved, work_dir)
		original_code = source_file.read_text(encoding="utf-8", errors="replace")
		patched = JavaPatcher().patch_method(
			original_code, method_sig_resolved, input_data.buggy_code_with_logging_code
		)
		source_file.write_text(patched, encoding="utf-8")
	except Exception as e:
		return fatal(f"Failed to patch source file: {e}")

	try:
		output, extra = _run_test_and_collect(config, work_dir, metadata)
		run_meta.update(extra)
	except Exception as e:
		return fatal(f"Failed to run defects4j test: {e}")

	_write_text_atomic(output_path, json.dumps(output.to_dict(), indent=2, ensure_ascii=False))
	_copy_if_exists(work_dir / config.auto_capture_log_name, config.out_dir / "auto_capture.log")
	_copy_if_exists(work_dir / "failing_tests", config.out_dir / "failing_tests")
	run_meta["ended_at_epoch"] = int(time.time())
	_write_json_atomic(run_meta_path, run_meta)

	if os.environ.get("D4J_KEEP_WORKSPACE", "0") not in ("1", "true", "TRUE", "yes", "YES"):
		shutil.rmtree(work_dir, ignore_errors=True)

	return 0


if __name__ == "__main__":
	raise SystemExit(main())
