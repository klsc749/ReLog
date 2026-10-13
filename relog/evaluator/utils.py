import json
from pathlib import Path


class EvaluationUtils:
    @staticmethod
    def get_item_key(item):
        jira_id = item["jira_id"]
        commit_hash = item["commit_hash"]
        return f"{jira_id}__{commit_hash}"

    @staticmethod
    def load_ground_truth(file_path: str) -> dict:
        with open(file_path, "r", encoding="utf-8") as f:
            ground_truth_data = json.load(f)

        ground_truth_dict = {}
        for item in ground_truth_data:
            key = EvaluationUtils.get_item_key(item)
            ground_truth_dict[key] = item

        return ground_truth_dict

    @staticmethod
    def construct_model_config(model_name, temperature, cache: bool):
        return {
            "model_name": model_name,
            "temperature": temperature,
            "cache": cache,
        }

    @staticmethod
    def construct_batch_items_from_source2_data_item(item, ground_truth_bug_desc, ground_truth_repair_code) -> dict:
        return {
            "jira_id": item["jira_id"],
            "commit_hash": item["commit_hash"],
            "log": item["buggy_code_runtime_logs"],
            "code_to_be_detected": item["buggy_code_with_logging_code"],
            "code_to_be_repaired": item["buggy_code"],
            "ground_truth_bug_desc": ground_truth_bug_desc,
            "ground_truth_repair_code": ground_truth_repair_code,
        }

    @staticmethod
    def get_direct_debugging_result_and_statistic_save_path(
        debugging_model_name,
        method_name,
        use_log=True,
        base_dir="results",
    ):
        base_path = Path(base_dir)
        safe_model_name = debugging_model_name.replace("/", "_").replace(":", "_")

        if not use_log:
            result_path = base_path / "without_log_results.json"
            stats_path = base_path / "without_log_statistics.json"
        else:
            model_dir = base_path / safe_model_name
            result_path = model_dir / f"{method_name}_results.json"
            stats_path = model_dir / f"{method_name}_statistics.json"

        return str(result_path), str(stats_path)

    @staticmethod
    def construct_batch_items_from_feedback_refine_data_item(
        item,
        final_code,
        log,
        ground_truth_bug_desc,
        ground_truth_repair_code,
        key="meta_data",
    ) -> dict:
        return {
            "jira_id": item[key]["jira_id"],
            "commit_hash": item[key]["commit_hash"],
            "log": log,
            "code_to_be_detected": final_code,
            "code_to_be_repaired": item["original_code"],
            "ground_truth_bug_desc": ground_truth_bug_desc,
            "ground_truth_repair_code": ground_truth_repair_code,
        }
