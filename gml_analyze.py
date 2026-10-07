"""GML source analysis: strip comments/strings, extract defs/calls, metrics."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

DEF_RE = re.compile(r"\bfunction\s+([A-Za-z_]\w*)\s*\(")
CALL_RE = re.compile(r"\b([A-Za-z_]\w*)\s*\(")
IDENT_START = re.compile(r"[A-Za-z_]")


@dataclass
class Unit:
    name: str
    file: str
    line: int
    kind: str  # "function" | "object_event"
    lines: int
    code_lines: int


def strip_comments_and_strings(source: str) -> str:
    """Blank comments and string contents; preserve newlines and other code."""
    out: list[str] = []
    i = 0
    n = len(source)
    state = "code"  # code | line_comment | block_comment | dstring | sstring

    while i < n:
        ch = source[i]
        nxt = source[i + 1] if i + 1 < n else ""

        if state == "code":
            if ch == "/" and nxt == "/":
                out.append("  ")
                i += 2
                state = "line_comment"
                continue
            if ch == "/" and nxt == "*":
                out.append("  ")
                i += 2
                state = "block_comment"
                continue
            if ch == '"':
                out.append(" ")
                i += 1
                state = "dstring"
                continue
            if ch == "'":
                out.append(" ")
                i += 1
                state = "sstring"
                continue
            out.append(ch)
            i += 1
            continue

        if state == "line_comment":
            if ch == "\n":
                out.append("\n")
                state = "code"
            else:
                out.append(" ")
            i += 1
            continue

        if state == "block_comment":
            if ch == "*" and nxt == "/":
                out.append("  ")
                i += 2
                state = "code"
                continue
            out.append("\n" if ch == "\n" else " ")
            i += 1
            continue

        if state in ("dstring", "sstring"):
            quote = '"' if state == "dstring" else "'"
            if ch == "\\":
                out.append("  ")
                i += 2 if i + 1 < n else 1
                continue
            if ch == quote:
                out.append(" ")
                i += 1
                state = "code"
                continue
            out.append("\n" if ch == "\n" else " ")
            i += 1
            continue

    return "".join(out)


def discover_gml_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.gml") if p.is_file())


def object_event_name(path: Path, root: Path) -> str | None:
    try:
        rel = path.relative_to(root)
    except ValueError:
        return None
    parts = rel.parts
    if len(parts) >= 3 and parts[0] == "objects" and path.suffix == ".gml":
        return f"{parts[-2]}:{path.stem}"
    return None


def _line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def _code_line_count(stripped_lines: list[str], start: int, end: int) -> int:
    """1-based inclusive line range → count of non-whitespace lines."""
    count = 0
    for lineno in range(start, end + 1):
        if lineno < 1 or lineno > len(stripped_lines):
            continue
        if stripped_lines[lineno - 1].strip():
            count += 1
    return count


def analyze_file(
    path: Path,
    root: Path,
    source: str,
    project_functions: set[str],
) -> tuple[list[Unit], Counter[tuple[str, str]]]:
    stripped = strip_comments_and_strings(source)
    stripped_lines = stripped.splitlines()
    if source.endswith("\n") and (not stripped_lines or stripped_lines[-1] != ""):
        # splitlines drops a trailing empty line; keep lengths aligned via enumerate below
        pass
    physical_lines = source.splitlines()
    n_physical = len(physical_lines)

    units: list[Unit] = []
    calls: Counter[tuple[str, str]] = Counter()

    event_name = object_event_name(path, root)
    rel_file = str(path.relative_to(root)).replace("\\", "/")

    # scope stack: (name, brace_depth_at_body_open, body_start_line, kind, header_line)
    scope_stack: list[tuple[str, int, int, str, int]] = []
    brace_depth = 0
    pending_def: tuple[str, int] | None = None  # name, header_line

    if event_name is not None:
        # Whole file is the synthetic caller's body.
        scope_stack.append((event_name, 0, 1, "object_event", 1))

    i = 0
    n = len(stripped)
    while i < n:
        ch = stripped[i]

        if ch == "{":
            if pending_def is not None:
                name, header_line = pending_def
                body_start = _line_of(stripped, i)
                brace_depth += 1
                scope_stack.append(
                    (name, brace_depth, body_start, "function", header_line)
                )
                pending_def = None
            else:
                brace_depth += 1
            i += 1
            continue

        if ch == "}":
            if scope_stack:
                name, open_depth, body_start, kind, header_line = scope_stack[-1]
                if kind == "function" and brace_depth == open_depth:
                    body_end = _line_of(stripped, i)
                    lines = max(0, body_end - body_start + 1)
                    code_lines = _code_line_count(stripped_lines, body_start, body_end)
                    units.append(
                        Unit(
                            name=name,
                            file=rel_file,
                            line=header_line,
                            kind=kind,
                            lines=lines,
                            code_lines=code_lines,
                        )
                    )
                    scope_stack.pop()
            brace_depth = max(0, brace_depth - 1)
            i += 1
            continue

        # Definition: function Name(
        if stripped.startswith("function", i) and (
            i == 0 or not (stripped[i - 1].isalnum() or stripped[i - 1] == "_")
        ):
            m = DEF_RE.match(stripped, i)
            if m:
                pending_def = (m.group(1), _line_of(stripped, i))
                i = m.end()
                continue

        # Call site: ident(  (definitions already consumed above)
        if IDENT_START.match(ch):
            m = CALL_RE.match(stripped, i)
            if m:
                callee = m.group(1)
                if callee in project_functions and scope_stack:
                    caller = scope_stack[-1][0]
                    calls[(caller, callee)] += 1
                i = m.end()
                continue

        i += 1

    # Close any unclosed function scopes at EOF (malformed source).
    eof_line = max(1, n_physical)
    while scope_stack:
        name, open_depth, body_start, kind, header_line = scope_stack.pop()
        if kind == "object_event":
            lines = n_physical
            code_lines = _code_line_count(stripped_lines, 1, n_physical)
            units.append(
                Unit(
                    name=name,
                    file=rel_file,
                    line=header_line,
                    kind=kind,
                    lines=lines,
                    code_lines=code_lines,
                )
            )
        else:
            body_end = eof_line
            lines = max(0, body_end - body_start + 1)
            code_lines = _code_line_count(stripped_lines, body_start, body_end)
            units.append(
                Unit(
                    name=name,
                    file=rel_file,
                    line=header_line,
                    kind=kind,
                    lines=lines,
                    code_lines=code_lines,
                )
            )

    return units, calls


def collect_project_functions(root: Path, files: list[Path]) -> set[str]:
    names: set[str] = set()
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        stripped = strip_comments_and_strings(text)
        for m in DEF_RE.finditer(stripped):
            names.add(m.group(1))
    return names


def unit_to_dict(unit: Unit) -> dict:
    return asdict(unit)
