"""Minimal YAML-compatible fallback for the LLT verification scripts.

This module intentionally supports only the small surface area used in this
workspace: `dump`, `safe_dump`, and `safe_load`.

The parser is intentionally conservative. It supports the common YAML shapes
used by this skill bundle and by simple dictionary files:
- mappings
- lists
- nested mappings/lists via indentation
- quoted and unquoted scalars
"""

from __future__ import annotations

import ast
import json
from typing import Any, Iterable, List, Tuple, TextIO


def _parse_scalar(token: str) -> Any:
    token = token.strip()
    if token == "" or token in {"null", "Null", "NULL", "~"}:
        return None
    if token in {"true", "True", "TRUE"}:
        return True
    if token in {"false", "False", "FALSE"}:
        return False
    if (token.startswith('"') and token.endswith('"')) or (
        token.startswith("'") and token.endswith("'")
    ):
        return token[1:-1]
    try:
        if "." in token:
            return float(token)
        return int(token)
    except ValueError:
        pass
    try:
        return ast.literal_eval(token)
    except Exception:
        return token


def _strip_comment(line: str) -> str:
    if "#" not in line:
        return line
    in_quote = None
    for idx, ch in enumerate(line):
        if ch in {"'", '"'}:
            if in_quote == ch:
                in_quote = None
            elif in_quote is None:
                in_quote = ch
        elif ch == "#" and in_quote is None:
            return line[:idx]
    return line


def _preprocess(text: str) -> List[Tuple[int, str]]:
    result: List[Tuple[int, str]] = []
    for raw_line in text.splitlines():
        line = _strip_comment(raw_line.rstrip("\n")).rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        result.append((indent, line.strip()))
    return result


def _parse_block(lines: List[Tuple[int, str]], start: int, base_indent: int):
    if start >= len(lines):
        return None, start

    indent, text = lines[start]
    if text.startswith("- "):
        items = []
        idx = start
        while idx < len(lines):
            indent, text = lines[idx]
            if indent < base_indent or not text.startswith("- "):
                break

            item_text = text[2:].strip()
            idx += 1

            if item_text == "":
                nested, idx = _parse_block(lines, idx, indent + 2)
                items.append(nested)
                continue

            if ":" in item_text:
                key, value = item_text.split(":", 1)
                item = {key.strip(): _parse_scalar(value)}
                if idx < len(lines) and lines[idx][0] > indent:
                    nested, idx = _parse_block(lines, idx, indent + 2)
                    if isinstance(nested, dict):
                        item.update(nested)
                    elif nested is not None:
                        item[key.strip()] = nested
                items.append(item)
                continue

            items.append(_parse_scalar(item_text))
            if idx < len(lines) and lines[idx][0] > indent:
                nested, idx = _parse_block(lines, idx, indent + 2)
                items[-1] = nested

        return items, idx

    mapping = {}
    idx = start
    while idx < len(lines):
        indent, text = lines[idx]
        if indent < base_indent:
            break
        if text.startswith("- ") and indent == base_indent:
            nested, idx = _parse_block(lines, idx, base_indent)
            return nested, idx
        if ":" not in text:
            idx += 1
            continue

        key, value = text.split(":", 1)
        key = key.strip()
        value = value.strip()
        idx += 1

        if value:
            mapping[key] = _parse_scalar(value)
            continue

        if idx < len(lines) and lines[idx][0] > indent:
            nested, idx = _parse_block(lines, idx, indent + 2)
            mapping[key] = nested
        else:
            mapping[key] = None

    return mapping, idx


def safe_load(stream: Any) -> Any:
    if hasattr(stream, "read"):
        text = stream.read()
    else:
        text = str(stream)
    text = text.strip()
    if not text:
        return None

    # Fast path for JSON-compatible YAML.
    try:
        return json.loads(text)
    except Exception:
        pass

    lines = _preprocess(text)
    if not lines:
        return None
    parsed, _ = _parse_block(lines, 0, lines[0][0])
    return parsed


def dump(
    data: Any,
    stream: TextIO | None = None,
    default_flow_style: bool = False,
    sort_keys: bool = False,
    **_: Any,
) -> str | None:
    rendered = json.dumps(data, indent=2, sort_keys=sort_keys)
    if stream is not None:
        stream.write(rendered)
        return None
    return rendered


def safe_dump(
    data: Any,
    stream: TextIO | None = None,
    default_flow_style: bool = False,
    sort_keys: bool = False,
    **kwargs: Any,
) -> str | None:
    return dump(
        data,
        stream=stream,
        default_flow_style=default_flow_style,
        sort_keys=sort_keys,
        **kwargs,
    )
