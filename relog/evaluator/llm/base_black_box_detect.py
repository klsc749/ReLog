from typing import Dict, List, Optional

import dspy

from ...base_dspy import BaseDspy

CallerCodeLogMap = List[Dict[str, str]]


class IndirectDetectBase(dspy.Signature):
	blackbox_method_signature: str = dspy.InputField(
		desc=(
			"Signature of the black-box method under debugging (implementation unavailable). "
			"Use it to identify the call boundary in the caller code."
		)
	)

	has_bug: bool = dspy.OutputField(
		desc=(
			"Boolean flag indicating whether the evidence suggests a likely real defect or "
			"contract violation in the black-box method.\n"
			"Set to True if caller evidence indicates incorrect behavior under some inputs/state.\n"
			"Do NOT set to False solely because the available logs are incomplete or inconclusive."
		)
	)


class IndirectDetectGeneral(IndirectDetectBase):
	caller_code_snippet_2_log_map: CallerCodeLogMap = dspy.InputField(
		desc=(
			"A list of dictionaries, each containing:\n"
			"- 'caller_code_snippet': The caller method source code\n"
			"- 'runtime_log': logs generated in the caller context\n\n"
			"Use the logs as runtime evidence to explain what triggers the failure and what incorrect behavior is observed.\n\n"
			"Example format:\n"
			"[\n"
			'  {"caller_code_snippet": "public void method1() {...}", "runtime_log": "LOG: input=null\\nException..."},\n'
			'  {"caller_code_snippet": "public void method2() {...}", "runtime_log": "LOG: result=null\\n..."}\n'
			"]"
		)
	)

	bugs: str = dspy.OutputField(
		desc=(
			"Provide a fault explanation for the black-box method.\n"
			"If has_bug is True, describe:\n"
			"- Bug type (e.g., incorrect boundary handling, contract violation, unexpected exception)\n"
			"- Trigger (inputs/state/call context that correlate with failure)\n"
			"- Evidence (key observations from caller code and the provided logs)\n"
			"- Impact (what goes wrong and under what conditions)\n"
			"Do NOT reference black-box internal implementation details or line numbers.\n"
			"If has_bug is False, return an empty string."
		)
	)


LOG_TYPES = ["simple", "narrative", "contract", "diagnostic"]


class IndirectBugDetector(BaseDspy):
	def _post_init(self, **kwargs):
		super()._post_init(**kwargs)

	def _detect_with_signature(
		self,
		signature_class: type,
		caller_code_snippet_2_log_map: CallerCodeLogMap,
		blackbox_method_signature: str,
		max_tries: int = 3,
	) -> Optional[dict]:
		if not caller_code_snippet_2_log_map:
			print("Warning: Empty caller_code_snippet_2_log_map provided")
			return None

		with self.use_model():
			detector = dspy.ChainOfThought(signature_class)

			for attempt in range(max_tries):
				try:
					result = detector(
						caller_code_snippet_2_log_map=caller_code_snippet_2_log_map,
						blackbox_method_signature=blackbox_method_signature,
					)
					return {
						"has_bug": result.has_bug,
						"bugs": result.bugs,
						"num_callers": len(caller_code_snippet_2_log_map),
					}
				except Exception as e:
					print(f"Detection attempt {attempt + 1}/{max_tries} failed: {e}")
					if attempt == max_tries - 1:
						raise RuntimeError(f"Indirect detection failed after {max_tries} attempts") from e

			return None

	def detect_with_general_logs(
		self,
		caller_code_snippet_2_log_map: CallerCodeLogMap,
		blackbox_method_signature: str,
		max_tries: int = 3,
	) -> Optional[dict]:
		return self._detect_with_signature(
			IndirectDetectGeneral,
			caller_code_snippet_2_log_map,
			blackbox_method_signature,
			max_tries,
		)

	def detect(
		self,
		caller_code_logs: CallerCodeLogMap,
		blackbox_method_signature: str,
		log_type: str = "general",
		max_tries: int = 3,
	) -> Optional[dict]:
		detect_method = self.detect_with_general_logs
		return detect_method(caller_code_logs, blackbox_method_signature, max_tries)

	def batch_detect(
		self,
		detection_type: str,
		caller_code_snippet_2_log_maps: List[CallerCodeLogMap],
		blackbox_signatures: List[str],
		max_tries: int = 3,
	) -> List[Optional[dict]]:
		if len(caller_code_snippet_2_log_maps) != len(blackbox_signatures):
			raise ValueError("Lists must have the same length")

		detect_method = self.detect_with_general_logs

		results = []
		for caller_log_map, signature in zip(
			caller_code_snippet_2_log_maps, blackbox_signatures, strict=False
		):
			result = detect_method(caller_log_map, signature, max_tries)
			results.append(result)

		return results
