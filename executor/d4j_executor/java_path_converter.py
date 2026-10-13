from __future__ import annotations

import re
from pathlib import Path
from typing import Union


def file_path_to_class_path(file_path: str) -> str:
	if not file_path or not isinstance(file_path, str):
		return ""
	normalized = file_path.strip().replace("\\", "/")
	for ext in [".java", ".class"]:
		if normalized.endswith(ext):
			normalized = normalized[: -len(ext)]
			break
	patterns = [
		r"/src/main/java/(.+)$",
		r"/src/test/java/(.+)$",
		r"^src/main/java/(.+)$",
		r"^src/test/java/(.+)$",
		r"/src/main/(.+)$",
		r"/src/test/(.+)$",
		r"^src/main/(.+)$",
		r"^src/test/(.+)$",
		r"/java/(.+)$",
	]
	for pattern in patterns:
		match = re.search(pattern, normalized)
		if match:
			return match.group(1).replace("/", ".")
	for prefix in ["src/", "java/", "test/"]:
		if normalized.startswith(prefix):
			normalized = normalized[len(prefix) :]
	class_path = normalized.replace("/", ".")
	return ".".join(part for part in class_path.split(".") if part)


def class_path_to_file_path(
	class_path: str, project_root: Union[str, Path], file_extension: str = ".java"
) -> Path:
	if not class_path:
		raise ValueError("class_path cannot be empty")
	project_root = Path(project_root)
	if not project_root.exists():
		raise FileNotFoundError(f"project_root does not exist: {project_root}")
	parts = class_path.split(".")
	relative_path = "/".join(parts) + file_extension
	possible_source_dirs = [
		"src/main/java",
		"src/test/java",
		"src/java",
		"src",
		"gson/src/main/java",
		"",
	]
	for src_dir in possible_source_dirs:
		full_path = project_root / src_dir / relative_path if src_dir else project_root / relative_path
		if full_path.exists():
			return full_path
	tried_paths = [
		str(project_root / src_dir / relative_path) if src_dir else str(project_root / relative_path)
		for src_dir in possible_source_dirs
	]
	raise FileNotFoundError(
		f"Could not find file for class path: {class_path}\n"
		f"Project root: {project_root}\n"
		f"Tried the following paths:\n" + "\n".join(f"  - {p}" for p in tried_paths)
	)


to_class_path = file_path_to_class_path
to_file_path = class_path_to_file_path
