from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from ..config import MAX_CHUNK_CHARS

try:
    from tree_sitter_language_pack import get_parser  # type: ignore
except Exception:  # pragma: no cover - optional at import time
    get_parser = None


@dataclass
class SymbolRecord:
    name: str
    kind: str
    start_line: int
    end_line: int
    language: str
    signature: str = ""
    qualified_name: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChunkRecord:
    start_line: int
    end_line: int
    language: str
    kind: str
    name: str
    text: str
    symbol_index: int | None = None


@dataclass
class ParseResult:
    language: str
    symbols: list[SymbolRecord]
    chunks: list[ChunkRecord]
    metadata: dict[str, Any]


LANGUAGE_BY_SUFFIX = {
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".java": "java",
    ".feature": "karate",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".properties": "properties",
    ".xml": "xml",
    ".gradle": "gradle",
    ".kts": "kotlin",
    ".toml": "toml",
    ".md": "markdown",
    ".sql": "sql",
    ".tf": "terraform",
    ".tfvars": "terraform",
}

TS_SYMBOL_TYPES = {
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
        "type_alias_declaration": "type",
        "enum_declaration": "enum",
        "generator_function_declaration": "function",
    },
    "tsx": {
        "function_declaration": "function",
        "class_declaration": "class",
        "method_definition": "method",
        "interface_declaration": "interface",
        "type_alias_declaration": "type",
        "enum_declaration": "enum",
    },
    "java": {
        "class_declaration": "class",
        "interface_declaration": "interface",
        "enum_declaration": "enum",
        "record_declaration": "record",
        "method_declaration": "method",
        "constructor_declaration": "constructor",
    },
}

_NAME_NODE_TYPES = {
    "identifier", "type_identifier", "property_identifier", "field_identifier",
}


def language_for_path(path: Path | str) -> str:
    return LANGUAGE_BY_SUFFIX.get(Path(path).suffix.lower(), "text")


def _line_text(lines: list[str], start_line: int, end_line: int) -> str:
    start = max(1, start_line)
    end = min(len(lines), max(start, end_line))
    text = "".join(lines[start - 1 : end])
    if len(text) > MAX_CHUNK_CHARS:
        text = text[:MAX_CHUNK_CHARS] + "\n/* ... chunk truncated ... */\n"
    return text


def _node_name(node, source: bytes) -> str:
    # Prefer the named 'name' field where grammars expose it.
    try:
        child = node.child_by_field_name("name")
        if child is not None:
            return source[child.start_byte : child.end_byte].decode("utf-8", errors="replace")
    except Exception:
        pass
    try:
        for child in node.children:
            if child.type in _NAME_NODE_TYPES:
                return source[child.start_byte : child.end_byte].decode("utf-8", errors="replace")
    except Exception:
        pass
    return ""


def _walk(node) -> Iterable[Any]:
    stack = [node]
    while stack:
        cur = stack.pop()
        yield cur
        try:
            stack.extend(reversed(cur.children))
        except Exception:
            continue


def _tree_sitter_symbols(text: str, language: str) -> list[SymbolRecord]:
    if get_parser is None or language not in TS_SYMBOL_TYPES:
        return []
    source = text.encode("utf-8", errors="replace")
    try:
        parser = get_parser(language)
        tree = parser.parse(source)
        root = tree.root_node
    except Exception:
        return []

    symbols: list[SymbolRecord] = []
    for node in _walk(root):
        kind = TS_SYMBOL_TYPES[language].get(getattr(node, "type", ""))
        if not kind:
            continue
        name = _node_name(node, source).strip()
        if not name:
            continue
        start_line = int(node.start_point[0]) + 1
        end_line = int(node.end_point[0]) + 1
        snippet = source[node.start_byte : min(node.end_byte, node.start_byte + 400)].decode("utf-8", errors="replace")
        signature = snippet.split("{", 1)[0].strip().replace("\n", " ")[:400]
        symbols.append(
            SymbolRecord(
                name=name,
                kind=kind,
                start_line=start_line,
                end_line=end_line,
                language=language,
                signature=signature,
            )
        )
    return symbols


_JS_ARROW_RE = re.compile(
    r"(?m)^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*(?::[^=\n]+)?=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>"
)
_JS_IMPORT_RE = re.compile(r"(?m)^\s*import\s+(.*?)\s+from\s+['\"]([^'\"]+)['\"]")
_JS_REQUIRE_RE = re.compile(r"require\(\s*['\"]([^'\"]+)['\"]\s*\)")
_ENV_RE = re.compile(r"\bprocess\.env\.([A-Z0-9_]+)\b")
_AWS_CLIENT_RE = re.compile(r"\b([A-Za-z0-9_]+Client|[A-Za-z0-9_]+Command)\b")
_LAMBDA_HANDLER_RE = re.compile(
    r"^\s*(?:export\s+)?(?:const|let|var)\s+handler\s*=|^\s*export\s+(?:async\s+)?function\s+handler\b|\bexports\.handler\s*=",
    re.MULTILINE,
)
_REACT_HOOK_RE = re.compile(r"\b(use[A-Z][A-Za-z0-9_]*)\s*\(")
_PLAYWRIGHT_TEST_RE = re.compile(r"\btest(?:\.(?:only|skip|fixme))?\s*\(\s*['\"]([^'\"]+)['\"]")
_PLAYWRIGHT_DESCRIBE_RE = re.compile(r"\btest\.describe\s*\(\s*['\"]([^'\"]+)['\"]")
_PLAYWRIGHT_FIXTURE_RE = re.compile(r"\btest\.extend\s*[<(]")
_PLAYWRIGHT_ACTION_RE = re.compile(r"\b(?:page|context|request)\.(goto|locator|getByRole|getByText|getByTestId|click|fill|route|storageState|newPage|newContext)\b")

_JAVA_IMPORT_RE = re.compile(r"(?m)^\s*import\s+([\w.*]+)\s*;")
_JAVA_PACKAGE_RE = re.compile(r"(?m)^\s*package\s+([\w.]+)\s*;")
_JAVA_ANNOT_RE = re.compile(r"(?m)^\s*@([A-Za-z_][\w.]*)")

_KARATE_SCENARIO_RE = re.compile(r"(?m)^\s*(Scenario(?: Outline)?):\s*(.+?)\s*$")
_KARATE_TAG_RE = re.compile(r"(?m)^\s*(@[^\n]+)$")
_KARATE_CALL_RE = re.compile(r"\b(?:call\s+)?read\(\s*['\"]([^'\"]+)['\"]\s*\)|\bJava\.type\(\s*['\"]([^'\"]+)['\"]\s*\)")


def _brace_end_line(lines: list[str], start_line: int, max_scan: int = 500) -> int:
    """Best-effort brace matching for regex-discovered JS/Java symbols."""
    depth = 0
    saw_open = False
    quote: str | None = None
    escape = False
    end_limit = min(len(lines), start_line - 1 + max_scan)
    for idx in range(start_line - 1, end_limit):
        line = lines[idx]
        i = 0
        while i < len(line):
            ch = line[i]
            if escape:
                escape = False
                i += 1
                continue
            if quote:
                if ch == "\\":
                    escape = True
                elif ch == quote:
                    quote = None
                i += 1
                continue
            if ch in {'"', "'", "`"}:
                quote = ch
            elif ch == "{":
                depth += 1
                saw_open = True
            elif ch == "}":
                depth -= 1
                if saw_open and depth <= 0:
                    return idx + 1
            i += 1
    return min(len(lines), start_line + 80)


def _add_regex_symbols(text: str, lines: list[str], language: str, symbols: list[SymbolRecord]) -> None:
    existing = {(s.name, s.start_line) for s in symbols}
    if language in {"javascript", "typescript", "tsx"}:
        for match in _JS_ARROW_RE.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            name = match.group(1)
            if (name, line) in existing:
                continue
            end = _brace_end_line(lines, line)
            kind = "react_component" if name[:1].isupper() else "function"
            if name.startswith("use") and len(name) > 3 and name[3:4].isupper():
                kind = "react_hook"
            symbols.append(SymbolRecord(name, kind, line, end, language, lines[line - 1].strip()[:400]))

        # Detect CommonJS and direct exports that tree-sitter may not elevate to named declarations.
        for match in re.finditer(r"(?m)^\s*(?:module\.)?exports\.([A-Za-z_$][\w$]*)\s*=", text):
            line = text.count("\n", 0, match.start()) + 1
            name = match.group(1)
            if (name, line) not in existing:
                symbols.append(SymbolRecord(name, "export", line, _brace_end_line(lines, line), language, lines[line - 1].strip()[:400]))

    if language == "java" and not symbols:
        # Fallback for environments where a tree-sitter grammar is unavailable.
        class_re = re.compile(r"(?m)^\s*(?:public\s+|protected\s+|private\s+|abstract\s+|final\s+|static\s+)*(class|interface|enum|record)\s+([A-Za-z_][\w]*)")
        for match in class_re.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            symbols.append(SymbolRecord(match.group(2), match.group(1), line, _brace_end_line(lines, line), language, lines[line - 1].strip()[:400]))
        method_re = re.compile(r"(?m)^\s*(?:@[\w.()\"'=, ]+\s*)*(?:public|protected|private|static|final|synchronized|abstract|native|default|\s)+[\w<>,.?\[\] ]+\s+([A-Za-z_][\w]*)\s*\([^;{}]*\)\s*(?:throws [^{]+)?\{")
        for match in method_re.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            name = match.group(1)
            symbols.append(SymbolRecord(name, "method", line, _brace_end_line(lines, line), language, lines[line - 1].strip()[:400]))


def _karate_parse(text: str, lines: list[str]) -> tuple[list[SymbolRecord], dict[str, Any]]:
    symbols: list[SymbolRecord] = []
    scenario_matches = list(_KARATE_SCENARIO_RE.finditer(text))
    for i, match in enumerate(scenario_matches):
        start = text.count("\n", 0, match.start()) + 1
        end = (text.count("\n", 0, scenario_matches[i + 1].start()) if i + 1 < len(scenario_matches) else len(lines))
        symbols.append(SymbolRecord(match.group(2).strip(), match.group(1).lower().replace(" ", "_"), start, max(start, end), "karate", match.group(0).strip()))
    calls: list[str] = []
    java_types: list[str] = []
    for m in _KARATE_CALL_RE.finditer(text):
        if m.group(1):
            calls.append(m.group(1))
        if m.group(2):
            java_types.append(m.group(2))
    metadata = {
        "tags": [m.group(1).strip() for m in _KARATE_TAG_RE.finditer(text)],
        "feature_calls": sorted(set(calls)),
        "java_types": sorted(set(java_types)),
    }
    return symbols, metadata


def _special_metadata(text: str, language: str, path: str) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    if language in {"javascript", "typescript", "tsx"}:
        imports = [{"what": m.group(1).strip(), "from": m.group(2)} for m in _JS_IMPORT_RE.finditer(text)]
        requires = [m.group(1) for m in _JS_REQUIRE_RE.finditer(text)]
        env = sorted(set(_ENV_RE.findall(text)))
        aws_names = sorted(set(_AWS_CLIENT_RE.findall(text)))
        aws_packages = sorted({entry["from"] for entry in imports if entry["from"].startswith("@aws-sdk/") or entry["from"] == "aws-sdk"})
        hooks = sorted(set(_REACT_HOOK_RE.findall(text)))
        playwright_import = any(entry["from"] == "@playwright/test" for entry in imports)
        metadata.update(
            {
                "imports": imports[:200],
                "requires": requires[:200],
                "environment_variables": env,
                "aws_sdk_packages": aws_packages,
                "aws_sdk_symbols": aws_names[:200],
                "react_hooks": hooks[:100],
                "is_lambda_handler": bool(_LAMBDA_HANDLER_RE.search(text)),
                "lambda_backend_hint": "lambdaBackend" in Path(path).parts,
                "is_playwright": playwright_import or "playwright.config" in Path(path).name,
                "playwright_tests": _PLAYWRIGHT_TEST_RE.findall(text)[:200],
                "playwright_describes": _PLAYWRIGHT_DESCRIBE_RE.findall(text)[:100],
                "playwright_fixture_extension": bool(_PLAYWRIGHT_FIXTURE_RE.search(text)),
                "playwright_actions": sorted(set(_PLAYWRIGHT_ACTION_RE.findall(text))),
            }
        )
    elif language == "java":
        package = _JAVA_PACKAGE_RE.search(text)
        imports = _JAVA_IMPORT_RE.findall(text)
        annotations = _JAVA_ANNOT_RE.findall(text)
        metadata.update(
            {
                "package": package.group(1) if package else "",
                "imports": imports[:300],
                "annotations": sorted(set(annotations))[:200],
                "spring": any(a.split(".")[-1] in {
                    "RestController", "Controller", "Service", "Repository", "Component",
                    "Configuration", "Bean", "RequestMapping", "GetMapping", "PostMapping",
                    "PutMapping", "PatchMapping", "DeleteMapping",
                } for a in annotations),
            }
        )
    return metadata


def _config_metadata(text: str, language: str, path: str) -> dict[str, Any]:
    name = Path(path).name
    if language == "json":
        try:
            obj = json.loads(text)
        except Exception:
            return {}
        if name == "package.json" and isinstance(obj, dict):
            return {
                "package_name": obj.get("name"),
                "scripts": obj.get("scripts", {}),
                "dependencies": obj.get("dependencies", {}),
                "devDependencies": obj.get("devDependencies", {}),
            }
        return {"top_level_keys": list(obj)[:100] if isinstance(obj, dict) else []}
    return {}


def _dedupe_symbols(symbols: list[SymbolRecord]) -> list[SymbolRecord]:
    out: list[SymbolRecord] = []
    seen: set[tuple[str, int, str]] = set()
    for s in sorted(symbols, key=lambda x: (x.start_line, x.end_line, x.name)):
        key = (s.name, s.start_line, s.kind)
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def _make_chunks(text: str, lines: list[str], language: str, symbols: list[SymbolRecord]) -> list[ChunkRecord]:
    chunks: list[ChunkRecord] = []
    # Symbol-level chunks are the highest-value retrieval unit.
    for idx, symbol in enumerate(symbols):
        if symbol.end_line < symbol.start_line:
            continue
        chunks.append(
            ChunkRecord(
                symbol.start_line,
                symbol.end_line,
                language,
                symbol.kind,
                symbol.name,
                _line_text(lines, symbol.start_line, symbol.end_line),
                idx,
            )
        )

    # Add bounded file-window chunks to preserve top-level glue/configuration and code not owned by symbols.
    window = 100
    overlap = 15
    total = len(lines)
    start = 1
    while start <= total:
        end = min(total, start + window - 1)
        chunk_text = _line_text(lines, start, end)
        if chunk_text.strip():
            chunks.append(ChunkRecord(start, end, language, "file_window", f"lines {start}-{end}", chunk_text, None))
        if end >= total:
            break
        start = max(start + 1, end - overlap + 1)

    # Avoid pathological chunk counts on huge generated-looking files.
    if len(chunks) > 500:
        chunks = chunks[:500]
    return chunks


def parse_source(path: str, text: str) -> ParseResult:
    language = language_for_path(path)
    lines = text.splitlines(keepends=True)
    if not lines:
        lines = [""]

    metadata: dict[str, Any] = {}
    symbols: list[SymbolRecord] = []

    if language == "karate":
        symbols, metadata = _karate_parse(text, lines)
    else:
        symbols = _tree_sitter_symbols(text, language)
        _add_regex_symbols(text, lines, language, symbols)
        metadata.update(_special_metadata(text, language, path))
        metadata.update(_config_metadata(text, language, path))
        if language in {"javascript", "typescript", "tsx"} and metadata.get("is_playwright"):
            for match in _PLAYWRIGHT_DESCRIBE_RE.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                symbols.append(SymbolRecord(match.group(1), "playwright_describe", line, _brace_end_line(lines, line), language, match.group(0)[:400]))
            for match in _PLAYWRIGHT_TEST_RE.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                symbols.append(SymbolRecord(match.group(1), "playwright_test", line, _brace_end_line(lines, line), language, match.group(0)[:400]))

    symbols = _dedupe_symbols(symbols)

    # Decorate known framework symbols.
    if language in {"javascript", "typescript", "tsx"}:
        for s in symbols:
            if s.name == "handler" and metadata.get("is_lambda_handler"):
                s.kind = "aws_lambda_handler"
                s.metadata["aws_sdk_packages"] = metadata.get("aws_sdk_packages", [])
                s.metadata["environment_variables"] = metadata.get("environment_variables", [])
            elif s.name[:1].isupper() and s.kind == "function" and (language == "tsx" or Path(path).suffix.lower() == ".jsx"):
                s.kind = "react_component"
            elif s.name.startswith("use") and len(s.name) > 3 and s.name[3:4].isupper():
                s.kind = "react_hook"
            elif metadata.get("is_playwright") and s.kind == "class" and s.name.endswith("Page"):
                s.kind = "playwright_page_object"
    elif language == "java":
        anns = metadata.get("annotations", [])
        framework_kinds = {
            "RestController": "spring_controller",
            "Controller": "spring_controller",
            "Service": "spring_service",
            "Repository": "spring_repository",
            "Configuration": "spring_configuration",
            "Component": "spring_component",
        }
        class_level = next((framework_kinds.get(a.split(".")[-1]) for a in anns if framework_kinds.get(a.split(".")[-1])), None)
        if class_level:
            for s in symbols:
                if s.kind in {"class", "interface", "record"}:
                    s.kind = class_level
                    break

    chunks = _make_chunks(text, lines, language, symbols)
    return ParseResult(language=language, symbols=symbols, chunks=chunks, metadata=metadata)
