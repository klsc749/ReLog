from typing import Optional

import dspy

from ...base_dspy import BaseDspy


class VerifyRepairCode(dspy.Signature):
	buggy_code: str = dspy.InputField(desc="The original code snippet that contains the bug")

	bug_description: str = dspy.InputField(
		desc="Description of the bug present in the original code"
	)

	repaired_code: str = dspy.InputField(
		desc="The code snippet after applying the repair to fix the bug"
	)

	ground_truth_repair_code: str = dspy.InputField(
		desc="The reference correct repair code (ground truth)"
	)

	is_correct: bool = dspy.OutputField(
		desc=(
			"Determine if the repaired code correctly fixes the bug by comparing with ground truth:\n"
			"1. Bug resolution:\n"
			"   - The specific issue described in bug_description is fixed\n"
			"   - The repair approach is semantically equivalent to ground truth\n"
			"2. Semantic equivalence with ground truth:\n"
			"   - The repaired code achieves the same fix as ground truth\n"
			"   - Implementation may differ but the outcome is the same\n"
			"   - Example: 'if (x == null)' is equivalent to 'if (null == x)'\n"
			"3. No new bugs:\n"
			"   - The repair doesn't introduce new issues\n"
			"   - Edge cases are handled correctly\n"
			"4. Functionality preserved:\n"
			"   - Original intended behavior is maintained\n"
			"   - Logic flow remains correct\n"
			"Return True if the repair semantically matches ground truth and fixes the bug."
		)
	)

	confidence: float = dspy.OutputField(
		desc=(
			"Confidence score from 0.0 to 1.0 based on match with ground truth:\n"
			"- 0.9-1.0: Excellent - semantically identical to ground truth\n"
			"- 0.7-0.8: Good - achieves same fix with minor differences\n"
			"- 0.5-0.6: Acceptable - fixes bug but approach differs from ground truth\n"
			"- 0.3-0.4: Questionable - partially correct but significant differences\n"
			"- 0.0-0.2: Incorrect - doesn't match ground truth or bug remains"
		)
	)

	explanation: str = dspy.OutputField(
		desc=(
			"Explain the verification result in 2-3 sentences:\n"
			"- If correct: explain how the repair matches ground truth (even if implementation differs)\n"
			"- If incorrect: explain differences from ground truth or remaining bugs\n"
			"- Justify the confidence score by comparing specific code changes\n"
			"Be specific and quote relevant code snippets from both repaired and ground truth code."
		)
	)


class CodeRepairVerifier(BaseDspy):
	def _post_init(self, **kwargs):
		self.verify_signature = VerifyRepairCode

	def verify(
		self,
		buggy_code: str,
		bug_description: str,
		repaired_code: str,
		ground_truth_repair_code: str,
		max_tries: int = 3,
	) -> Optional[dict]:
		with self.use_model():
			verifier = dspy.ChainOfThought(self.verify_signature)

			for attempt in range(max_tries):
				try:
					result = verifier(
						buggy_code=buggy_code,
						bug_description=bug_description,
						repaired_code=repaired_code,
						ground_truth_repair_code=ground_truth_repair_code,
					)
					return {
						"is_correct": result.is_correct,
						"confidence": result.confidence,
						"explanation": result.explanation,
					}
				except Exception as e:
					print(f"Verification attempt {attempt + 1}/{max_tries} failed: {e}")
					if attempt == max_tries - 1:
						raise RuntimeError(f"Repair verification failed after {max_tries} attempts") from e

			print(f"All {max_tries} verification attempts failed.")
			return None
