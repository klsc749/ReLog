import argparse
import json
from pathlib import Path

from .base_source3_evaluator import (
    BaseSource3Evaluator,
    calculate_logging_code_number,
    calculate_statistics,
)


def get_ground_truth_mapping(ground_truth_path):
    with open(ground_truth_path, "r", encoding="utf-8") as f:
        ground_truth_data = json.load(f)

    mapping = {}
    for item in ground_truth_data:
        mapping[f"{item['jira_id']}_{item['commit_hash']}"] = item["buggy_method"]
    return mapping


def _prepare_items(feedback_data, ground_truth_mapping):
    to_be_evaluated_items = []
    compile_failed_count = 0
    total_caller_count = 0
    generation_failed_count = 0
    caller_code = []

    for item in feedback_data:
        meta = item["metadata"]
        jira_id = meta["jira_id"]
        commit_hash = meta["commit_hash"]
        gt = ground_truth_mapping[f"{jira_id}_{commit_hash}"]

        caller_code_snippet_2_log_map = []
        for caller_method in item.get("caller_methods_results", []):
            final_data = caller_method.get("result", {}).get("final_data", {})
            code_with_logging = final_data.get("instrumented_code")
            runtime_logs = final_data.get("runtime_logs", "")

            total_caller_count += 1
            if final_data.get("normalized_status") == "compile_failed":
                compile_failed_count += 1
                continue
            if "error" in final_data or not code_with_logging or final_data.get("normalized_status") not in {"compile_success", "runtime_error", "test_timeout"}:
                generation_failed_count += 1
                continue
            caller_code.append(code_with_logging)

            caller_code_snippet_2_log_map.append(
                {
                    "caller_code_snippet": code_with_logging,
                    "runtime_log": runtime_logs,
                }
            )

        to_be_evaluated_items.append(
            {
                "metadata": {
                    "defects4j_bug_num": meta["defect4j_bug_num"],
                    "defects4j_project": meta["defect4j_project"],
                    "jira_id": jira_id,
                    "commit_hash": commit_hash,
                },
                "blackbox_method_signature": gt["signature"],
                "caller_code_snippet_2_log_map": caller_code_snippet_2_log_map,
                "ground_truth_bug_desc": gt["bug_description"],
                "buggy_code": gt["code"],
            }
        )

    return to_be_evaluated_items, caller_code, total_caller_count, compile_failed_count, generation_failed_count


def run_evaluation(
    input_path,
    ground_truth_path,
    result_path,
    statistics_path,
    detect_model_name,
    verify_model_name,
    temperature,
    verify_temperature,
    cache,
    max_workers,
):
    ground_truth_mapping = get_ground_truth_mapping(ground_truth_path)

    detect_model_config = {
        "model_name": detect_model_name,
        "temperature": temperature,
        "cache": cache,
    }
    verify_model_config = {
        "model_name": verify_model_name,
        "temperature": verify_temperature,
        "cache": cache,
    }

    evaluator = BaseSource3Evaluator(
        detect_model_config=detect_model_config,
        verify_model_config=verify_model_config,
    )

    with open(input_path, "r", encoding="utf-8") as f:
        feedback_data = json.load(f)

    to_be_evaluated_items, caller_code, total_caller_count, compile_failed_count, generation_failed_count = _prepare_items(
        feedback_data, ground_truth_mapping
    )

    results = evaluator.evaluate_batch(to_be_evaluated_items, max_workers=max_workers)

    statistics = calculate_statistics(results, total_caller_count, compile_failed_count)
    statistics["generation_failed_count"] = generation_failed_count
    log_count, avg_log_count = calculate_logging_code_number(caller_code)
    statistics["logging_code_count"] = log_count
    statistics["avg_logging_code_per_caller"] = avg_log_count

    Path(result_path).parent.mkdir(parents=True, exist_ok=True)
    Path(statistics_path).parent.mkdir(parents=True, exist_ok=True)

    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=4)

    with open(statistics_path, "w", encoding="utf-8") as f:
        json.dump(statistics, f, indent=4)


def _build_parser():
    parser = argparse.ArgumentParser(description="Evaluate indirect debugging results")
    parser.add_argument("--input-path", required=True)
    parser.add_argument("--ground-truth-path", required=True)
    parser.add_argument("--result-path", default=None)
    parser.add_argument("--statistics-path", default=None)
    parser.add_argument("--detect-model-name", default="deepseek-v3")
    parser.add_argument("--verify-model-name", default="deepseek-v3")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--verify-temperature", type=float, default=0.0)
    parser.add_argument("--cache", action="store_true", default=True)
    parser.add_argument("--no-cache", action="store_false", dest="cache")
    parser.add_argument("--max-workers", type=int, default=32)
    return parser


if __name__ == "__main__":
    args = _build_parser().parse_args()
    result_path = args.result_path or str(Path(args.input_path).with_name(Path(args.input_path).stem + "_evaluation.json"))
    statistics_path = args.statistics_path or str(Path(args.input_path).with_name(Path(args.input_path).stem + "_statistics.json"))

    run_evaluation(
        input_path=args.input_path,
        ground_truth_path=args.ground_truth_path,
        result_path=result_path,
        statistics_path=statistics_path,
        detect_model_name=args.detect_model_name,
        verify_model_name=args.verify_model_name,
        temperature=args.temperature,
        verify_temperature=args.verify_temperature,
        cache=args.cache,
        max_workers=args.max_workers,
    )
