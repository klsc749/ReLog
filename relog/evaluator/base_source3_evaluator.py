
import re
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import List

from tqdm import tqdm

from .llm.base_black_box_detect import IndirectBugDetector
from .llm.verify_bug_detect import BugDetectionVerifier


def calculate_logging_code_number(code_lists: list[str]) -> list[int]:
	log_pattern = re.compile(r"System\.out\.println\(.*?\);")
	log_counts = []
	for code in code_lists:
		logs = log_pattern.findall(code)
		log_counts.append(len(logs))
	avg_logs = sum(log_counts) / len(log_counts) if log_counts else 0
	return log_counts, avg_logs


def calculate_statistics(
	results: List[dict], total_caller_count: int, compile_failed_count: int
) -> dict:
	total_items = len(results)
	successful_detections = 0
	failed_detections = 0
	timeouts = 0
	bugs_detected = 0
	bugs_not_detected = 0
	correct_detect_count = 0
	incorrect_detect_count = 0
	verification_failed_count = 0

	for result in results:
		detection = result.get("detection", {})
		status = detection.get("status")
		has_bug = detection.get("has_bug")
		bug_verification = result.get("bug_verification")

		if status == "success":
			successful_detections += 1

			if has_bug:
				bugs_detected += 1

				if bug_verification is None:
					verification_failed_count += 1
				elif bug_verification.get("is_correct"):
					correct_detect_count += 1
				else:
					incorrect_detect_count += 1
			else:
				bugs_not_detected += 1

		elif status == "timeout":
			timeouts += 1
		elif status == "failed":
			failed_detections += 1

	detection_rate = bugs_detected / total_items if total_items > 0 else 0.0
	verified_count = correct_detect_count + incorrect_detect_count
	accuracy = correct_detect_count / verified_count if verified_count > 0 else 0.0
	success_rate = successful_detections / total_items if total_items > 0 else 0.0

	statistics = {
		"total_items": total_items,
		"successful_detections": successful_detections,
		"failed_detections": failed_detections,
		"timeouts": timeouts,
		"bugs_detected": bugs_detected,
		"bugs_not_detected": bugs_not_detected,
		"correct_detect_count": correct_detect_count,
		"incorrect_detect_count": incorrect_detect_count,
		"verification_failed_count": verification_failed_count,
		"total_caller_count": total_caller_count,
		"compile_failed_count": compile_failed_count,
		"detection_rate": round(detection_rate, 4),
		"accuracy": round(accuracy, 4),
		"success_rate": round(success_rate, 4),
	}

	return statistics


class BaseSource3Evaluator:
	def __init__(self, detect_model_config, verify_model_config):
		self.detector = IndirectBugDetector(**detect_model_config)
		self.bug_verifier = BugDetectionVerifier(**verify_model_config)

	def evaluate_item(
		self,
		blackbox_method_signature,
		caller_code_snippet_2_log_map,
		ground_truth_bug_desc,
		buggy_code,
	) -> dict:
		detection_result = self.detector.detect_with_general_logs(
			caller_code_snippet_2_log_map=caller_code_snippet_2_log_map,
			blackbox_method_signature=blackbox_method_signature,
		)

		if detection_result is None:
			return {
				"detection": {
					"status": "failed",
					"has_bug": None,
					"detected_bugs": None,
				},
				"bug_verification": None,
			}

		has_bug = detection_result["has_bug"]

		if has_bug:
			verification_result = self.bug_verifier.verify(
				detection_result["bugs"], buggy_code, ground_truth_bug_desc
			)
		else:
			verification_result = {
				"is_correct": False,
				"confidence": 1.0,
				"explanation": "No bug detected.",
			}

		return {
			"detection": {
				"status": "success",
				"has_bug": has_bug,
				"detected_bugs": detection_result["bugs"],
			},
			"bug_verification": verification_result,
		}

	def evaluate_batch(self, items: List[dict], max_workers: int = 4) -> List[dict]:
		results_dict = {}
		completed = 0

		with ProcessPoolExecutor(max_workers=max_workers) as executor:
			future_to_index = {
				executor.submit(
					self.evaluate_item,
					item["blackbox_method_signature"],
					item["caller_code_snippet_2_log_map"],
					item["ground_truth_bug_desc"],
					item["buggy_code"],
				): i
				for i, item in enumerate(items)
			}

			with tqdm(total=len(items), desc="Evaluating items") as pbar:
				for future in as_completed(future_to_index):
					index = future_to_index[future]
					item = items[index]

					try:
						result = future.result()
						status = "✅"
					except Exception as e:
						print(f"\n❌ Failed: {item['metadata']}: {e}")
						result = {
							"detection": {
								"status": "failed",
								"has_bug": None,
								"detected_bugs": None,
							},
							"bug_verification": None,
							"error": str(e),
							"error_type": type(e).__name__,
						}
						status = "❌"
					result["metadata"] = item["metadata"]
					results_dict[index] = result
					completed += 1

					pbar.set_postfix_str(f"{status} {index}")
					pbar.update(1)

		return [results_dict[i] for i in range(len(items))]
