import json
import os
from pathlib import Path


class LogInstructionApplier:
	@staticmethod
	def add_line_numbers(code_snippet):
		lines = code_snippet.split("\n")
		numbered = []
		for i, line in enumerate(lines, start=1):
			numbered.append(f"{i:4d} | {line}")
		return "\n".join(numbered)

	@staticmethod
	def parse_instructions(instructions_str):
		if isinstance(instructions_str, list):
			instructions = instructions_str
		else:
			instructions_str = instructions_str.strip()
			if instructions_str.startswith("```"):
				instructions_str = "\n".join(instructions_str.splitlines()[1:-1])
			instructions = json.loads(instructions_str)
		if not isinstance(instructions, list):
			raise ValueError("Logging instructions must be a JSON array")
		for i, inst in enumerate(instructions):
			if not isinstance(inst, dict):
				raise ValueError(f"Instruction {i + 1} must be an object")
			missing = [key for key in ["line_number", "position", "log_statement"] if key not in inst]
			if missing:
				raise ValueError(f"Instruction {i + 1} missing required fields: {missing}")
			if type(inst["line_number"]) is not int:
				raise ValueError(f"Instruction {i + 1} line_number must be an integer")
			if inst["position"] not in ["before", "after"]:
				raise ValueError(f"Instruction {i + 1} has invalid position: {inst['position']}")
			if not isinstance(inst["log_statement"], str):
				raise ValueError(f"Instruction {i + 1} log_statement must be a string")
		return instructions

	@staticmethod
	def apply_instructions(original_code, instructions):
		instructions = LogInstructionApplier.parse_instructions(instructions)
		lines = original_code.split("\n")
		original_line_count = len(lines)

		indexed_instructions = [
			{**inst, "_original_index": idx} for idx, inst in enumerate(instructions)
		]

		def sort_key(inst):
			return (
				-inst["line_number"],
				0 if inst["position"] == "after" else 1,
				-inst["_original_index"],
			)

		sorted_instructions = sorted(indexed_instructions, key=sort_key)

		application_report = {"total_instructions": len(instructions), "applied": [], "failed": []}

		for inst in sorted_instructions:
			line_num = inst["line_number"]
			position = inst["position"]
			log_stmt = inst["log_statement"]

			if line_num < 1 or line_num > original_line_count:
				raise ValueError(
					f"Invalid line number: {line_num} (code has {original_line_count} lines)"
				)

			original_line = lines[line_num - 1]
			indent = len(original_line) - len(original_line.lstrip())

			indented_log = " " * indent + log_stmt.strip()

			if position == "before":
				lines.insert(line_num - 1, indented_log)
			elif position == "after":
				lines.insert(line_num, indented_log)
			else:
				raise ValueError(f"Invalid position: {position}")

			application_report["applied"].append(
				{"line_number": line_num, "position": position, "log_statement": log_stmt}
			)

		instrumented_code = "\n".join(lines)

		print(f"\n✅ Applied {len(application_report['applied'])} instructions")

		return instrumented_code, application_report


def save_checkpoint(output_path, results):
	output_path = Path(output_path)
	temp_path = output_path.with_name(output_path.name + ".tmp")
	with temp_path.open("w", encoding="utf-8") as f:
		json.dump(results, f, indent=4, ensure_ascii=False)
	os.replace(temp_path, output_path)
