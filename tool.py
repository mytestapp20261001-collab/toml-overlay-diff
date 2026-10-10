#!/usr/bin/env python3
"""Offline, read-only audit. Python 3.12+, standard library only."""
import argparse
import json
import math
import re
import stat
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

MAX_BYTES = 8 * 1024 * 1024
MAX_RECORDS = 50000
MAX_FINDINGS = 100

class InputError(ValueError):
    """A safe, non-payload-bearing input error code."""

class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise InputError("invalid_arguments")

def read_text(path):
    p = Path(path)
    if not stat.S_ISREG(p.stat().st_mode):
        raise InputError("regular_file_required")
    with p.open("rb") as stream:
        data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise InputError("file_size_limit")
    return data.decode("utf-8")

def reject_constant(value):
    raise InputError("non_finite_json_number")

def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InputError("duplicate_json_member")
        result[key] = value
    return result

def parse_json(text):
    try:
        result = json.loads(text, object_pairs_hook=unique_pairs,
                            parse_float=Decimal, parse_constant=reject_constant)
    except InputError:
        raise
    except (ValueError, RecursionError, InvalidOperation):
        raise InputError("invalid_json") from None
    stack, nodes = [(result, 0)], 0
    while stack:
        value, depth = stack.pop()
        nodes += 1
        if depth > 128 or nodes > 200000:
            raise InputError("json_structure_limit")
        if isinstance(value, dict):
            stack.extend((v, depth + 1) for v in value.values())
        elif isinstance(value, list):
            stack.extend((v, depth + 1) for v in value)
    return result

class Report:
    def __init__(self, tool):
        self.tool, self.findings, self.count = tool, [], 0
    def add(self, code, **location):
        self.count += 1
        if len(self.findings) < MAX_FINDINGS:
            self.findings.append(dict(code=code, **location))
    def finish(self, **summary):
        return {"tool": self.tool, "status": "fail" if self.count else "pass",
                "summary": dict(summary, finding_count=self.count),
                "findings": self.findings,
                "findings_truncated": self.count > len(self.findings)}

def emit_main(run):
    try:
        result = run()
        code = 1 if result["status"] == "fail" else 0
    except InputError as exc:
        result, code = {"tool": TOOL, "status": "error", "error": str(exc)}, 2
    except (OSError, UnicodeError):
        result, code = {"tool": TOOL, "status": "error", "error": "unreadable_utf8_input"}, 2
    except (ValueError, RecursionError, InvalidOperation):
        result, code = {"tool": TOOL, "status": "error", "error": "invalid_input"}, 2
    print(json.dumps(result, ensure_ascii=True, sort_keys=True, indent=2, allow_nan=False))
    return code

TOOL = "toml-overlay-diff"

import tomllib

def parse_toml(text):
    try:
        result = tomllib.loads(text, parse_float=Decimal)
    except (tomllib.TOMLDecodeError, ValueError, RecursionError, InvalidOperation):
        raise InputError("invalid_toml") from None
    stack, count = [(result, 0)], 0
    while stack:
        value, depth = stack.pop()
        count += 1
        if depth > 64 or count > 100000:
            raise InputError("toml_structure_limit")
        if isinstance(value, dict):
            stack.extend((v, depth + 1) for v in value.values())
        elif isinstance(value, list):
            stack.extend((v, depth + 1) for v in value)
    return result

def overlay(base, patch, mode):
    result = base.copy()
    for key, value in patch.items():
        if mode == "deep" and isinstance(value, dict) and isinstance(base.get(key), dict):
            result[key] = overlay(base[key], value, mode)
        else:
            result[key] = value
    return result

def equal(a, b):
    if type(a) is not type(b):
        return False
    if isinstance(a, Decimal) and a.is_nan() and b.is_nan():
        return True
    if isinstance(a, list):
        return len(a) == len(b) and all(equal(x, y) for x, y in zip(a, b))
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(equal(a[k], b[k]) for k in a)
    return a == b

def audit(base_text, overlay_text, *, mode, show_paths=False):
    if mode not in ("shallow", "deep"):
        raise InputError("explicit_overlay_mode_required")
    base, patch = parse_toml(base_text), parse_toml(overlay_text)
    merged = overlay(base, patch, mode)
    report = Report(TOOL)
    def walk(left, right, rank_path, name_path):
        if isinstance(left, dict) and isinstance(right, dict):
            for rank, key in enumerate(sorted(left.keys() | right.keys()), 1):
                ranks, names = rank_path + [rank], name_path + [key]
                location = {"path_indices": ranks}
                if show_paths:
                    location["path"] = "/" + "/".join(s.replace("~", "~0").replace("/", "~1") for s in names)
                if key not in left:
                    report.add("added", **location, after_type=type(right[key]).__name__)
                elif key not in right:
                    report.add("removed", **location, before_type=type(left[key]).__name__)
                else:
                    walk(left[key], right[key], ranks, names)
        elif not equal(left, right):
            location = {"path_indices": rank_path}
            if show_paths:
                location["path"] = "/" + "/".join(s.replace("~", "~0").replace("/", "~1") for s in name_path)
            report.add("type_changed" if type(left) is not type(right) else "value_changed",
                       **location, before_type=type(left).__name__, after_type=type(right).__name__)
    walk(base, merged, [], [])
    return report.finish(mode=mode, changed_locations=report.count,
                         base_root_keys=len(base), overlay_root_keys=len(patch))

def run():
    parser = Parser(description=__doc__)
    parser.add_argument("input")
    parser.add_argument("--overlay", required=True)
    parser.add_argument("--mode", required=True, choices=("shallow", "deep"))
    parser.add_argument("--show-paths", action="store_true", help="Expose configuration key names, never values")
    args = parser.parse_args()
    return audit(read_text(args.input), read_text(args.overlay), mode=args.mode, show_paths=args.show_paths)

if __name__ == "__main__":
    sys.exit(emit_main(run))
