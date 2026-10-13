import argparse
import concurrent.futures
import json
import os
from pathlib import Path

from tqdm import tqdm

from .code_runner import CodeRunner
from .roles import (
	code_compilation_fixer,
	initial_logger,
	log_sufficient_evaluator,
	logging_code_refiner,
)
from .utils import LogInstructionApplier, save_checkpoint


def add_logging_code_to_item(
	jira_id,
	commit_hash,
	defect4j_bug_num,
	defect4j_project,
	code_snippet,
	model_name="gpt-5-mini",
	compilation_fix_model_name="deepseek-v3",
	temperature=0,
	cache=True,
	max_compile_fix_attempts=5,
	max_refine_iterations=10,
	code_runner_config=None,
):
	model_config = {
		"model_name": model_name,
		"cache": cache,
		"temperature": temperature,
	}

	compilation_fix_model_config = {
		"model_name": compilation_fix_model_name,
		"cache": cache,
		"temperature": temperature,
	}

	if code_runner_config:
		CodeRunner.configure_paths(**code_runner_config)

	results = {
		"metadata": {
			"jira_id": jira_id,
			"commit_hash": commit_hash,
			"defect4j_bug_num": defect4j_bug_num,
			"defect4j_project": defect4j_project,
			"code_snippet": code_snippet,
			"numbered_code_snippet": LogInstructionApplier.add_line_numbers(code_snippet),
		},
		"initial_data": {
			"runtime_logs": None,
			"execution_outcome": None,
			"normalized_status": None,
			"instrumented_code": None,
			"instructions": None,
			"report": None,
		},
		"refinement_iterations": [],
		"final_data": {},
	}

	try:
		runtime_logs, execution_outcome, normalized_status = CodeRunner.run_code(
			defect4j_bug_num, defect4j_project, code_snippet
		)
		results["initial_data"]["runtime_logs"] = runtime_logs
		results["initial_data"]["execution_outcome"] = execution_outcome
		results["initial_data"]["normalized_status"] = normalized_status

		if normalized_status == "fatal_error" or normalized_status == "unknown":
			print(f"⚠️  [{defect4j_project}-{defect4j_bug_num}] Fatal/unknown error. Skipping.")
			results["final_data"]["error"] = "Cannot process due to fatal/unknown error"
			return results

		initial_logger_instance = initial_logger.InitialLogger(**model_config)

		instrumented_code, instructions, report = initial_logger_instance.add_initial_logging_code(
			code_snippet, execution_outcome
		)

		results["initial_data"]["instrumented_code"] = instrumented_code
		results["initial_data"]["instructions"] = instructions
		results["initial_data"]["report"] = report

		print(f"\n🔍 [{defect4j_project}-{defect4j_bug_num}] Running instrumented code...")
		runtime_logs, execution_outcome, normalized_status = CodeRunner.run_code(
			defect4j_bug_num, defect4j_project, instrumented_code
		)

		log_sufficient_evaluator_instance = log_sufficient_evaluator.LogSufficientEvaluator(
			**model_config
		)
		logging_code_refiner_instance = logging_code_refiner.LoggingCodeRefiner(**model_config)

		for iteration in range(max_refine_iterations):
			print(f"\n{'='*60}")
			print(
				f"📊 [{defect4j_project}-{defect4j_bug_num}] Iteration {iteration + 1}/{max_refine_iterations}"
			)
			print(f"{'='*60}")

			iteration_data = {
				"iteration": iteration + 1,
				"execution_outcome": execution_outcome,
				"normalized_status": normalized_status,
				"runtime_logs": runtime_logs,
			}

			if normalized_status == "fatal_error" or normalized_status == "unknown":
				print("⚠️  Fatal/unknown error detected. Stopping.")
				iteration_data["error"] = "Fatal or unknown error"
				results["refinement_iterations"].append(iteration_data)
				break

			compilation_fix_rounds = []
			if normalized_status == "compile_failed":
				print("🔧 Compilation error detected. Attempting to fix...")
				code_compilation_fixer_instance = code_compilation_fixer.DirectCompilationFixer(
					**compilation_fix_model_config
				)
				for attempt in range(max_compile_fix_attempts):
					print(f"   Attempt {attempt + 1}/{max_compile_fix_attempts}")

					fixed_code, fixed_instructions, error_analysis, fix_report = (
						code_compilation_fixer_instance.fix_compilation_error(
							code_snippet, instructions, execution_outcome
						)
					)

					instrumented_code = fixed_code
					instructions = fixed_instructions
					runtime_logs, execution_outcome, normalized_status = CodeRunner.run_code(
						defect4j_bug_num, defect4j_project, fixed_code
					)

					compilation_fix_rounds.append(
						{
							"attempt": attempt + 1,
							"fixed_code": fixed_code,
							"fixed_instructions": fixed_instructions,
							"error_analysis": error_analysis,
							"execution_outcome": execution_outcome,
							"normalized_status": normalized_status,
						}
					)

					if normalized_status in {"compile_success", "runtime_error", "test_timeout"}:
						print("✅ Compilation errors fixed.")
						break
					elif normalized_status == "compile_failed":
						print("❌ Compilation errors persist.")
						instructions = fixed_instructions
					else:
						raise RuntimeError(execution_outcome)

				iteration_data["compilation_fix_rounds"] = compilation_fix_rounds

				if normalized_status == "compile_failed":
					print("⚠️  Cannot fix compilation errors. Stopping.")
					iteration_data["error"] = "Cannot fix compilation errors after all attempts"
					iteration_data["final_status"] = "compilation_failed"
					results["refinement_iterations"].append(iteration_data)
					break

			print("\n📋 Evaluating log sufficiency...")
			is_sufficient, analysis, suggestions, evaluation_report = (
				log_sufficient_evaluator_instance.evaluate_log_sufficiency(
					code_snippet, instructions, runtime_logs, execution_outcome
				)
			)

			iteration_data["sufficiency_evaluation"] = {
				"is_sufficient": is_sufficient,
				"analysis": analysis,
				"suggestions": suggestions,
				"report": evaluation_report,
			}

			if is_sufficient:
				print("✅ Logging is sufficient. Refinement complete.")
				iteration_data["refinement"] = "Not needed - logs sufficient"
				results["refinement_iterations"].append(iteration_data)
				break

			print("\n🔄 Refining logging code...")
			refinement_instructions, refinement_report, refined_code, apply_report = (
				logging_code_refiner_instance.refine_logging_code(
					code_snippet, instructions, suggestions
				)
			)

			iteration_data["refinement"] = {
				"refinement_instructions": refinement_instructions,
				"refinement_report": refinement_report,
				"apply_report": apply_report,
				"refined_code": refined_code,
			}

			results["refinement_iterations"].append(iteration_data)

			instrumented_code = refined_code
			instructions = refinement_instructions

			print("\n🔍 Running refined code...")
			runtime_logs, execution_outcome, normalized_status = CodeRunner.run_code(
				defect4j_bug_num, defect4j_project, instrumented_code
			)

		if normalized_status == "compile_failed":
			code_compilation_fixer_instance = code_compilation_fixer.DirectCompilationFixer(
				**compilation_fix_model_config
			)

			final_compilation_fix_rounds = []
			for attempt in range(max_compile_fix_attempts):
				print(f"   Final fix attempt {attempt + 1}/{max_compile_fix_attempts}")

				fixed_code, fixed_instructions, error_analysis, fix_report = (
					code_compilation_fixer_instance.fix_compilation_error(
						code_snippet, instructions, execution_outcome
					)
				)

				instrumented_code = fixed_code
				instructions = fixed_instructions
				runtime_logs, execution_outcome, normalized_status = CodeRunner.run_code(
					defect4j_bug_num, defect4j_project, fixed_code
				)

				final_compilation_fix_rounds.append(
					{
						"attempt": attempt + 1,
						"fixed_code": fixed_code,
						"fixed_instructions": fixed_instructions,
						"error_analysis": error_analysis,
						"execution_outcome": execution_outcome,
						"normalized_status": normalized_status,
					}
				)

				if normalized_status in {"compile_success", "runtime_error", "test_timeout"}:
					print("✅ Final compilation errors fixed.")
					break
				elif normalized_status == "compile_failed":
					print("❌ Final compilation errors persist.")
					instructions = fixed_instructions
				else:
					raise RuntimeError(execution_outcome)

			results["final_data"]["final_compilation_fix_rounds"] = final_compilation_fix_rounds

		results["final_data"].update({
			"instrumented_code": instrumented_code,
			"instructions": instructions,
			"runtime_logs": runtime_logs,
			"execution_outcome": execution_outcome,
			"normalized_status": normalized_status,
			"total_iterations": len(results["refinement_iterations"]),
			"evaluation_summary": log_sufficient_evaluator_instance.get_evaluation_summary(),
		})
		if normalized_status in {"fatal_error", "unknown", "compile_failed"}:
			raise RuntimeError(execution_outcome)

		print(f"\n✅ [{defect4j_project}-{defect4j_bug_num}] Completed")

	except Exception as e:
		print(f"❌ [{defect4j_project}-{defect4j_bug_num}] Error: {e}")
		results["final_data"]["error"] = str(e)
		results["final_data"]["error_type"] = type(e).__name__

	return results


def process_items_concurrent(
	data_path="datasets/direct_debugging.json",
	output_path="results/direct_debugging_results.json",
	max_workers=2,
	save_interval=5,
	model_name="gpt-5-mini",
	compilation_fix_model_name="deepseek-v3",
	temperature=0,
	cache=True,
	max_compile_fix_attempts=5,
	max_refine_iterations=10,
	code_runner_config=None,
):
	Path(output_path).parent.mkdir(parents=True, exist_ok=True)

	with open(data_path, "r") as f:
		dataset = json.load(f)

	print(f"📊 Total items in dataset: {len(dataset)}")

	processed_ids = set()
	results = []

	if os.path.exists(output_path):
		print(f"📂 Loading checkpoint from {output_path}")
		with open(output_path, "r", encoding="utf-8") as f:
			results = json.load(f)
		results = [
			r for r in results
			if "error" not in r["final_data"]
			and r["final_data"].get("normalized_status") in {"compile_success", "runtime_error", "test_timeout"}
		]
		processed_ids = {
			(r["metadata"]["defect4j_project"], r["metadata"]["defect4j_bug_num"])
			for r in results
		}
		print(f"   ✅ Loaded {len(processed_ids)} successful items; failed items will be retried")
	else:
		print("📝 No checkpoint found. Starting from scratch.")

	items_to_process = [
		item
		for item in dataset
		if (item["defects4j_project"], item["defects4j_bug_num"]) not in processed_ids
	]

	if not items_to_process:
		print("✅ All items already processed!")
		return

	print(f"🔄 Processing {len(items_to_process)} remaining items...")
	print(f"   Already done: {len(processed_ids)}")
	print(f"   Remaining: {len(items_to_process)}")

	with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
		future_to_item = {}
		for item in items_to_process:
			future = executor.submit(
				add_logging_code_to_item,
				item["jira_id"],
				item["commit_hash"],
				item["defects4j_bug_num"],
				item["defects4j_project"],
				item["buggy_code"],
				model_name,
				compilation_fix_model_name,
				temperature,
				cache,
				max_compile_fix_attempts,
				max_refine_iterations,
				code_runner_config,
			)
			future_to_item[future] = item

		completed = 0

		with tqdm(total=len(items_to_process), desc="Processing") as pbar:
			for future in concurrent.futures.as_completed(future_to_item):
				item = future_to_item[future]
				bug_id = f"{item['defects4j_project']}-{item['defects4j_bug_num']}"

				try:
					result = future.result()
				except Exception as e:
					result = {
						"metadata": {
							"jira_id": item["jira_id"],
							"commit_hash": item["commit_hash"],
							"defect4j_bug_num": item["defects4j_bug_num"],
							"defect4j_project": item["defects4j_project"],
						},
						"final_data": {"error": str(e), "error_type": type(e).__name__},
					}
				results.append(result)
				completed += 1
				status = "❌" if "error" in result["final_data"] else "✅"
				pbar.set_postfix_str(f"{status} {bug_id}")
				pbar.update(1)
				if completed % save_interval == 0:
					save_checkpoint(output_path, results)
					print(f"\n💾 Checkpoint saved: {len(results)} total items")

	save_checkpoint(output_path, results)

	print(f"\n{'='*60}")
	print(f"✅ Processing completed!")
	print(f"{'='*60}")
	print(f"Total items: {len(results)}")
	print(
		f"Successfully processed: {sum(1 for r in results if 'error' not in r.get('final_data', {}))}"
	)
	print(f"Failed: {sum(1 for r in results if 'error' in r.get('final_data', {}))}")
	print(f"Results saved to: {output_path}")
	print(f"{'='*60}\n")


def _build_parser():
	parser = argparse.ArgumentParser(description="ReLog direct debugging")
	parser.add_argument(
		"--data-path", default="datasets/direct_debugging.json"
	)
	parser.add_argument(
		"--output-path",
		default="results/direct_debugging_results.json",
	)
	parser.add_argument("--max-workers", type=int, default=2)
	parser.add_argument("--save-interval", type=int, default=5)
	parser.add_argument("--model-name", default="gpt-5-mini")
	parser.add_argument("--compilation-fix-model-name", default="deepseek-v3")
	parser.add_argument("--temperature", type=float, default=0)
	parser.add_argument("--cache", action="store_true", default=True)
	parser.add_argument("--no-cache", action="store_false", dest="cache")
	parser.add_argument("--max-compile-fix-attempts", type=int, default=5)
	parser.add_argument("--max-refine-iterations", type=int, default=10)
	parser.add_argument("--runner-base-output-dir", default=None)
	parser.add_argument("--runner-source3-output-dir", default=None)
	parser.add_argument("--runner-script-path", default=None)
	parser.add_argument("--runner-working-dir", default=None)
	return parser


if __name__ == "__main__":
	args = _build_parser().parse_args()
	runner_config = {
		"base_output_dir": args.runner_base_output_dir,
		"source3_output_dir": args.runner_source3_output_dir,
		"script_file_path": args.runner_script_path,
		"working_dir_path": args.runner_working_dir,
	}
	if not any(runner_config.values()):
		runner_config = None

	process_items_concurrent(
		data_path=args.data_path,
		output_path=args.output_path,
		max_workers=args.max_workers,
		save_interval=args.save_interval,
		model_name=args.model_name,
		compilation_fix_model_name=args.compilation_fix_model_name,
		temperature=args.temperature,
		cache=args.cache,
		max_compile_fix_attempts=args.max_compile_fix_attempts,
		max_refine_iterations=args.max_refine_iterations,
		code_runner_config=runner_config,
	)
