import re
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Optional

from tqdm import tqdm

from .llm.base_detect_and_repair import BaseDetectorAndRepairer
from .llm.verify_bug_detect import BugDetectionVerifier
from .llm.verify_repair_code import CodeRepairVerifier


def calculate_statistics(
	results: list[dict],
	compilation_failed_count: int,
	total_count: int,
	result_key: str = "with_log",
	generation_failed_count: int = 0,
) -> dict:
	processed_samples = len(results)

	stats = {
		"total_samples": total_count,
		"compilation_failed": compilation_failed_count,
		"generation_failed": generation_failed_count,
		"processed_samples": processed_samples,
		"detection": {
			"total": processed_samples,
			"success": 0,
			"failed": 0,
			"has_bug_detected": 0,
			"no_bug_detected": 0,
		},
		"bug_verification": {
			"total": 0,
			"correct": 0,
			"incorrect": 0,
		},
		"repair": {
			"total_attempted": 0,
			"success": 0,
			"failed": 0,
		},
		"repair_verification": {
			"total": 0,
			"correct": 0,
			"incorrect": 0,
		},
	}

	detection_confidences = []
	repair_confidences = []

	for result_item in results:
		result = result_item.get("results", {}).get(result_key, {})

		if not result:
			stats["detection"]["failed"] += 1
			continue

		detection = result.get("detection")
		if detection is None:
			stats["detection"]["failed"] += 1
		else:
			stats["detection"]["success"] += 1
			if detection.get("has_bug"):
				stats["detection"]["has_bug_detected"] += 1
			else:
				stats["detection"]["no_bug_detected"] += 1

		bug_verification = result.get("bug_verification")
		if bug_verification is not None:
			stats["bug_verification"]["total"] += 1
			if bug_verification.get("is_correct"):
				stats["bug_verification"]["correct"] += 1
			else:
				stats["bug_verification"]["incorrect"] += 1

			if "confidence" in bug_verification:
				detection_confidences.append(bug_verification["confidence"])

		repair = result.get("repair")
		if repair is not None and repair.get("attempted"):
			stats["repair"]["total_attempted"] += 1
			if repair.get("repaired_code") is not None:
				stats["repair"]["success"] += 1
			else:
				stats["repair"]["failed"] += 1

		repair_verification = result.get("repair_verification")
		if repair_verification is not None:
			stats["repair_verification"]["total"] += 1
			if repair_verification.get("is_correct"):
				stats["repair_verification"]["correct"] += 1
			else:
				stats["repair_verification"]["incorrect"] += 1

			if "confidence" in repair_verification:
				repair_confidences.append(repair_verification["confidence"])

	stats["rates"] = {}

	if stats["detection"]["success"] > 0:
		stats["rates"]["bug_detection_rate"] = round(
			stats["detection"]["has_bug_detected"] / stats["detection"]["success"] * 100, 2
		)

	if stats["bug_verification"]["total"] > 0:
		stats["rates"]["bug_verification_accuracy"] = round(
			stats["bug_verification"]["correct"] / stats["bug_verification"]["total"] * 100, 2
		)

	if detection_confidences:
		stats["rates"]["avg_detection_confidence"] = round(
			sum(detection_confidences) / len(detection_confidences), 3
		)

	if stats["repair_verification"]["total"] > 0:
		stats["rates"]["repair_verification_accuracy"] = round(
			stats["repair_verification"]["correct"] / stats["repair_verification"]["total"] * 100, 2
		)

	if repair_confidences:
		stats["rates"]["avg_repair_confidence"] = round(
			sum(repair_confidences) / len(repair_confidences), 3
		)

	return stats


def calculate_logging_code_number(code_lists: list[str]) -> list[int]:
	log_pattern = re.compile(r"System\.out\.println\(.*?\);")
	log_counts = []
	for code in code_lists:
		logs = log_pattern.findall(code)
		log_counts.append(len(logs))
	avg_logs = sum(log_counts) / len(log_counts) if log_counts else 0
	return log_counts, avg_logs


class BaseEvaluator:
	def __init__(
		self,
		use_log,
		detect_and_repair_model_config,
		bug_verifier_model_config,
		repair_code_verifier_model_config,
	):
		self.detector_and_repairer = BaseDetectorAndRepairer(
			use_log=use_log, **detect_and_repair_model_config
		)
		self.bug_detection_verifier = BugDetectionVerifier(**bug_verifier_model_config)
		self.code_repair_verifier = CodeRepairVerifier(**repair_code_verifier_model_config)

	def evaluate_item(
		self,
		log,
		code_to_be_detected,
		code_to_be_repaired,
		ground_truth_bug_desc,
		ground_truth_repair_code,
	) -> dict:
		detect_result = self.detector_and_repairer.detect(code_snippet=code_to_be_detected, log=log)

		if detect_result is None:
			return {
				"detection": None,
				"bug_verification": None,
				"repair": None,
				"repair_verification": None,
				"error": "Detection failed after all retries",
			}

		bug_verification_result = self.bug_detection_verifier.verify(
			detected_bugs=detect_result["bugs"],
			ground_truth_bug=ground_truth_bug_desc,
			buggy_code=code_to_be_detected,
		)

		repair_result = None
		repair_verification = None

		if detect_result["has_bug"]:
			repair_result = self.detector_and_repairer.repair(
				code_snippet=code_to_be_repaired,
				bug_description=detect_result["bugs"],
				log=log,
			)

			if repair_result is not None:
				repair_verification = self.code_repair_verifier.verify(
					buggy_code=code_to_be_repaired,
					bug_description=ground_truth_bug_desc,
					ground_truth_repair_code=ground_truth_repair_code,
					repaired_code=repair_result,
				)

		return {
			"detection": {
				"has_bug": detect_result["has_bug"],
				"detected_bugs": detect_result["bugs"],
			},
			"bug_verification": bug_verification_result,
			"repair": {
				"repaired_code": repair_result,
				"attempted": detect_result["has_bug"],
			},
			"repair_verification": repair_verification,
		}

	def evaluate_batch(self, items: list[dict], max_workers: Optional[int] = None) -> list[dict]:
		results = []

		with ProcessPoolExecutor(max_workers=max_workers) as executor:
			future_to_item = {
				executor.submit(
					self.evaluate_item,
					item["log"],
					item["code_to_be_detected"],
					item["code_to_be_repaired"],
					item["ground_truth_bug_desc"],
					item["ground_truth_repair_code"],
				): item
				for item in items
			}

			for future in tqdm(
				as_completed(future_to_item), total=len(items), desc="Evaluating items"
			):
				item = future_to_item[future]
				try:
					result = future.result()
				except Exception as e:
					result = {
						"detection": None,
						"bug_verification": None,
						"repair": None,
						"repair_verification": None,
						"error": str(e),
					}
				results.append(
					{
						"metadata": {
							"jira_id": item["jira_id"],
							"commit_hash": item["commit_hash"],
						},
						"ground_truth": {
							"bug_description": item["ground_truth_bug_desc"],
							"fixed_code": item["ground_truth_repair_code"],
						},
						"results": {"with_log": result},
					}
				)

		return results
