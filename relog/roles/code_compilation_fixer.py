import json

import dspy

from ..base_dspy import BaseDspy
from ..utils import LogInstructionApplier


class CompilationErrorFixerSign(dspy.Signature):
	numbered_code: str = dspy.InputField(desc="The original code with line numbers for reference.")
	applied_instructions: str = dspy.InputField(
		desc="JSON array of logging instructions that were applied to the code."
	)
	compilation_error_info: str = dspy.InputField(desc="Compilation error message from javac.")
	previous_fix_history: str = dspy.InputField(
		desc="History of previous fix attempts in this round (empty if first attempt)."
	)

	error_analysis: str = dspy.OutputField(
		desc=(
			"Analyze the compilation error step by step:\n"
			"0. HISTORY CHECK: Review previous_fix_history. If the same error persists, "
			"identify what went wrong in the previous fix.\n"
			"1. ROOT CAUSE: Identify which log instruction(s) caused the error.\n"
			"2. ERROR TYPE: Classify (e.g., syntax error, undefined variable, unreachable code).\n"
			"3. IMPACT: Determine if other logs are affected.\n"
			"4. FIX STRATEGY: Describe the specific changes needed.\n"
		)
	)

	fix_actions: str = dspy.OutputField(
		desc=(
			"Generate fix actions as a JSON array. Each action must modify or remove problematic logging instructions.\n\n"
			"📋 REQUIRED FIELDS FOR EACH ACTION:\n"
			'- action: "modify" or "remove"\n'
			"- target_line: <int> - The line_number of the instruction to fix\n"
			"📋 ADDITIONAL FIELDS FOR 'modify' ACTION:\n"
			"- new_line_number: <int> - Where to place the log (required if moving)\n"
			'- new_position: "before" or "after" - Position relative to new_line_number\n'
			"- new_log: <string> - Corrected log statement (optional, only if log content needs fixing)\n\n"
			"⚠️ CRITICAL RULES:\n"
			"1. EXACT MATCHING: Use target_line to identify which instruction to modify\n"
			"   - If multiple logs exist at the same line, the first one matching target_line will be modified\n"
			"   - To modify multiple logs at the same line, create separate actions\n"
			"2. POSITION RULES:\n"
			"   - NEVER place logs inside multi-line expressions (if/while/return conditions)\n"
			"   - Place logs INSIDE code blocks (after '{'), not between statement lines\n"
			"   - For multi-line statements, move ALL affected logs together\n"
			"3. SCOPE RULES:\n"
			"   - Ensure variables are declared before they are logged\n"
			"   - If a log references an undefined variable, move it after the declaration\n"
			"4. SYNTAX RULES:\n"
			"   - Check for proper escape sequences in strings\n"
			"   - Ensure log statements are complete Java statements\n"
			"5. PRESERVATION:\n"
			"   - Only modify instructions that are causing errors\n"
			"   - Keep other instructions unchanged\n\n"
			"📤 OUTPUT FORMAT:\n"
			"Return ONLY a valid JSON array. Do not include explanations outside the JSON.\n\n"
			"Example structure:\n"
			"[\n"
			"  {\n"
			'    "action": "modify",\n'
			'    "target_line": 5,\n'
			'    "new_line_number": 4,\n'
			'    "new_position": "after"\n'
			"  },\n"
			"  {\n"
			'    "action": "remove",\n'
			'    "target_line": 10,\n'
			"  }\n"
			"]"
		)
	)


class DirectCompilationErrorFixerSign(dspy.Signature):
	numbered_code: str = dspy.InputField(desc="The original code with line numbers for reference.")
	applied_instructions: str = dspy.InputField(
		desc="JSON array of logging instructions that were applied to the code."
	)
	compilation_error_info: str = dspy.InputField(desc="Compilation error message from javac.")
	previous_fix_history: str = dspy.InputField(
		desc="History of previous fix attempts in this round (empty if first attempt)."
	)

	error_analysis: str = dspy.OutputField(
		desc=(
			"Analyze the compilation error step by step:\n"
			"0. HISTORY CHECK: Review previous_fix_history. If the same error persists, "
			"identify what went wrong in the previous fix.\n"
			"1. ROOT CAUSE: Identify which log instruction(s) caused the error.\n"
			"2. ERROR TYPE: Classify (e.g., syntax error, undefined variable, unreachable code).\n"
			"3. IMPACT: Determine if other logs are affected.\n"
			"4. FIX STRATEGY: Describe the specific changes needed.\n"
		)
	)

	fixed_instructions: str = dspy.OutputField(
		desc=(
			"Generate the COMPLETE fixed instruction list as a JSON array.\n\n"
			"📋 INSTRUCTIONS:\n"
			"1. Start with ALL instructions from applied_instructions\n"
			"2. Fix ONLY the problematic ones that caused the compilation error\n"
			"3. Keep all other instructions unchanged\n"
			"4. Return the complete updated list\n\n"
			"📋 EACH INSTRUCTION MUST HAVE:\n"
			"- line_number: <int> - Where to insert the log\n"
			'- position: "before" or "after" - Position relative to the line\n'
			"- log_statement: <string> - Complete Java print statement\n\n"
			"⚠️ DO NOT INCLUDE:\n"
			"- reason field (not needed)\n"
			"- priority field (not needed)\n"
			"- Any other extra fields\n\n"
			"⚠️ CRITICAL FIX RULES:\n"
			"1. MULTI-LINE STATEMENTS:\n"
			"   - If a log is inserted in the middle of if/while/for/return statements, move it\n"
			"   - Place it INSIDE the code block (after '{') or BEFORE the statement starts\n"
			"2. VARIABLE SCOPE:\n"
			"   - If a log references an undefined variable, move it after the variable declaration\n"
			"   - Check that all variables in log_statement are in scope at the insertion point\n"
			"3. SYNTAX ERRORS:\n"
			"   - Fix escape sequences (use '\\\\n' for newline in Java strings)\n"
			"   - Ensure log_statement ends with semicolon\n"
			"   - Check parentheses and quotes are balanced\n"
			"4. PRESERVATION:\n"
			"   - Only modify instructions that are causing errors\n"
			"   - Keep the same number of instructions (unless removing duplicates)\n"
			"   - Maintain the original intent of each log\n\n"
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
			"- Return the complete instruction list (not just the changed ones)"
		)
	)


class DirectCompilationFixer(BaseDspy):
	def _post_init(self, **kwargs):
		self.fixer_signature = DirectCompilationErrorFixerSign
		self.applier = LogInstructionApplier()
		self.compilation_fix_history_records = []

	def fix_compilation_error(
		self, original_code_snippet, applied_instructions, compilation_error_info, max_llm_retries=3
	):
		numbered_code = self.applier.add_line_numbers(original_code_snippet)

		instructions_str = self._format_instructions_for_llm(applied_instructions)

		history_summary = self._build_compilation_history(self.compilation_fix_history_records)

		with self.use_model():
			fixer = dspy.ChainOfThought(self.fixer_signature)

			for attempt in range(max_llm_retries):
				try:
					result = fixer(
						numbered_code=numbered_code,
						applied_instructions=instructions_str,
						compilation_error_info=compilation_error_info,
						previous_fix_history=history_summary,
					)

					fixed_instructions = self.applier.parse_instructions(result.fixed_instructions)

					self.compilation_fix_history_records.append(
						{
							"round": len(self.compilation_fix_history_records) + 1,
							"original_error": compilation_error_info,
							"error_analysis": result.error_analysis,
							"instructions_before": applied_instructions,
							"instructions_after": fixed_instructions,
						}
					)

					fixed_code, apply_report = self.applier.apply_instructions(
						original_code_snippet, fixed_instructions
					)

					return fixed_code, fixed_instructions, result.error_analysis, {}

				except Exception as e:
					print(
						f"❌ Direct compilation fix attempt {attempt + 1}/{max_llm_retries} failed: {e}"
					)
					if attempt == max_llm_retries - 1:
						raise RuntimeError(f"Compilation repair failed after {max_llm_retries} attempts") from e

		raise RuntimeError("Max LLM retries exceeded for direct compilation fixing.")

	def _format_instructions_for_llm(self, instructions):
		return json.dumps(instructions, indent=2)

	def _build_compilation_history(self, history_records):
		if not history_records:
			return "No previous compilation fixes attempted."

		lines = [f"Previous compilation fix attempts: {len(history_records)}"]

		for record in history_records[-3:]:
			lines.append(f"\nRound {record['round']}:")

			error_snippet = record["original_error"][:150]
			if len(record["original_error"]) > 150:
				error_snippet += "..."
			lines.append(f"  Error: {error_snippet}")

			before = record.get("instructions_before", [])
			after = record.get("instructions_after", [])

			lines.append(f"  Instructions: {len(before)} → {len(after)}")

			if before and after:
				changed_lines = set(i["line_number"] for i in before) ^ set(
					i["line_number"] for i in after
				)
				if changed_lines:
					lines.append(f"  Changed lines: {sorted(changed_lines)}")

			if record.get("error_analysis"):
				analysis_snippet = record["error_analysis"][:150]
				if len(record["error_analysis"]) > 150:
					analysis_snippet += "..."
				lines.append(f"  Analysis: {analysis_snippet}")

		lines.append(
			"\n⚠️  LEARN from failures: If the same error persists, try a DIFFERENT approach!"
		)

		return "\n".join(lines)


class CompilationFixer(BaseDspy):
	def _post_init(self, **kwargs):
		self.fixer_signature = CompilationErrorFixerSign
		self.applier = LogInstructionApplier()
		self.compilation_fix_history_records = []

	def fix_compilation_error(
		self, original_code_snippet, applied_instructions, compilation_error_info, max_llm_retries=3
	):
		numbered_code = self.applier.add_line_numbers(original_code_snippet)

		instructions_str = self._format_instructions_for_llm(applied_instructions)

		history_summary = self._build_compilation_history(self.compilation_fix_history_records)

		with self.use_model():
			fixer = dspy.ChainOfThought(self.fixer_signature)

			for attempt in range(max_llm_retries):
				try:
					result = fixer(
						numbered_code=numbered_code,
						applied_instructions=instructions_str,
						compilation_error_info=compilation_error_info,
						previous_fix_history=history_summary,
					)

					fix_actions = self._parse_fix_actions(result.fix_actions)

					if not fix_actions:
						raise ValueError("No valid fix actions generated")

					fixed_instructions, fix_report = self._apply_fix_actions(
						original_instructions=applied_instructions, fix_actions=fix_actions
					)

					self.compilation_fix_history_records.append(
						{
							"round": len(self.compilation_fix_history_records) + 1,
							"original_error": compilation_error_info,
							"error_analysis": result.error_analysis,
							"fix_report": fix_report,
							"instructions_before": len(applied_instructions),
							"instructions_after": len(fixed_instructions),
						}
					)

					fixed_code, apply_report = self.applier.apply_instructions(
						original_code_snippet, fixed_instructions
					)

					return fixed_code, fixed_instructions, result.error_analysis, fix_report

				except Exception as e:
					print(f"❌ Compilation fix attempt {attempt + 1}/{max_llm_retries} failed: {e}")
					if attempt == max_llm_retries - 1:
						raise RuntimeError(f"Compilation repair failed after {max_llm_retries} attempts") from e

		raise RuntimeError("Max LLM retries exceeded for compilation fixing.")

	def _parse_fix_actions(self, fix_actions_str):
		try:
			fix_actions_str = fix_actions_str.strip()
			if fix_actions_str.startswith("```"):
				lines = fix_actions_str.split("\n")
				json_lines = []
				in_json = False

				for line in lines:
					if line.strip().startswith("```"):
						if in_json:
							break
						else:
							in_json = True
							continue
					if in_json:
						json_lines.append(line)

				fix_actions_str = "\n".join(json_lines)

			fix_actions = json.loads(fix_actions_str)

			for i, action in enumerate(fix_actions):
				if "action" not in action:
					print(f"⚠️  Action {i} missing 'action' field, skipping")
					continue

				if action["action"] == "modify":
					if "new_line_number" not in action and "new_log" not in action:
						print(
							f"⚠️  Warning: Action {i} has 'modify' but no new_line_number or new_log"
						)
						print(f"   This won't change the insertion point!")

					action.setdefault("new_line_number", action.get("target_line"))
					action.setdefault("new_position", "after")

			return fix_actions

		except json.JSONDecodeError as e:
			print(f"❌ Failed to parse fix_actions JSON: {e}")
			print(f"Raw output: {fix_actions_str[:500]}")
			return []

	def _validate_fix_action(self, action):
		if not isinstance(action, dict):
			raise ValueError(f"Action must be a dict, got {type(action)}")

		action_type = action.get("action", "").lower()

		if action_type not in ["remove", "replace", "modify"]:
			raise ValueError(f"Unknown action type: {action_type}")

		if "target_line" not in action:
			raise ValueError(f"Missing 'target_line' in action: {action}")

		validated = {
			"action": action_type,
			"target_line": int(action["target_line"]),
		}

		if action_type in ["replace", "modify"]:
			new_inst = action.get("new_instruction")
			if not new_inst:
				raise ValueError(
					f"{action_type.upper()} action missing 'new_instruction': {action}"
				)

			if "log_statement" not in new_inst:
				raise ValueError(f"new_instruction missing 'log_statement': {new_inst}")

			validated["new_instruction"] = {
				"line_number": int(new_inst.get("line_number", validated["target_line"])),
				"position": new_inst.get("position", "after"),
				"log_statement": new_inst["log_statement"],
			}

		return validated

	def _format_instructions_for_llm(self, instructions):
		return json.dumps(instructions, indent=2)

	def _build_compilation_history(self, history_records):
		if not history_records:
			return "No previous compilation fixes attempted."

		lines = [f"Previous compilation fix attempts: {len(history_records)}"]

		for record in history_records[-3:]:
			lines.append(f"\nRound {record['round']}:")

			error_snippet = record["original_error"][:100]
			if len(record["original_error"]) > 100:
				error_snippet += "..."
			lines.append(f"  Error: {error_snippet}")

			fix_report = record.get("fix_report", {})
			actions_applied = fix_report.get("actions_applied", 0)
			actions_failed = fix_report.get("actions_failed", 0)
			lines.append(f"  Actions: {actions_applied} applied, {actions_failed} failed")

			before = record.get("instructions_before", 0)
			after = record.get("instructions_after", 0)
			lines.append(f"  Instructions: {before} → {after}")

			if record.get("error_analysis"):
				analysis_snippet = record["error_analysis"][:150]
				if len(record["error_analysis"]) > 150:
					analysis_snippet += "..."
				lines.append(f"  Analysis: {analysis_snippet}")

		lines.append(
			"\n⚠️  IMPORTANT: Learn from previous failures. Do NOT repeat the same fix actions that failed before."
		)

		return "\n".join(lines)

	def _apply_fix_actions(self, original_instructions, fix_actions):
		result_instructions = []
		processed_indices = set()

		fix_report = {"actions_applied": 0, "actions_failed": 0, "details": []}

		print(f"\n🔍 Original instructions ({len(original_instructions)} total):")
		for i, inst in enumerate(original_instructions):
			print(
				f"  [{i}] line={inst.get('line_number')}, pos={inst.get('position')}, log={inst.get('log_statement')[:50]}..."
			)

		print(f"\n🔍 Fix actions ({len(fix_actions)} total):")
		for action in fix_actions:
			print(
				f"  action={action.get('action')}, target={action.get('target_line')}, new_line={action.get('new_line_number')}"
			)

		for action in fix_actions:
			action_type = action.get("action")
			target_line = action.get("target_line")

			if action_type == "remove":
				for i, inst in enumerate(original_instructions):
					if inst.get("line_number") == target_line and i not in processed_indices:
						processed_indices.add(i)
						fix_report["actions_applied"] += 1
						fix_report["details"].append(
							{"action": "remove", "target_line": target_line, "status": "success"}
						)
						print(f"  ✅ Removed instruction at line {target_line}")
						break
				else:
					fix_report["actions_failed"] += 1
					fix_report["details"].append(
						{
							"action": "remove",
							"target_line": target_line,
							"status": "failed",
							"error": f"No instruction found at line {target_line}",
						}
					)
					print(f"  ❌ Failed to remove: no instruction at line {target_line}")

			elif action_type == "modify":
				found = False

				for i, inst in enumerate(original_instructions):
					if inst.get("line_number") == target_line and i not in processed_indices:
						new_inst = inst.copy()

						old_line = new_inst["line_number"]
						new_line = action.get("new_line_number", old_line)
						new_inst["line_number"] = new_line
						new_inst["position"] = action.get("new_position", inst["position"])

						if "new_log" in action:
							new_inst["log_statement"] = action["new_log"]

						result_instructions.append(new_inst)
						processed_indices.add(i)
						found = True

						fix_report["actions_applied"] += 1
						fix_report["details"].append(
							{
								"action": "modify",
								"old_line": old_line,
								"new_line": new_line,
								"status": "success",
							}
						)

						print(
							f"  ✅ Modified instruction: line {old_line} → {new_line}, pos={new_inst['position']}"
						)
						break

				if not found:
					fix_report["actions_failed"] += 1
					fix_report["details"].append(
						{
							"action": "modify",
							"target_line": target_line,
							"status": "failed",
							"error": f"No instruction found at line {target_line}",
						}
					)
					print(f"  ❌ Failed to modify: no instruction at line {target_line}")
					print(
						f"     Available lines: {[inst.get('line_number') for inst in original_instructions]}"
					)

		for i, inst in enumerate(original_instructions):
			if i not in processed_indices:
				result_instructions.append(inst)

		print(
			f"\n✅ Fix summary: {fix_report['actions_applied']} applied, {fix_report['actions_failed']} failed"
		)
		print(
			f"📋 Result: {len(result_instructions)} instructions (was {len(original_instructions)})"
		)

		return result_instructions, fix_report
