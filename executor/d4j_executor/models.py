from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict


@dataclass
class InputData:
	defects4j_bug_num: int
	defects4j_project: str
	buggy_code_with_logging_code: str
	method_path: str = ""
	method_signature: str = ""
	test_method: str = ""

	@classmethod
	def from_dict(cls, data: Dict[str, Any]) -> "InputData":
		return cls(
			defects4j_bug_num=data["defects4j_bug_num"],
			defects4j_project=data["defects4j_project"],
			buggy_code_with_logging_code=data["buggy_code_with_logging_code"],
			method_path=str(data.get("method_path") or data.get("main_method_path") or ""),
			method_signature=str(data.get("method_signature") or data.get("main_method_signature") or ""),
			test_method=str(data.get("test_method") or ""),
		)

	def to_dict(self) -> Dict[str, Any]:
		return asdict(self)


@dataclass
class MetadataEntry:
	defects4j_bug_num: int
	defects4j_project: str
	main_method_path: str
	main_method_signature: str
	test_method: str

	@classmethod
	def from_dict(cls, data: Dict[str, Any]) -> "MetadataEntry":
		test_methods = data.get("test_methods", [])
		test_method = test_methods[0] if test_methods else ""
		return cls(
			defects4j_bug_num=data["defects4j_bug_num"],
			defects4j_project=data["defects4j_project"],
			main_method_path=data["main_method_path"],
			main_method_signature=data["main_method_signature"],
			test_method=test_method,
		)


@dataclass
class OutputData:
	buggy_code_runtime_logs: str
	status: str
	defects4j_logs: str
	message: str
	compilation_err_info: str = ""
	exception_stack_trace: str = ""

	def to_dict(self) -> Dict[str, Any]:
		return asdict(self)
