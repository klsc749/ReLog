from __future__ import annotations

from typing import Optional

import tree_sitter_java as tsjava
from tree_sitter import Language, Node, Parser

from .java_signature_extractor import get_function_signature_from_node


class JavaPatcher:
	def __init__(self):
		self.java_language = Language(tsjava.language())
		self.parser = Parser(self.java_language)

	def _normalize_signature(self, signature: str) -> str:
		import re

		return re.sub(r"\s+", "", signature)

	def _find_method_node(self, java_code: str, target_signature: str) -> Optional[Node]:
		java_code_bytes = java_code.encode("utf-8")
		tree = self.parser.parse(java_code_bytes)
		root = tree.root_node
		normalized_target = self._normalize_signature(target_signature)
		stack = [root]
		while stack:
			node = stack.pop()
			if node.type in ["method_declaration", "constructor_declaration"]:
				node_signature = get_function_signature_from_node(
					node, java_code_bytes, include_annotations=False
				)
				if self._normalize_signature(node_signature) == normalized_target:
					return node
			for child in reversed(node.children):
				stack.append(child)
		return None

	def patch_method(self, java_code: str, method_signature: str, new_method_code: str) -> str:
		target_node = self._find_method_node(java_code, method_signature)
		if not target_node:
			raise ValueError(f"Method not found with signature: {method_signature}")
		start_byte = target_node.start_byte
		end_byte = target_node.end_byte
		original_bytes = java_code.encode("utf-8")
		new_bytes = new_method_code.encode("utf-8")
		patched_bytes = original_bytes[:start_byte] + new_bytes + original_bytes[end_byte:]
		try:
			return patched_bytes.decode("utf-8")
		except UnicodeDecodeError:
			return patched_bytes.decode("utf-8", errors="replace")
