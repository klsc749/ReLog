import dspy

from ..base_dspy import BaseDspy
from ..utils import LogInstructionApplier


class InitialLoggingInstructionSign(dspy.Signature):
	original_code_snippet: str = dspy.InputField(
		desc="The ORIGINAL Java code (with line numbers) that needs debugging logs."
	)

	initial_execution_outcome: str = dspy.InputField(
		desc=("The observed result of running the original code.")
	)

	logging_instructions: str = dspy.OutputField(
		desc=(
			"Generate logging instructions as JSON array.\n\n"
			"OUTPUT FORMAT: JSON array of logging instructions:\n"
			"[\n"
			"  {\n"
			'    "line_number": <int>,\n'
			'    "position": "after" | "before",\n'
			'    "log_statement": "System.out.println(...)",\n'
			"  }\n"
			"]\n\n"
			"RULES:\n"
			"1. Use ONLY System.out.println() - no imports\n"
			"2. Log statements must reference existing variables only\n"
			"3. NEVER insert logs inside multi-line statements (if/while/for conditions)\n"
			"4. Insert logs INSIDE code blocks (after '{'), not before or between conditions\n"
			"5. Ensure variables are declared before logging them\n"
			"6. Use proper Java escape sequences in strings\n\n"
			"7. Align priorities with the provided strategy\n"
			"8. Return ONLY valid JSON, no markdown\n\n"
			"EXAMPLE Result:\n"
			"[\n"
			"  {\n"
			'    "line_number": 15,\n'
			'    "position": "before",\n'
			'    "log_statement": "System.out.println(\\"DEBUG: x = \\" + x);",\n'
			"  }\n"
			"]"
		)
	)


class InitialLoggingWithStrategySign(InitialLoggingInstructionSign):
	logging_strategy: str = dspy.InputField(
		desc=(
			"Pre-analyzed logging strategy based on static analysis."
			"Use this to guide your logging placement decisions."
		)
	)

	logging_instructions: str = dspy.OutputField(
		desc=(
			"You are an expert Java debugger with access to a pre-analyzed logging strategy.\n\n"
			"GOAL: Generate logging instructions following the provided strategy.\n\n"
			"OUTPUT FORMAT: JSON array of logging instructions:\n"
			"[\n"
			"  {\n"
			'    "line_number": <int>,\n'
			'    "position": "after" | "before",\n'
			'    "log_statement": "System.out.println(...)",\n'
			"  }\n"
			"]\n\n"
			"HOW TO USE LOGGING_STRATEGY:\n"
			"1. Review the HIGH priority locations first\n"
			"2. Ensure all HIGH priority points have logs\n"
			"3. Add MEDIUM priority logs\n"
			"4. Add LOW priority logs (if space allows)\n"
			"5. Prioritize quality over quantity\n\n"
			"RULES:\n"
			"1. Use ONLY System.out.println() - no imports\n"
			"2. Log statements must reference existing variables only\n"
			"3. NEVER insert logs inside multi-line statements (if/while/for conditions)\n"
			"4. Insert logs INSIDE code blocks (after '{'), not before or between conditions\n"
			"5. Ensure variables are declared before logging them\n"
			"6. Use proper Java escape sequences in strings\n\n"
			"7. Align priorities with the provided strategy\n"
			"8. Return ONLY valid JSON, no markdown\n\n"
			"EXAMPLE with strategy:\n"
			"If strategy says: 'HIGH priority: line 15 (variable x before crash)'\n"
			"Then generate:\n"
			"[\n"
			"  {\n"
			'    "line_number": 15,\n'
			'    "position": "before",\n'
			'    "log_statement": "System.out.println(\\"DEBUG: x = \\" + x);",\n'
			"  }\n"
			"]"
		)
	)


class InitialLogger(BaseDspy):
	def _post_init(self, **kwargs):
		self.applier = LogInstructionApplier()

	def add_initial_logging_code(
		self, code_snippet, initial_execution_outcome, logging_strategy=None, max_llm_retries=3
	):
		numbered_code = self.applier.add_line_numbers(code_snippet)

		signature = self._select_signature(logging_strategy is not None)

		with self.use_model():
			logger = dspy.ChainOfThought(signature)

			for attempt in range(max_llm_retries):
				try:
					inputs = {
						"original_code_snippet": numbered_code,
						"initial_execution_outcome": initial_execution_outcome,
					}

					if logging_strategy:
						inputs["logging_strategy"] = logging_strategy

					result = logger(**inputs)

					instructions = self.applier.parse_instructions(result.logging_instructions)

					if not instructions:
						raise ValueError("No valid instructions generated")

					print(f"✅ Generated {len(instructions)} logging instructions")

					instrumented_code, report = self.applier.apply_instructions(
						code_snippet, instructions
					)

					self._print_application_summary(report)

					return instrumented_code, instructions, report

				except Exception as e:
					print(f"❌ Initial logging attempt {attempt + 1}/{max_llm_retries} failed: {e}")

					if attempt == max_llm_retries - 1:
						raise RuntimeError(f"Initial logging failed after {max_llm_retries} attempts") from e

		raise RuntimeError("Unexpected error: exceeded max retries without proper error handling")

	def _select_signature(self, has_strategy):
		if has_strategy:
			return InitialLoggingWithStrategySign
		else:
			return InitialLoggingInstructionSign

	def _print_application_summary(self, report):
		total = report["total_instructions"]
		applied_count = len(report["applied"])
		failed_count = len(report["failed"])

		if failed_count == 0:
			print(f"✅ All {total} instructions applied successfully")
		elif applied_count == 0:
			print(f"❌ All {total} instructions failed to apply")
		else:
			success_rate = (applied_count / total) * 100
			print(
				f"⚠️  Partial success: {applied_count}/{total} applied ({success_rate:.1f}%), {failed_count} failed"
			)

			if failed_count <= 3:
				print("   Failed instructions:")
				for failed in report["failed"]:
					line = failed["instruction"].get("line_number", "?")
					error = failed["error"][:80]
					print(f"      - Line {line}: {error}")
			else:
				print(f"   ({failed_count} failures - check report for details)")
