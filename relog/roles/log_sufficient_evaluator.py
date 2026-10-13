import json

import dspy

from ..base_dspy import BaseDspy
from ..utils import LogInstructionApplier


class LogSufficiencyEvaluatorSign(dspy.Signature):
	original_code_snippet: str = dspy.InputField(desc="The ORIGINAL Java code (with line numbers).")

	applied_logging_instructions: str = dspy.InputField(
		desc=(
			"JSON array of applied logging instructions:\n"
			'[{"line_number": 5, "position": "after", '
			'"log_statement": "System.out.println(...)", "reason": "...", "priority": "HIGH"}]'
		)
	)

	runtime_logs: str = dspy.InputField(desc="Console output from executing the instrumented code.")

	execution_outcome: str = dspy.InputField(
		desc=(
			"Execution result from CodeRunner:\n"
			"- COMPILATION ERROR: 'COMPILATION ERROR:\\n>>> FileName.java:15: error: ...'\n"
			"- RUNTIME ERROR: '✓ Compilation successful.\\nRUNTIME EXCEPTION:\\n>>> java.lang.NullPointerException at ...'\n"
			"- SUCCESS: '✓ Compilation successful.\\n✓ Execution completed without exceptions.'\n"
			"- TIMEOUT: '⏱️ TIMEOUT: Execution exceeded time limit.'\n"
			"- FATAL ERROR: '❌ FATAL ERROR: Script execution failed.'"
		)
	)

	analysis: str = dspy.OutputField(
		desc=(
			"Analyze logging sufficiency:\n\n"
			"1. CLASSIFY OUTCOME: Identify what happened (compilation error/runtime error/success/timeout/fatal)\n"
			"2. ANALYZE LOGS vs OUTCOME:\n"
			"   - For RUNTIME ERROR: Are crash-related variables logged? Can we see what caused it?\n"
			"   - For SUCCESS: Can we trace execution flow? Are key decisions visible?\n"
			"   - For TIMEOUT: Are loop counters/conditions logged?\n"
			"   - For COMPILATION ERROR: Which log caused it? (rare - CompilationFixer handles this)\n"
			"3. IDENTIFY GAPS: What critical info is missing?\n"
			"4. JUDGE SUFFICIENCY: Can we explain the outcome from these logs alone?\n\n"
			"Output: Structured analysis covering outcome, what logs show, what's missing, and sufficiency."
		)
	)

	is_sufficient: bool = dspy.OutputField(
		desc=(
			"Return True if:\n"
			"- For RUNTIME ERROR: We can see the variables that caused it\n"
			"- For SUCCESS: We can understand the execution flow\n"
			"- For EXTERNAL METHOD issue: We've identified the problem is in a helper method we cannot instrument\n"
			"- No additional logs IN THIS METHOD would help\n\n"
			"Return False if:\n"
			"- Key variables in THIS METHOD are not logged\n"
			"- We cannot explain THIS METHOD's behavior\n"
			"- Don't return False just because external methods are black boxes"
		)
	)

	improvement_suggestions: str = dspy.OutputField(
		desc=(
			"HIGH-LEVEL suggestions (NOT code implementation):\n\n"
			"FORMAT: One per line:\n"
			"1. [ACTION] What to do - Why it matters (priority)\n\n"
			"ACTIONS:\n"
			"- ADD: 'Add log for variable X at line Y before error - HIGH'\n"
			"- REMOVE: 'Remove redundant log at line Z - LOW'\n"
			"- MODIFY: 'Enhance log at line W with more context - MEDIUM'\n"
			"- RELOCATE: 'Move log from line A to B to capture earlier state - MEDIUM'\n\n"
			"GUIDELINES:\n"
			"- Be SPECIFIC: exact line numbers, variable names, reasons\n"
			"- PRIORITIZE: HIGH priority first\n"
			"- ADAPT: Match suggestions to outcome type\n"
			"- For COMPILATION ERROR: Usually 'CompilationFixer will handle this.'\n"
			"- If sufficient: 'No improvements needed.'\n\n"
			"Focus on WHAT and WHY, not HOW."
		)
	)


class LogSufficiencyEvaluatorWithHistorySign(LogSufficiencyEvaluatorSign):
	evaluation_history: str = dspy.InputField(
		desc=(
			"Previous evaluation rounds:\n"
			"- What feedback was given\n"
			"- Which logs were added/removed\n"
			"- Did previous suggestions help?\n"
			"- Are we stuck in a loop?\n\n"
			"Use this to AVOID repeating ineffective suggestions."
		)
	)

	analysis: str = dspy.OutputField(
		desc=(
			"Analyze with LEARNING from history:\n\n"
			"1. CHECK HISTORY: What was tried? Did it help? Are we repeating?\n"
			"2. CLASSIFY OUTCOME: What happened? Has outcome changed?\n"
			"3. ANALYZE LOGS: What changed since last round? What's still missing?\n"
			"4. ASSESS PROGRESS: Getting closer or going in circles?\n"
			"5. JUDGE: Are logs sufficient NOW? What NEW info is needed?\n\n"
			"Output: Analysis covering history learnings, current state, and sufficiency."
		)
	)

	improvement_suggestions: str = dspy.OutputField(
		desc=(
			"Suggestions LEARNING from history:\n\n"
			"FORMAT: One per line with priority\n\n"
			"CRITICAL - LEARN FROM HISTORY:\n"
			"1. DON'T repeat suggestions that didn't help\n"
			"2. If stuck (3+ rounds insufficient), try DIFFERENT approach\n"
			"3. Escalate: Round 1-2 obvious logs → Round 3-4 deeper → Round 5+ alternative angles\n\n"
			"ACTIONS: ADD/REMOVE/MODIFY/RELOCATE/ALTERNATIVE\n\n"
			"EXAMPLE:\n"
			"If history shows 'Added log at line 15 for count, but NPE persists':\n"
			"✓ GOOD: 'ADD log for METHOD CALL result at line 14 (before count used) - HIGH'\n"
			"✗ BAD: 'ADD log for variable count at line 15' (already tried!)\n\n"
			"If stuck or sufficient: 'No improvements needed.' or 'Try different debugging approach.'"
		)
	)


class LogSufficientEvaluator(BaseDspy):
	def _post_init(self, **kwargs):
		self.applier = LogInstructionApplier()
		self.evaluation_history = []

	def evaluate_log_sufficiency(
		self,
		original_code_snippet,
		applied_instructions,
		runtime_logs,
		execution_outcome,
		max_llm_retries=3,
	):
		numbered_code = self.applier.add_line_numbers(original_code_snippet)
		instructions_str = self._format_instructions_for_llm(applied_instructions)

		use_history = len(self.evaluation_history) > 0
		signature = self._select_signature(use_history)

		with self.use_model():
			evaluator = dspy.ChainOfThought(signature)

			for attempt in range(max_llm_retries):
				try:
					inputs = {
						"original_code_snippet": numbered_code,
						"applied_logging_instructions": instructions_str,
						"runtime_logs": runtime_logs,
						"execution_outcome": execution_outcome,
					}

					if use_history:
						inputs["evaluation_history"] = self._build_evaluation_history_summary()

					result = evaluator(**inputs)

					is_sufficient = str(result.is_sufficient).lower() == "true"
					suggestions_text = result.improvement_suggestions.strip()

					self._add_to_history(
						is_sufficient=is_sufficient,
						analysis=result.analysis,
						suggestions_text=suggestions_text,
						execution_outcome=execution_outcome,
						runtime_logs=runtime_logs,
					)

					evaluation_report = {
						"round": len(self.evaluation_history),
						"is_sufficient": is_sufficient,
						"suggestions_text": suggestions_text,
						"used_history": use_history,
					}

					return is_sufficient, result.analysis, suggestions_text, evaluation_report

				except Exception as e:
					print(f"❌ Log evaluation attempt {attempt + 1} failed: {e}")
					if attempt == max_llm_retries - 1:
						raise RuntimeError(f"Log evaluation failed after {max_llm_retries} attempts") from e

		raise RuntimeError("Max LLM retries exceeded for log evaluation.")

	def _select_signature(self, use_history):
		if use_history:
			return LogSufficiencyEvaluatorWithHistorySign
		else:
			return LogSufficiencyEvaluatorSign

	def _add_to_history(
		self, is_sufficient, analysis, suggestions_text, execution_outcome, runtime_logs
	):
		self.evaluation_history.append(
			{
				"round": len(self.evaluation_history) + 1,
				"is_sufficient": is_sufficient,
				"suggestions_text": suggestions_text,
				"analysis": analysis[:500],
				"execution_outcome_type": self._classify_outcome(execution_outcome),
				"runtime_logs_length": len(runtime_logs),
			}
		)

	def _classify_outcome(self, execution_outcome):
		outcome_upper = execution_outcome.upper()

		if "COMPILATION ERROR" in outcome_upper:
			return "compile_failed"
		elif "RUNTIME EXCEPTION" in outcome_upper or "EXCEPTION" in outcome_upper:
			return "runtime_error"
		elif "TIMEOUT" in outcome_upper:
			return "test_timeout"
		elif "FATAL ERROR" in outcome_upper:
			return "fatal_error"
		elif (
			"✓ EXECUTION COMPLETED" in outcome_upper or "✓ COMPILATION SUCCESSFUL" in outcome_upper
		):
			return "success"
		else:
			return "unknown"

	def _format_instructions_for_llm(self, instructions):
		return json.dumps(instructions, indent=2)

	def _build_evaluation_history_summary(self):
		if not self.evaluation_history:
			return "No previous evaluation rounds."

		lines = [f"Total evaluation rounds: {len(self.evaluation_history)}"]

		sufficient_count = sum(1 for r in self.evaluation_history if r["is_sufficient"])
		lines.append(
			f"Sufficient logs achieved: {sufficient_count}/{len(self.evaluation_history)} times"
		)

		lines.append("\nRecent evaluation rounds:")
		for record in self.evaluation_history[-3:]:
			round_num = record["round"]
			is_sufficient = record["is_sufficient"]
			outcome_type = record["execution_outcome_type"]

			status = "✓ Sufficient" if is_sufficient else "✗ Insufficient"
			lines.append(f"  Round {round_num}: {status} | Outcome: {outcome_type}")

			suggestions = record.get("suggestions_text", "")
			if suggestions and suggestions != "No improvements needed.":
				suggestion_lines = suggestions.split("\n")[:2]
				for sugg in suggestion_lines:
					if sugg.strip():
						lines.append(f"    Suggested: {sugg.strip()[:80]}...")

		if len(self.evaluation_history) >= 3:
			last_3_sufficient = [r["is_sufficient"] for r in self.evaluation_history[-3:]]
			if not any(last_3_sufficient):
				lines.append(
					"\n⚠️  WARNING: Logs have been insufficient for 3+ rounds. Consider a different strategy."
				)

			last_3_suggestions = [
				r.get("suggestions_text", "") for r in self.evaluation_history[-3:]
			]
			if self._has_repeated_suggestions(last_3_suggestions):
				lines.append("⚠️  WARNING: Similar suggestions repeated. Are we stuck?")

		lines.append(
			"\n💡 TIP: Learn from previous rounds. If past suggestions didn't help, try a different approach."
		)

		return "\n".join(lines)

	def _has_repeated_suggestions(self, suggestions_list):
		if len(suggestions_list) < 2:
			return False

		for i in range(len(suggestions_list) - 1):
			if self._text_similarity(suggestions_list[i], suggestions_list[i + 1]) > 0.7:
				return True
		return False

	def should_early_stop(self):
		if len(self.evaluation_history) < 3:
			return False, None

		last_3 = self.evaluation_history[-3:]

		if not any(r["is_sufficient"] for r in last_3):
			return True, "Logs insufficient for 3+ consecutive rounds"

		last_3_suggestions = [r.get("suggestions_text", "") for r in last_3]
		if self._has_repeated_suggestions(last_3_suggestions):
			return True, "Stuck in feedback loop - repeated suggestions"

		if len(self.evaluation_history) >= 2:
			last_2_analyses = [r.get("analysis", "")[:200] for r in self.evaluation_history[-2:]]
			if last_2_analyses[0] and last_2_analyses[1]:
				similarity = self._text_similarity(last_2_analyses[0], last_2_analyses[1])
				if similarity > 0.8:
					return True, "Repeated similar analysis - likely stuck"

		return False, None

	def _text_similarity(self, text1, text2):
		words1 = set(text1.lower().split())
		words2 = set(text2.lower().split())

		if not words1 or not words2:
			return 0.0

		intersection = len(words1 & words2)
		union = len(words1 | words2)

		return intersection / union if union > 0 else 0.0

	def get_evaluation_summary(self):
		if not self.evaluation_history:
			return {"total_rounds": 0, "sufficient_count": 0, "history": []}

		sufficient_count = sum(1 for r in self.evaluation_history if r["is_sufficient"])

		return {
			"total_rounds": len(self.evaluation_history),
			"sufficient_count": sufficient_count,
			"success_rate": sufficient_count / len(self.evaluation_history),
			"history": self.evaluation_history,
			"outcome_distribution": self._get_outcome_distribution(),
		}

	def _get_outcome_distribution(self):
		distribution = {}
		for record in self.evaluation_history:
			outcome_type = record["execution_outcome_type"]
			distribution[outcome_type] = distribution.get(outcome_type, 0) + 1
		return distribution

	def reset_history(self):
		self.evaluation_history = []
