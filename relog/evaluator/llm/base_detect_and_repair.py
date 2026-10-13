from typing import Optional

import dspy

from ...base_dspy import BaseDspy


class BaseDetect(dspy.Signature):
	input_code_snippet: str = dspy.InputField(
		desc=(
			"The code snippet to be analyzed for potential bugs. "
			"Carefully inspect control flow, environment assumptions "
			"(OS, filesystem, native libs, DNS, etc.), resource management, "
			"exception handling, and multi-run or cross-platform behavior."
		)
	)

	has_bug: bool = dspy.OutputField(
		desc=(
			"Boolean flag indicating whether there is at least one likely real "
			"bug in the code snippet. "
			"Set to True if static reasoning reveals a defect, even if a "
			"single observed execution might succeed. "
			"Do NOT set to False solely because a test or log appears successful."
		)
	)

	bugs: str = dspy.OutputField(
		desc=(
			"A concise but detailed description of the bugs found, if any. "
			"If has_bug is True, list the main bug(s) with:\n"
			"- Bug Type (e.g., platform-dependent path bug, missing exception, "
			"  resource cleanup issue, flaky statistical test, etc.)\n"
			"- Location (class/method/line or code fragment)\n"
			"- Root cause (what assumption or behavior is wrong)\n"
			"- Impact (what can go wrong and under which environment/run)\n"
			"If has_bug is False, return an empty string."
		)
	)


class BaseDetectWithLog(BaseDetect):
	log: str = dspy.InputField(
		desc=(
			"Runtime log information related to one execution of the code snippet. "
			"Use this log to:\n"
			"- Identify symptoms (exceptions, timeouts, incorrect outputs) when present.\n"
			"- Detect what the test actually checks (e.g., only exit code vs. full behavior).\n"
			"- Notice missing signals (no OS info, no failure path, no cleanup) that "
			"suggest hidden bugs.\n"
			"Never assume the code is correct just because the log shows success. "
			"If static analysis suggests a defect that the log does not cover "
			"(e.g., Windows-only failure, multi-run flakiness), still mark has_bug=True."
		)
	)


class BaseRepair(dspy.Signature):
	input_code_snippet: str = dspy.InputField(
		desc=(
			"The original code snippet containing the bug(s) to be fixed. "
			"You should modify this code to eliminate the described defect(s) "
			"while preserving its intended behavior."
		)
	)

	bug_description: str = dspy.InputField(
		desc=(
			"Detailed description of the bug(s) present in the code snippet, "
			"including bug type, location, root cause, and the intended behavior. "
			"Use this description to target the true underlying problem rather "
			"than only adjusting tests or logging."
		)
	)

	repaired_code_snippet: str = dspy.OutputField(
		desc=(
			"The corrected code snippet that fixes all identified bug(s) while "
			"maintaining the original functionality and code style as much as "
			"possible. The patch should address the root cause (e.g., add an "
			"OS guard, catch the missing exception type, clean up temporary "
			"resources, or make statistical tests robust), not just mask symptoms."
		)
	)


class BaseRepairWithLog(BaseRepair):
	log: str = dspy.InputField(
		desc=(
			"Runtime log information related to the execution of the buggy code. "
			"Use this log to:\n"
			"- See how the bug manifests (exceptions, wrong outputs, timeouts) "
			"when failures are present.\n"
			"- Understand what the current tests actually exercise and what they "
			"miss (e.g., no Windows run, no second execution, no DNS failure).\n"
			"Your repaired_code_snippet must fix the root cause indicated by the "
			"bug_description and code, even if the provided log shows a successful run."
		)
	)


class BaseDetectorAndRepairer(BaseDspy):
	def _post_init(self, use_log: bool = False, **kwargs):
		self.use_log = use_log
		self.detect_signature = BaseDetectWithLog if use_log else BaseDetect
		self.repair_signature = BaseRepairWithLog if use_log else BaseRepair

	def detect(
		self, code_snippet: str, log: Optional[str] = None, max_tries: int = 3
	) -> Optional[dict]:
		if self.use_log and log is None:
			raise ValueError("log parameter is required when use_log=True")
		with self.use_model():
			detector = dspy.ChainOfThought(self.detect_signature)

			for attempt in range(max_tries):
				try:
					kwargs = {"input_code_snippet": code_snippet}
					if self.use_log:
						kwargs["log"] = log

					result = detector(**kwargs)
					return {"has_bug": result.has_bug, "bugs": result.bugs}
				except Exception as e:
					print(f"Detection attempt {attempt + 1}/{max_tries} failed: {e}")
					if attempt == max_tries - 1:
						raise RuntimeError(f"Detection failed after {max_tries} attempts") from e

			print(f"All {max_tries} detection attempts failed.")
			return None

	def repair(
		self, code_snippet: str, bug_description: str, log: Optional[str] = None, max_tries: int = 3
	) -> Optional[str]:
		if self.use_log and log is None:
			raise ValueError("log parameter is required when use_log=True")
		with self.use_model():
			repairer = dspy.ChainOfThought(self.repair_signature)

			for attempt in range(max_tries):
				try:
					kwargs = {
						"input_code_snippet": code_snippet,
						"bug_description": bug_description,
					}
					if self.use_log:
						kwargs["log"] = log

					result = repairer(**kwargs)
					return result.repaired_code_snippet
				except Exception as e:
					print(f"Repair attempt {attempt + 1}/{max_tries} failed: {e}")
					if attempt == max_tries - 1:
						raise RuntimeError(f"Repair failed after {max_tries} attempts") from e

			print(f"All {max_tries} repair attempts failed.")
			return None

	def detect_and_repair(
		self, code_snippet: str, log: Optional[str] = None, max_tries: int = 3
	) -> Optional[dict]:
		detection_result = self.detect(code_snippet, log, max_tries)
		if detection_result is None:
			return None

		if not detection_result["has_bug"]:
			return {
				"has_bug": False,
				"original_code": code_snippet,
				"repaired_code": code_snippet,
				"bugs": "",
			}

		repaired_code = self.repair(code_snippet, detection_result["bugs"], log, max_tries)

		if repaired_code is None:
			return None

		return {
			"has_bug": True,
			"original_code": code_snippet,
			"repaired_code": repaired_code,
			"bugs": detection_result["bugs"],
		}


class BaseDetectorAndRepairerWithLog(BaseDetectorAndRepairer):
	def __init__(self, model_name: str, cache: bool = False, temperature: float = 0.7):
		super().__init__(model_name, cache=cache, temperature=temperature, use_log=True)
