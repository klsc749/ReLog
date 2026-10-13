import argparse
import json
from pathlib import Path

from .base_evaluator import BaseEvaluator, calculate_logging_code_number, calculate_statistics
from .utils import EvaluationUtils


def _prepare_items(to_be_evaluated_data, ground_truth_dict):
    compilation_failed_count = 0
    generation_failed_count = 0
    to_be_evaluated_items = []
    code_list = []

    for item in to_be_evaluated_data:
        final_data = item.get("final_data", {})
        refined_code = final_data.get("instrumented_code")
        runtime_logs = final_data.get("runtime_logs", "")
        run_status = final_data.get("normalized_status")
        is_compilation_failed = run_status == "compile_failed"

        if is_compilation_failed:
            compilation_failed_count += 1
            continue
        if "error" in final_data or not refined_code or run_status not in {"compile_success", "runtime_error", "test_timeout"}:
            generation_failed_count += 1
            continue

        key = EvaluationUtils.get_item_key(item["metadata"])
        ground_truth = ground_truth_dict[key]
        batch_item = EvaluationUtils.construct_batch_items_from_feedback_refine_data_item(
            {
                "meta_data": item["metadata"],
                "original_code": ground_truth["buggy_code"],
            },
            refined_code,
            runtime_logs,
            ground_truth["bug_description"],
            ground_truth["fixed_code"],
        )

        code_list.append(refined_code)
        to_be_evaluated_items.append(batch_item)

    return to_be_evaluated_items, code_list, compilation_failed_count, generation_failed_count


def run_evaluation(
    input_path,
    ground_truth_path,
    result_path,
    statistics_path,
    model_name,
    verifier_model_name,
    cache,
    temperature,
    verifier_temperature,
    method_name,
    critic_model,
    actor_model,
    max_workers,
):
    with open(input_path, "r", encoding="utf-8") as f:
        to_be_evaluated_data = json.load(f)

    ground_truth_dict = EvaluationUtils.load_ground_truth(ground_truth_path)
    total_count = len(to_be_evaluated_data)

    detect_and_repair_model_config = EvaluationUtils.construct_model_config(
        model_name=model_name,
        temperature=temperature,
        cache=cache,
    )
    verifier_model_config = EvaluationUtils.construct_model_config(
        model_name=verifier_model_name,
        temperature=verifier_temperature,
        cache=cache,
    )

    evaluator = BaseEvaluator(
        use_log=True,
        detect_and_repair_model_config=detect_and_repair_model_config,
        bug_verifier_model_config=verifier_model_config,
        repair_code_verifier_model_config=verifier_model_config,
    )

    to_be_evaluated_items, code_list, compilation_failed_count, generation_failed_count = _prepare_items(
        to_be_evaluated_data, ground_truth_dict
    )

    results = evaluator.evaluate_batch(items=to_be_evaluated_items, max_workers=max_workers)

    stats = calculate_statistics(
        results=results,
        compilation_failed_count=compilation_failed_count,
        total_count=total_count,
        generation_failed_count=generation_failed_count,
    )
    _, avg_log_number = calculate_logging_code_number(code_list)
    stats["avg_logging_code_number"] = avg_log_number
    stats["method_name"] = method_name
    stats["model_name"] = model_name
    stats["critic_model"] = critic_model
    stats["actor_model"] = actor_model

    Path(result_path).parent.mkdir(parents=True, exist_ok=True)
    Path(statistics_path).parent.mkdir(parents=True, exist_ok=True)

    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=4)

    with open(statistics_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=4)


def _build_parser():
    parser = argparse.ArgumentParser(description="Evaluate direct debugging results")
    parser.add_argument("--input-path", required=True)
    parser.add_argument("--ground-truth-path", required=True)
    parser.add_argument("--result-path", default=None)
    parser.add_argument("--statistics-path", default=None)
    parser.add_argument("--model-name", default="deepseek-v3")
    parser.add_argument("--verifier-model-name", default="deepseek-v3")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--verifier-temperature", type=float, default=0.0)
    parser.add_argument("--cache", action="store_true", default=True)
    parser.add_argument("--no-cache", action="store_false", dest="cache")
    parser.add_argument("--method-name", default="direct_debugging_eval")
    parser.add_argument("--critic-model", default="deepseek-v3")
    parser.add_argument("--actor-model", default="deepseek-v3")
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
        model_name=args.model_name,
        verifier_model_name=args.verifier_model_name,
        cache=args.cache,
        temperature=args.temperature,
        verifier_temperature=args.verifier_temperature,
        method_name=args.method_name,
        critic_model=args.critic_model,
        actor_model=args.actor_model,
        max_workers=args.max_workers,
    )
