from __future__ import annotations

import re

import tree_sitter_java as tsjava
from tree_sitter import Language, Parser

JAVA_LANGUAGE = Language(tsjava.language())
parser = Parser(JAVA_LANGUAGE)


def _find_signature_start_byte(method_node, skip_annotations: bool = True) -> int:
	if not skip_annotations:
		return method_node.start_byte
	for child in method_node.children:
		if child.type == "modifiers":
			for mod_child in child.children:
				if "annotation" not in mod_child.type and "comment" not in mod_child.type:
					return mod_child.start_byte
			continue
		if "annotation" not in child.type and "comment" not in child.type:
			return child.start_byte
	return method_node.start_byte


def _find_signature_end_byte(method_node) -> int:
	for child in method_node.children:
		if child.type in ["block", "constructor_body"]:
			return child.start_byte
	return method_node.end_byte


def _normalize_signature(signature: str, remove_parameter_annotations: bool = True) -> str:
	signature = signature.strip()
	signature = re.sub(r"\s+", " ", signature)
	if remove_parameter_annotations:
		signature = re.sub(r"@\w+\s+", "", signature)
	return signature


def get_function_signature_from_node(method_node, source_code, include_annotations: bool = False) -> str:
	if method_node.type not in ["method_declaration", "constructor_declaration"]:
		return ""
	if isinstance(source_code, str):
		source_code = source_code.encode("utf8")
	start_byte = _find_signature_start_byte(
		method_node, skip_annotations=not include_annotations
	)
	end_byte = _find_signature_end_byte(method_node)
	signature_bytes = source_code[start_byte:end_byte]
	signature = signature_bytes.decode("utf8")
	return _normalize_signature(
		signature, remove_parameter_annotations=not include_annotations
	)
