"""Symbol (definition) extraction.

Primary path uses tree-sitter via ``tree-sitter-language-pack`` for accurate,
multi-language parsing. When the pack is unavailable, a grammar is missing, or a
parse fails, it degrades to the same regex heuristic RepoOperator has always
shipped — so symbol extraction is never *worse* than the previous behaviour.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Symbol:
    name: str
    kind: str
    line: int   # 1-based
    col: int    # 1-based


# ── tree-sitter availability (checked once) ─────────────────────────────────────
_PACK_AVAILABLE: bool | None = None
_PARSER_CACHE: dict[str, object] = {}


def tree_sitter_available() -> bool:
    global _PACK_AVAILABLE
    if _PACK_AVAILABLE is None:
        try:
            import tree_sitter_language_pack  # noqa: F401
            _PACK_AVAILABLE = True
        except Exception:
            _PACK_AVAILABLE = False
    return _PACK_AVAILABLE


def _get_parser(lang: str):
    if lang in _PARSER_CACHE:
        return _PARSER_CACHE[lang]
    parser = None
    try:
        from tree_sitter_language_pack import get_parser
        parser = get_parser(lang)
    except Exception:
        parser = None
    _PARSER_CACHE[lang] = parser
    return parser


# node-type → symbol kind, per language. Names come from the child field ``name``
# where the grammar exposes one, else the first identifier-ish child.
_NODE_KINDS: dict[str, dict[str, str]] = {
    "python": {
        "function_definition": "function",
        "class_definition": "class",
    },
    "javascript": {
        "function_declaration": "function",
        "class_declaration": "class",
        "method_definition": "method",
        "generator_function_declaration": "function",
    },
    "typescript": {
        "function_declaration": "function",
        "class_declaration": "class",
        "method_definition": "method",
        "interface_declaration": "interface",
        "enum_declaration": "enum",
        "type_alias_declaration": "type",
        "abstract_class_declaration": "class",
    },
    "tsx": {
        "function_declaration": "function",
        "class_declaration": "class",
        "method_definition": "method",
        "interface_declaration": "interface",
        "enum_declaration": "enum",
        "type_alias_declaration": "type",
        "abstract_class_declaration": "class",
    },
    "go": {
        "function_declaration": "function",
        "method_declaration": "method",
        "type_declaration": "type",
    },
    "rust": {
        "function_item": "function",
        "struct_item": "struct",
        "enum_item": "enum",
        "trait_item": "trait",
        "const_item": "const",
        "mod_item": "module",
    },
    "java": {
        "class_declaration": "class",
        "method_declaration": "method",
        "interface_declaration": "interface",
        "enum_declaration": "enum",
    },
    "ruby": {
        "method": "method",
        "class": "class",
        "module": "module",
        "singleton_method": "method",
    },
    "c": {"function_definition": "function", "struct_specifier": "struct"},
    "cpp": {"function_definition": "function", "class_specifier": "class", "struct_specifier": "struct"},
    "c_sharp": {"class_declaration": "class", "method_declaration": "method", "interface_declaration": "interface"},
    "kotlin": {"function_declaration": "function", "class_declaration": "class"},
    "swift": {"function_declaration": "function", "class_declaration": "class"},
}

_MAX_NODES = 200_000  # safety cap on tree walk


def _node_name(node, source: bytes) -> str | None:
    # Most grammars expose a ``name`` field.
    try:
        named = node.child_by_field_name("name")
    except Exception:
        named = None
    if named is not None:
        return source[named.start_byte:named.end_byte].decode("utf-8", "replace")
    # Fallback: first identifier-ish child.
    for child in getattr(node, "children", []) or []:
        if child.type in ("identifier", "type_identifier", "constant", "field_identifier", "name"):
            return source[child.start_byte:child.end_byte].decode("utf-8", "replace")
    return None


def _extract_tree_sitter(text: str, lang: str) -> list[Symbol] | None:
    kinds = _NODE_KINDS.get(lang)
    if not kinds:
        return None
    parser = _get_parser(lang)
    if parser is None:
        return None
    try:
        source = text.encode("utf-8", "replace")
        tree = parser.parse(source)
    except Exception:
        return None

    symbols: list[Symbol] = []
    visited = 0
    stack = [tree.root_node]
    while stack:
        if visited >= _MAX_NODES:
            break
        node = stack.pop()
        visited += 1
        kind = kinds.get(node.type)
        if kind:
            name = _node_name(node, source)
            if name:
                srow, scol = node.start_point
                symbols.append(Symbol(name=name, kind=kind, line=srow + 1, col=scol + 1))
        stack.extend(getattr(node, "children", []) or [])
    return symbols


# ── regex fallback (mirrors the long-standing find_file_candidates heuristic) ───
_DEF_RE = re.compile(
    r"\b(?P<kw>class|struct|interface|enum|trait|def|func|fn|function|module)\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
)
_KW_KIND = {
    "class": "class", "struct": "struct", "interface": "interface", "enum": "enum",
    "trait": "trait", "def": "function", "func": "function", "fn": "function",
    "function": "function", "module": "module",
}


def _extract_regex(text: str) -> list[Symbol]:
    symbols: list[Symbol] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        for match in _DEF_RE.finditer(line):
            symbols.append(
                Symbol(
                    name=match.group("name"),
                    kind=_KW_KIND.get(match.group("kw"), "symbol"),
                    line=line_no,
                    col=match.start("name") + 1,
                )
            )
    return symbols


def extract_symbols(text: str, lang: str) -> tuple[list[Symbol], str]:
    """Return (symbols, parse_mode) where parse_mode is 'tree_sitter' or 'regex'."""
    if tree_sitter_available():
        ts = _extract_tree_sitter(text, lang)
        if ts is not None:
            return ts, "tree_sitter"
    return _extract_regex(text), "regex"
