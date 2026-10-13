import json

import dspy

from ..base_dspy import BaseDspy
from ..utils import LogInstructionApplier


class LoggingCodeRefinerSign(dspy.Signature):
	original_code_snippet: str = dspy.InputField(
		desc="The original Java code with line numbers (without logging)."
	)

	current_logging_instructions: str = dspy.InputField(
		desc=(
			"Current logging instructions as JSON array:\n"
			'[{"line_number": 5, "position": "after", "log_statement": "..."}]'
		)
	)

	improvement_suggestions: str = dspy.InputField(
		desc=(
			"Specific improvement suggestions from the evaluator.\n"
			"Examples:\n"
			"- ADD: Log variable X at line Y to track state changes\n"
			"- REMOVE: Delete redundant log at line Z\n"
			"- MODIFY: Enhance log at line W to include more context"
		)
	)

	analysis: str = dspy.OutputField(
		desc=(
			"Analyze the improvement suggestions:\n"
			"1. UNDERSTAND: What improvements are requested?\n"
			"2. IMPACT: How will these changes improve debugging?\n"
			"3. STRATEGY: What specific changes to make?\n"
			"4. VALIDATION: Check for potential issues (scope, syntax, placement)"
		)
	)

	refined_instructions: str = dspy.OutputField(
		desc=(
			"Generate the COMPLETE refined instruction list as a JSON array.\n\n"
			"📋 INSTRUCTIONS:\n"
			"1. Start with ALL instructions from current_logging_instructions\n"
			"2. Apply the improvements suggested (add/remove/modify)\n"
			"3. Ensure all changes follow Java syntax and scope rules\n"
			"4. Return the complete updated list\n\n"
			"📋 EACH INSTRUCTION MUST HAVE:\n"
			"- line_number: <int> - Where to insert the log\n"
			'- position: "before" or "after" - Position relative to the line\n'
			"- log_statement: <string> - Complete Java print statement\n\n"
			"⚠️ CRITICAL RULES:\n"
			"1. PLACEMENT RULES:\n"
			"   - NEVER insert logs inside multi-line expressions (if/while/for/return conditions)\n"
			"   - Place logs INSIDE code blocks (after '{'), not between statement lines\n"
			"   - For loop variables, log INSIDE the loop body\n"
			"2. VARIABLE SCOPE:\n"
			"   - Ensure all variables in log_statement are declared before the log position\n"
			"   - Variables assigned in conditions (e.g., while ((c = ...))) are only valid inside the block\n"
			"3. SYNTAX RULES:\n"
			"   - Use proper escape sequences: '\\\\n' for newline in Java strings\n"
			"   - Ensure log_statement ends with semicolon\n"
			"   - Use + for string concatenation with variables\n"
			"4. PRESERVATION:\n"
			"   - Keep logs that are not mentioned in improvement_suggestions\n"
			"   - Maintain the original intent of each log\n"
			"   - Only add/remove/modify as explicitly requested\n\n"
			"📤 OUTPUT FORMAT:\n"
			"Return ONLY a valid JSON array with this exact structure:\n"
			"[\n"
			"  {\n"
			'    "line_number": 2,\n'
			'    "position": "after",\n'
			'    "log_statement": "System.out.println(\\"DEBUG: x=\\" + x);"\n'
			"  },\n"
			"  {\n"
			'    "line_number": 5,\n'
			'    "position": "before",\n'
			'    "log_statement": "System.out.println(\\"DEBUG: Entering loop\\");"\n'
			"  }\n"
			"]\n\n"
			"⚠️ IMPORTANT:\n"
			"- Do NOT wrap the JSON in markdown code blocks\n"
			"- Do NOT add explanations outside the JSON\n"
			"- Return the complete instruction list (not just changes)"
		)
	)


class LoggingCodeRefiner(BaseDspy):
	def _post_init(self, **kwargs):
		self.refiner_signature = LoggingCodeRefinerSign
		self.applier = LogInstructionApplier()

	def refine_logging_code(
		self,
		original_code_snippet,
		current_instructions,
		improvement_suggestions_text,
		max_llm_retries=3,
	):
		if not improvement_suggestions_text or improvement_suggestions_text.strip() in [
			"No improvements needed.",
			"SUFFICIENT",
		]:
			print("✅ No improvements needed, keeping current instructions")
			current_code, apply_report = self.applier.apply_instructions(
				original_code_snippet, current_instructions
			)
			return (
				current_instructions,
				{"status": "no_changes", "message": "No improvements suggested"},
				current_code,
				apply_report,
			)

		numbered_code = self.applier.add_line_numbers(original_code_snippet)
		instructions_str = self._format_instructions_for_llm(current_instructions)

		with self.use_model():
			refiner = dspy.ChainOfThought(self.refiner_signature)

			for attempt in range(max_llm_retries):
				try:
					result = refiner(
						original_code_snippet=numbered_code,
						current_logging_instructions=instructions_str,
						improvement_suggestions=improvement_suggestions_text,
					)

					refined_instructions = self._parse_instructions(result.refined_instructions)

					if not refined_instructions:
						raise ValueError("No valid instructions generated")

					refinement_report = self._generate_refinement_report(
						current_instructions, refined_instructions, result.analysis
					)

					print(
						f"✅ Refined instructions: {len(current_instructions)} → {len(refined_instructions)}"
					)

					refined_code, apply_report = self.applier.apply_instructions(
						original_code_snippet, refined_instructions
					)

					return refined_instructions, refinement_report, refined_code, apply_report

				except Exception as e:
					print(f"❌ Refinement attempt {attempt + 1}/{max_llm_retries} failed: {e}")
					if attempt == max_llm_retries - 1:
						raise RuntimeError(f"Logging refinement failed after {max_llm_retries} attempts") from e

		raise RuntimeError("Max LLM retries exceeded for logging refinement.")

	def _parse_instructions(self, json_str):
		return self.applier.parse_instructions(json_str)

	def _generate_refinement_report(self, original_instructions, refined_instructions, analysis):
		original_map = {}
		for inst in original_instructions:
			key = (inst["line_number"], inst["position"])
			original_map[key] = inst

		refined_map = {}
		for inst in refined_instructions:
			key = (inst["line_number"], inst["position"])
			refined_map[key] = inst

		changes = {"added": [], "removed": [], "modified": []}

		for key, refined_inst in refined_map.items():
			if key not in original_map:
				changes["added"].append(
					{
						"line": key[0],
						"position": key[1],
						"log": refined_inst["log_statement"][:50] + "...",
					}
				)
			else:
				original_inst = original_map[key]
				if original_inst["log_statement"] != refined_inst["log_statement"]:
					changes["modified"].append(
						{
							"line": key[0],
							"position": key[1],
							"old_log": original_inst["log_statement"][:50] + "...",
							"new_log": refined_inst["log_statement"][:50] + "...",
						}
					)

		for key, original_inst in original_map.items():
			if key not in refined_map:
				changes["removed"].append(
					{
						"line": key[0],
						"position": key[1],
						"log": original_inst["log_statement"][:50] + "...",
					}
				)

		report = {
			"status": "success",
			"analysis": analysis,
			"original_count": len(original_instructions),
			"refined_count": len(refined_instructions),
			"changes": changes,
			"summary": (
				f"{len(changes['added'])} added, "
				f"{len(changes['removed'])} removed, "
				f"{len(changes['modified'])} modified"
			),
		}

		print(f"📊 Refinement changes: {report['summary']}")
		for added in changes["added"]:
			print(f"   ➕ ADD: line {added['line']} ({added['position']})")
		for removed in changes["removed"]:
			print(f"   🗑️  REMOVE: line {removed['line']} ({removed['position']})")
		for modified in changes["modified"]:
			print(f"   ✏️  MODIFY: line {modified['line']} ({modified['position']})")

		return report

	def _format_instructions_for_llm(self, instructions):
		return json.dumps(instructions, indent=2)
