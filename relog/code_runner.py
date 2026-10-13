import json
import os
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
base_output_path = str(REPO_ROOT / ".cache/runs/direct")
source3_output_path = str(REPO_ROOT / ".cache/runs/indirect")
script_path = str(REPO_ROOT / "executor/scripts/run_job.sh")
working_dir = str(REPO_ROOT)


class CodeRunner:
	@staticmethod
	def configure_paths(
		base_output_dir=None, source3_output_dir=None, script_file_path=None, working_dir_path=None
	):
		global base_output_path, source3_output_path, script_path, working_dir
		if base_output_dir:
			base_output_path = str(base_output_dir)
		if source3_output_dir:
			source3_output_path = str(source3_output_dir)
		if script_file_path:
			script_path = str(script_file_path)
		if working_dir_path:
			working_dir = str(working_dir_path)

	MAX_RUNTIME_LOGS_LENGTH = 10000
	MAX_ERROR_MESSAGE_LENGTH = 2000
	TRUNCATE_MESSAGE = "\n...[LOG TRUNCATED - Too verbose]..."

	@staticmethod
	def run_code(defects4j_bug_num, defects4j_project, code_snippet):
		input_data = {
			"defects4j_bug_num": defects4j_bug_num,
			"defects4j_project": defects4j_project,
			"buggy_code_with_logging_code": code_snippet,
		}

		in_out_dir = f"{base_output_path}/{defects4j_project}_{defects4j_bug_num}"
		os.makedirs(in_out_dir, exist_ok=True)

		input_file_path = os.path.join(in_out_dir, "input.json")
		output_file_path = os.path.join(in_out_dir, "output.json")

		Path(output_file_path).unlink(missing_ok=True)
		with open(input_file_path, "w", encoding="utf-8") as f:
			json.dump(input_data, f, indent=4)

		command = ["bash", script_path, "--out", in_out_dir, "--input", input_file_path]

		try:
			subprocess.run(
				command,
				check=True,
				capture_output=True,
				text=True,
				cwd=working_dir,
			)
			print(f"✅ Code run successful for {defects4j_project} {defects4j_bug_num}")
		except subprocess.CalledProcessError as e:
			print(f"❌ Code run failed for {defects4j_project} {defects4j_bug_num}: {e.stderr}")
			return None, f"Script execution failed: {e.stderr[:500]}", "fatal_error"

		if not os.path.exists(output_file_path):
			return None, "Output file not found - script may have crashed.", "fatal_error"

		try:
			with open(output_file_path, "r", encoding="utf-8") as f:
				result_data = json.load(f)
		except json.JSONDecodeError as e:
			return None, f"Failed to parse output JSON: {e}", "fatal_error"

		runtime_logs = result_data.get("buggy_code_runtime_logs", "")
		compilation_err_info = result_data.get("compilation_err_info", "")
		exception_info = result_data.get("exception_stack_trace", "")
		status = result_data.get("status", "unknown")

		execution_outcome, normalized_status = CodeRunner._build_execution_outcome(
			status, compilation_err_info, exception_info, result_data.get("message", "")
		)

		runtime_logs = CodeRunner._process_runtime_logs(runtime_logs, normalized_status)

		return runtime_logs, execution_outcome, normalized_status

	@staticmethod
	def run_source3_code(
		defects4j_bug_num,
		defects4j_project,
		code_snippet,
		method_path,
		method_signature,
		test_method,
	):
		input_data = {
			"defects4j_bug_num": defects4j_bug_num,
			"defects4j_project": defects4j_project,
			"buggy_code_with_logging_code": code_snippet,
			"method_path": method_path,
			"method_signature": method_signature,
			"test_method": test_method,
		}

		import hashlib

		method_hash = hashlib.md5(method_signature.encode()).hexdigest()[:8]

		in_out_dir = f"{source3_output_path}/{defects4j_project}_{defects4j_bug_num}_{method_hash}"
		os.makedirs(in_out_dir, exist_ok=True)

		input_file_path = os.path.join(in_out_dir, "input.json")
		output_file_path = os.path.join(in_out_dir, "output.json")

		Path(output_file_path).unlink(missing_ok=True)
		with open(input_file_path, "w", encoding="utf-8") as f:
			json.dump(input_data, f, indent=4)

		command = ["bash", script_path, "--out", in_out_dir, "--input", input_file_path]

		try:
			subprocess.run(
				command,
				check=True,
				capture_output=True,
				text=True,
				cwd=working_dir,
			)
			print(f"✅ Source3 code run successful for {defects4j_project} {defects4j_bug_num}")
		except subprocess.CalledProcessError as e:
			print(
				f"❌ Source3 code run failed for {defects4j_project} {defects4j_bug_num}: {e.stderr}"
			)
			return None, f"Script execution failed: {e.stderr[:500]}", "fatal_error"

		if not os.path.exists(output_file_path):
			return None, "Output file not found - script may have crashed.", "fatal_error"

		try:
			with open(output_file_path, "r", encoding="utf-8") as f:
				result_data = json.load(f)
		except json.JSONDecodeError as e:
			return None, f"Failed to parse output JSON: {e}", "fatal_error"

		runtime_logs = result_data.get("buggy_code_runtime_logs", "")
		compilation_err_info = result_data.get("compilation_err_info", "")
		exception_info = result_data.get("exception_stack_trace", "")
		status = result_data.get("status", "unknown")

		execution_outcome, normalized_status = CodeRunner._build_execution_outcome(
			status, compilation_err_info, exception_info, result_data.get("message", "")
		)

		runtime_logs = CodeRunner._process_runtime_logs(runtime_logs, normalized_status)
		return runtime_logs, execution_outcome, normalized_status

	@staticmethod
	def _build_execution_outcome(status, compilation_err_info, exception_info, message=""):
		outcome_parts = []

		if status == "compile_failed":
			normalized_status = "compile_failed"

			clean_error = CodeRunner._clean_compilation_error(compilation_err_info)
			outcome_parts.append(f"COMPILATION ERROR:\n{clean_error}")

		elif status == "success":
			normalized_status = "compile_success"
			outcome_parts.append("✓ Compilation successful.")

			if exception_info and exception_info.strip():
				normalized_status = "runtime_error"

				clean_exception = CodeRunner._clean_exception_trace(exception_info)
				outcome_parts.append(f"\nRUNTIME EXCEPTION:\n{clean_exception}")
			else:
				outcome_parts.append("✓ Execution completed without exceptions.")

		elif status == "test_timeout":
			normalized_status = "test_timeout"
			outcome_parts.append("⏱️  TIMEOUT: Execution exceeded time limit.")

		elif status == "fatal_error":
			normalized_status = "fatal_error"
			outcome_parts.append(f"❌ FATAL ERROR: {message}")

		else:
			normalized_status = "unknown"
			outcome_parts.append(f"⚠️  UNKNOWN STATUS: {status}")

		return "\n".join(outcome_parts), normalized_status

	@staticmethod
	def _clean_compilation_error(error_message):
		if not error_message or not error_message.strip():
			return "No compilation error details available."

		lines = error_message.split("\n")
		cleaned_lines = []

		for line in lines:
			if not line.strip() or "^" in line:
				continue

			line = re.sub(r"/.*?/([^/]+\.java):", r"\1:", line)

			if re.search(r":\d+:", line):
				cleaned_lines.append(f">>> {line}")
			else:
				cleaned_lines.append(line)

		cleaned_error = "\n".join(cleaned_lines)

		if len(cleaned_error) > CodeRunner.MAX_ERROR_MESSAGE_LENGTH:
			cleaned_error = (
				cleaned_error[: CodeRunner.MAX_ERROR_MESSAGE_LENGTH]
				+ "\n...[Error message truncated]"
			)

		return cleaned_error

	@staticmethod
	def _clean_exception_trace(exception_trace):
		if not exception_trace or not exception_trace.strip():
			return "No exception trace available."

		lines = exception_trace.split("\n")
		cleaned_lines = []
		stack_count = 0
		max_stack_lines = 15

		for line in lines:
			stripped = line.strip()

			if not stripped:
				continue

			if stripped.startswith(("Exception", "Error", "java.lang", "org.junit")):
				cleaned_lines.append(f">>> {line}")
				continue

			if stripped.startswith("at "):
				stack_count += 1
				if stack_count > max_stack_lines:
					cleaned_lines.append("    ... [remaining stack frames omitted]")
					break

				if any(skip in stripped for skip in ["junit", "sun.reflect", "java.lang.reflect"]):
					continue

				simplified = re.sub(r"at (.*?)\((.*?):\d+\)", r"at \1(\2)", line)
				cleaned_lines.append(simplified)
			else:
				cleaned_lines.append(line)

		return "\n".join(cleaned_lines)

	@staticmethod
	def _process_runtime_logs(runtime_logs, status):
		if not runtime_logs or not runtime_logs.strip():
			return "Runtime Logs:\nNo logs produced during execution."

		log_lines = runtime_logs.split("\n")
		total_lines = len(log_lines)

		repetitions = CodeRunner._detect_repetitive_logs(log_lines)

		if repetitions:
			runtime_logs = CodeRunner._collapse_repetitive_logs(log_lines, repetitions)
			log_lines = runtime_logs.split("\n")

		if len(runtime_logs) > CodeRunner.MAX_RUNTIME_LOGS_LENGTH:
			keep_head = CodeRunner.MAX_RUNTIME_LOGS_LENGTH // 2
			keep_tail = CodeRunner.MAX_RUNTIME_LOGS_LENGTH // 4

			omitted_chars = len(runtime_logs) - keep_head - keep_tail
			runtime_logs = (
				runtime_logs[:keep_head]
				+ f"\n\n... [{omitted_chars} characters omitted] ...\n\n"
				+ runtime_logs[-keep_tail:]
			)

		stats = f"Runtime Logs (Total: {total_lines} lines, Length: {len(runtime_logs)} chars):\n"

		if repetitions:
			stats += f"⚠️  Detected {len(repetitions)} repetitive log patterns\n"

		stats += "-" * 80 + "\n"

		return stats + runtime_logs

	@staticmethod
	def _detect_repetitive_logs(log_lines):
		from collections import Counter

		non_empty_lines = [line for line in log_lines if line.strip()]

		if len(non_empty_lines) < 20:
			return []

		line_counts = Counter(non_empty_lines)

		repetitions = [
			(line, count, log_lines.index(line))
			for line, count in line_counts.items()
			if count >= 10
		]

		return sorted(repetitions, key=lambda x: x[1], reverse=True)

	@staticmethod
	def _collapse_repetitive_logs(log_lines, repetitions):
		if not repetitions:
			return "\n".join(log_lines)

		from itertools import groupby

		repeated_lines = {line for line, _, _ in repetitions}
		result_lines = []
		for line, group in groupby(log_lines):
			count = sum(1 for _ in group)
			if line in repeated_lines and count > 5:
				result_lines.extend(
					[line, f"... [Previous line repeated {count - 2} additional times] ...", line]
				)
			else:
				result_lines.extend([line] * count)
		return "\n".join(result_lines)
