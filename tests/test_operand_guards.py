"""Ratchet: no new constant regex, bank-name set or bare ValueError in ``instructions/``.

Constants, bank sets and field refusals are moving to :mod:`laddercodec.operands`.  Each
instance in ``src/laddercodec/instructions/`` today is listed below, keyed by file and a
snippet of its source; the scan fails on an instance the lists do not hold, and on a
listed instance the code no longer has.  A step that removes an instance removes its
entry.

- ``REGEX``: a ``re.compile`` call, or a ``re.match``/``fullmatch``/``search`` call whose
  literal pattern reads digits, hex digits or ``$`` (the shapes of a constant).
- ``BANK_SET``: a set literal, or ``set``/``frozenset`` of a literal, whose items are all
  text and include a bank name.
- ``VALUE_ERROR``: ``raise ValueError(...)`` outside the blob-parse functions in
  ``BLOB_PARSE``, which report malformed bytes and stay ``ValueError``.
"""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

from laddercodec.operands.address import ADDRESS_BANKS

INSTRUCTIONS = Path(__file__).resolve().parents[1] / "src" / "laddercodec" / "instructions"

_MATCH_FUNCS = frozenset({"match", "fullmatch", "search"})
_CONSTANT_PATTERN_HINTS = ("0-9", "\\d", "A-F", "a-f", "\\$")
_SNIPPET_MAX = 72

#: Functions that parse blob bytes; a ``ValueError`` there reports malformed data.
BLOB_PARSE = frozenset({("raw.py", "_read_utf16le_boundary"), ("raw.py", "find_blob_boundary")})

Key = tuple[str, str]


def _snippet(node: ast.AST) -> str:
    """The node's source on one line, cut at ``_SNIPPET_MAX``; a text constant's value."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        text = node.value
    else:
        text = " ".join(ast.unparse(node).split())
    return text if len(text) <= _SNIPPET_MAX else text[:_SNIPPET_MAX] + "..."


def _is_re_call(node: ast.Call, names: frozenset[str] | set[str]) -> bool:
    func = node.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr in names
        and isinstance(func.value, ast.Name)
        and func.value.id == "re"
    )


def _is_regex(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    if _is_re_call(node, {"compile"}):
        return True
    if _is_re_call(node, _MATCH_FUNCS) and node.args:
        pattern = node.args[0]
        if isinstance(pattern, ast.Constant) and isinstance(pattern.value, str):
            return any(hint in pattern.value for hint in _CONSTANT_PATTERN_HINTS)
    return False


def _bank_items(node: ast.AST) -> list[str] | None:
    """The items of a set literal (or ``set``/``frozenset`` of a literal) if all are text."""
    if isinstance(node, ast.Set):
        elts = node.elts
    elif (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"set", "frozenset"}
        and len(node.args) == 1
        and isinstance(node.args[0], (ast.Set, ast.List, ast.Tuple))
    ):
        elts = node.args[0].elts
    else:
        return None
    items = [e.value for e in elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    if not items or len(items) != len(elts):
        return None
    return items


def _is_bank_set(node: ast.AST, parent: ast.AST | None) -> bool:
    items = _bank_items(node)
    if items is None or not any(item in ADDRESS_BANKS for item in items):
        return False
    # ``frozenset({...})`` is one instance, not two.
    return not (isinstance(node, ast.Set) and parent is not None and _bank_items(parent))


def _value_error(node: ast.AST) -> bool:
    if not isinstance(node, ast.Raise) or not isinstance(node.exc, ast.Call):
        return False
    func = node.exc.func
    return isinstance(func, ast.Name) and func.id == "ValueError"


def scan(root: Path = INSTRUCTIONS) -> dict[str, Counter[Key]]:
    """Every instance of each guarded kind under ``root``, counted by (file, snippet)."""
    found: dict[str, Counter[Key]] = {"REGEX": Counter(), "BANK_SET": Counter()}
    found["VALUE_ERROR"] = Counter()
    for path in sorted(root.glob("*.py")):
        name = path.name
        tree = ast.parse(path.read_text(encoding="utf-8"))
        parents: dict[ast.AST, ast.AST] = {
            child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)
        }

        def function_of(node: ast.AST, parents: dict[ast.AST, ast.AST] = parents) -> str:
            while node in parents:
                node = parents[node]
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    return node.name
            return ""

        for node in ast.walk(tree):
            if _is_regex(node):
                assert isinstance(node, ast.Call)
                found["REGEX"][(name, _snippet(node.args[0]))] += 1
            elif _is_bank_set(node, parents.get(node)):
                found["BANK_SET"][(name, _snippet(node))] += 1
            elif _value_error(node) and (name, function_of(node)) not in BLOB_PARSE:
                assert isinstance(node, ast.Raise) and node.exc is not None
                found["VALUE_ERROR"][(name, _snippet(node.exc))] += 1
    return found


# ---------------------------------------------------------------------------
# Allowlists: the instances in instructions/ at the start of the operands move
# ---------------------------------------------------------------------------

REGEX_ALLOWED: dict[Key, int] = {
    ("comparison.py", "[+-]?(?:[0-9]+\\.?[0-9]*|\\.[0-9]+)(?:[eE][+-]?[0-9]+)?"): 1,
    ("comparison.py", "[+-]?[0-9]+"): 1,
    ("comparison.py", "[0-9A-Fa-f]+[hH]"): 1,
    ("comparison.py", "\\$[0-9A-Fa-f]{2}"): 1,
    ("copy.py", "([A-Z]{1,3})\\[(.*)\\]"): 1,
    ("copy.py", "DD[0-9]+"): 1,
    ("copy.py", "DF[0-9]+"): 1,
    ("copy.py", "[+-]?(?:[0-9]+\\.?[0-9]*|\\.[0-9]+)(?:[eE][+-]?[0-9]+)?|[+-]?[0-9A-Fa-f]+[..."): 1,
    ("copy.py", "[+-]?([0-9A-Fa-f]+)[hH]"): 1,
    ("copy.py", "[+-]?[0-9]+"): 1,
    ("copy.py", "\\$[0-9A-Fa-f]+"): 1,
    ("copy.py", "\\$[0-9A-Fa-f]{1,2}"): 1,
    ("copy.py", "\\$[0-9A-Fa-f]{2}"): 1,
    ("copy.py", "^to_(text|value|binary|ascii)(?:\\((.*)\\))?$"): 1,
    ("counter.py", "-?[0-9]+"): 1,
    ("drum.py", "[0-9]+"): 1,
    ("drum.py", "[A-Z]+[0-9]+"): 1,
    ("forloop.py", "[0-9]+"): 1,
    ("forloop.py", "[0-9]+(\\s+[0-9]+)+"): 1,
    ("math.py", "([A-Z]{1,3})([0-9]+u?)"): 1,
    ("math.py", "-?(?:(?:[0-9]+\\.[0-9]*|\\.[0-9]+)(?:[eE][+-]?[0-9]+)?|[0-9]+[eE][+-]?[0-9..."): 1,
    ("math.py", "-?[0-9]+"): 2,
    ("math.py", "H(-?[0-9]+)"): 1,
    ("math.py", "[0-9A-Fa-f]+h"): 1,
    ("math.py", "\\b(?:(?:CTD|CT|TD|TXT|SC|SD|DS|DD|DH|DF|X|Y|C|T)[0-9]+|(?:XD|YD)[0-9]+u?..."): 1,
    ("math.py", "\\b([A-Z]+)([0-9]+u?) : \\1([0-9]+u?)\\b"): 1,
    ("math.py", "f'<[^>]*>|{_HEX_CONSTANT}|{_NUMBER}|\\\\w+|\\\\S'"): 1,
    ("math.py", "f'{_HEX_CONSTANT}|{_NUMBER}'"): 1,
    ("out_variant.py", "[+-][0-9]+"): 1,
    ("raw.py", "(?:0[xX])?[0-9A-Fa-f]+"): 1,
    ("raw.py", "([0-9a-fA-F]{4})(?:\\[([0-9]+)\\])?(?::([0-9a-fA-F]{8}))?=(.*)"): 1,
    ("raw.py", "[0-9]+"): 1,
    ("search.py", "[+-]?([0-9A-Fa-f]+)[hH]"): 1,
    ("send_receive.py", "([0-9]{1,3})\\.([0-9]{1,3})\\.([0-9]{1,3})\\.([0-9]{1,3})"): 1,
    ("send_receive.py", "DS([1-9][0-9]*)"): 1,
    ("send_receive.py", "[0-9A-Fa-f]{1,4}h"): 1,
    ("send_receive.py", "^([A-Z]+)([0-9]+)$"): 1,
    ("send_receive.py", "^([A-Za-z_][A-Za-z0-9_]*)\\((.+)\\)$"): 1,
    ("timer.py", "[0-9]+"): 1,
}

BANK_SET_ALLOWED: dict[Key, int] = {
    ("coil.py", "frozenset({'Y', 'C', 'SC'})"): 1,
    ("comparison.py", "frozenset({'TD', 'CTD', 'DS', 'DD', 'DF', 'SD'})"): 1,
    ("comparison.py", "frozenset({'TXT'})"): 1,
    ("comparison.py", "frozenset({'XD', 'YD', 'DH'})"): 1,
    ("contact.py", "frozenset({'X', 'Y', 'C', 'T', 'CT', 'SC'})"): 1,
    ("copy.py", "frozenset({'C', 'DS', 'DD', 'DH', 'DF', 'XD', 'YD', 'TD', 'CTD', 'TXT'})"): 1,
    ("copy.py", "frozenset({'C', 'DS', 'DH'})"): 1,
    ("copy.py", "frozenset({'C'})"): 2,
    ("copy.py", "frozenset({'DD', 'CTD'})"): 1,
    ("copy.py", "frozenset({'DD', 'DF'})"): 2,
    ("copy.py", "frozenset({'DD'})"): 1,
    ("copy.py", "frozenset({'DH'})"): 3,
    ("copy.py", "frozenset({'DS', 'DD', 'DH', 'DF', 'SD'})"): 1,
    ("copy.py", "frozenset({'DS', 'DD', 'DH', 'DF', 'TD', 'CTD', 'SD'})"): 1,
    ("copy.py", "frozenset({'DS', 'DD', 'DH', 'DF', 'TD', 'CTD'})"): 1,
    ("copy.py", "frozenset({'DS', 'DD', 'DH', 'DF', 'XD', 'YD', 'TD', 'CTD', 'SD', 'TXT'}..."): 1,
    ("copy.py", "frozenset({'DS', 'DD', 'DH', 'DF'})"): 1,
    ("copy.py", "frozenset({'DS', 'DD', 'DH', 'TXT'})"): 1,
    ("copy.py", "frozenset({'DS'})"): 2,
    ("copy.py", "frozenset({'TXT'})"): 5,
    ("copy.py", "frozenset({'X', 'Y', 'C', 'T', 'CT', 'SC'})"): 1,
    ("copy.py", "frozenset({'X', 'Y', 'T', 'CT', 'SC'})"): 1,
    ("copy.py", "frozenset({'Y', 'C'})"): 3,
    ("copy.py", "{'DS'}"): 1,
    ("copy.py", "{'TXT'}"): 2,
    ("copy.py", "{'XD'}"): 1,
    ("copy.py", "{'Y', 'C'}"): 1,
    ("counter.py", "frozenset({'DS', 'DD'})"): 1,
    ("counter.py", "{'CT'}"): 1,
    ("counter.py", "{'CTD'}"): 1,
    ("drum.py", "frozenset({'X', 'Y', 'C', 'T', 'CT', 'SC'})"): 1,
    ("drum.py", "{'C'}"): 1,
    ("drum.py", "{'DS'}"): 3,
    ("drum.py", "{'TD'}"): 1,
    ("drum.py", "{'Y', 'C'}"): 1,
    ("forloop.py", "frozenset({'DS', 'DD', 'TD', 'CTD', 'SD'})"): 1,
    ("math.py", "frozenset({'CT'})"): 1,
    ("math.py", "frozenset({'DH', 'YD'})"): 1,
    ("math.py", "frozenset({'DS', 'DD', 'DF', 'TD', 'CTD', 'SD'})"): 1,
    ("out_variant.py", "frozenset({'TD'})"): 1,
    ("out_variant.py", "{'DS'}"): 1,
    ("search.py", "frozenset({'C'})"): 1,
    ("search.py", "frozenset({'DS', 'DD', 'DH', 'DF', 'TD', 'CTD', 'TXT'})"): 1,
    ("search.py", "frozenset({'DS'})"): 1,
    ("send_receive.py", "frozenset({'C'})"): 1,
    ("send_receive.py", "frozenset({'CTD', 'DD', 'DF'})"): 1,
    ("send_receive.py", "frozenset({'CTD', 'DS', 'DD', 'DH', 'DF', 'SD', 'TD', 'TXT'})"): 1,
    ("send_receive.py", "frozenset({'CTD', 'DS', 'DD', 'DH', 'DF', 'TD', 'SD', 'TXT'})"): 1,
    ("send_receive.py", "frozenset({'DD', 'CTD', 'DF', 'TXT'})"): 1,
    ("send_receive.py", "frozenset({'DD', 'CTD'})"): 1,
    ("send_receive.py", "frozenset({'DD', 'DF', 'CTD'})"): 1,
    ("send_receive.py", "frozenset({'DF'})"): 1,
    ("send_receive.py", "frozenset({'DH', 'XD', 'YD'})"): 2,
    ("send_receive.py", "frozenset({'DS', 'DD'})"): 1,
    ("send_receive.py", "frozenset({'DS', 'DH', 'SD', 'TD', 'YD', 'TXT'})"): 1,
    ("send_receive.py", "frozenset({'DS', 'DH', 'XD', 'YD', 'TD', 'SD', 'TXT'})"): 1,
    ("send_receive.py", "frozenset({'DS', 'TD', 'SD'})"): 1,
    ("send_receive.py", "frozenset({'TXT'})"): 1,
    ("send_receive.py", "frozenset({'X', 'Y', 'C', 'T', 'CT', 'SC'})"): 2,
    ("send_receive.py", "frozenset({'X', 'Y'})"): 1,
    ("send_receive.py", "frozenset({'Y', 'C'})"): 2,
    ("shift.py", "frozenset({'C'})"): 1,
    ("timer.py", "{'DS'}"): 1,
    ("timer.py", "{'T'}"): 1,
    ("timer.py", "{'TD'}"): 1,
}

VALUE_ERROR_ALLOWED: dict[Key, int] = {
    ("call.py", "ValueError(f'Cannot parse call instruction: {token!r}')"): 1,
    ("coil.py", "ValueError('coil oneshot must be 0 or 1')"): 1,
    ("coil.py", "ValueError(f\"Range delimiter ':' is unsupported: {token!r}\")"): 1,
    ("coil.py", "ValueError(f'Cannot parse coil keyword arg: {token!r}')"): 1,
    ("coil.py", "ValueError(f'Cannot parse coil range: {token!r}')"): 1,
    ("coil.py", "ValueError(f'Cannot parse coil: {token!r}')"): 2,
    ("coil.py", "ValueError(f'Coil does not support keyword argument(s): {sorted(unknown)..."): 1,
    ("coil.py", "ValueError(f'Immediate must be an inner wrapper (e.g. out(immediate(Y1))..."): 1,
    ("coil.py", "ValueError(f'only out() supports oneshot, not {token!r}')"): 1,
    ("coil.py", "ValueError(f'only out() supports oneshot: {self.to_csv()}')"): 1,
    ("comparison.py", "ValueError(f'Cannot parse compare contact: {token!r}')"): 1,
    ("contact.py", "ValueError(\"Edge contacts require edge_kind 'rise' or 'fall'\")"): 2,
    ("contact.py", "ValueError('Immediate edge contacts are unsupported')"): 2,
    ("copy.py", "ValueError(f\"Expected range with '..': {arg!r}\")"): 1,
    ("copy.py", "ValueError(f'Cannot parse convert value: {raw!r}')"): 1,
    ("copy.py", "ValueError(f'Cannot parse copy: {token!r}')"): 1,
    ("copy.py", "ValueError(f'Cannot parse range: {arg!r}')"): 1,
    ("copy.py", "ValueError(f'Unknown format: {self.format!r}')"): 1,
    ("copy.py", "ValueError(f'Unsupported copy-family instruction: {call.name!r}')"): 1,
    ("copy.py", "ValueError(f'blockcopy expects 2 positional args (src_range, dest_range)..."): 1,
    ("copy.py", "ValueError(f'copy expects 2 positional args (source, dest), got {len(arg..."): 1,
    ("copy.py", "ValueError(f'copy expects 2 positional args (source, dest), got {len(cal..."): 1,
    ("copy.py", "ValueError(f'fill expects 2 positional args (value, dest_range), got {le..."): 1,
    ("copy.py", "ValueError(f'to_{fmt} options must be keyword arguments: {raw!r}')"): 1,
    ("copy.py", "ValueError(f'to_{fmt} takes no arguments: {raw!r}')"): 1,
    ("copy.py", "ValueError(f'{call.name} expects 2 positional args (source, dest_range),..."): 1,
    ("copy.py", "ValueError(f'{call.name} expects 2 positional args (src_range, dest), go..."): 1,
    ("counter.py", "ValueError(f'Cannot parse counter: {token!r}')"): 1,
    (
        "counter.py",
        "ValueError(f'Unsupported counter variant: {self.counter_type}(down={self...",
    ): 1,
    (
        "counter.py",
        "ValueError(f'{counter_type} expects 2 positional args (done, current), g...",
    ): 1,
    ("counter.py", "ValueError(f'{counter_type} missing preset kwarg: {token!r}')"): 1,
    ("counter.py", "ValueError(f'{self.counter_type} requires a .reset() pin row')"): 1,
    ("drum.py", "ValueError('Drum requires a .reset() pin row')"): 1,
    ("drum.py", "ValueError(f'A pattern cell is 0 or 1: {row_str!r}')"): 1,
    ("drum.py", "ValueError(f'Expected list: {val!r}')"): 1,
    ("drum.py", "ValueError(f'Expected nested list: {val!r}')"): 1,
    ("drum.py", "ValueError(f'Unsupported time drum unit: {unit!r}')"): 1,
    ("drum.py", "ValueError(f'Unsupported time_event_drum unit: {unit!r}')"): 1,
    ("drum.py", "ValueError(f'Unsupported {self.drum_kind} drum unit: {self.unit!r}')"): 1,
    ("drum.py", "ValueError(f'time_event_drum accumulator must be a TD address: {accumula..."): 1,
    ("drum.py", "ValueError(f'time_event_drum needs one preset and one event per step (No..."): 1,
    ("email.py", "ValueError(f'Not a raw Email token: {token!r}')"): 1,
    ("email.py", "ValueError(f'Not an Email token: {token!r}')"): 1,
    ("end.py", "ValueError(f'Cannot parse end instruction: {token!r}')"): 1,
    ("forloop.py", "ValueError('for oneshot must be 0 or 1')"): 1,
    ("forloop.py", "ValueError(f'Cannot parse break instruction: {token!r}')"): 1,
    ("forloop.py", "ValueError(f'Cannot parse continue instruction: {token!r}')"): 1,
    ("forloop.py", "ValueError(f'Cannot parse for instruction: {token!r}')"): 1,
    ("forloop.py", "ValueError(f'Cannot parse next instruction: {token!r}')"): 1,
    (
        "forloop.py",
        "ValueError(f'for does not support keyword argument(s): {sorted(unknown)}...",
    ): 1,
    ("forloop.py", "ValueError(f'for expects 1 positional arg (limit), got {len(args)}')"): 1,
    ("home.py", "ValueError(f'Not a Home token: {token!r}')"): 1,
    ("home.py", "ValueError(f'Not a raw Home token: {token!r}')"): 1,
    ("math.py", "ValueError(f\"math mode must be 'decimal' or 'hex', got {mode_arg!r}\")"): 1,
    ("math.py", "ValueError(f'math expects 2 positional args (expression, result), got {l..."): 1,
    ("out_variant.py", "ValueError('timed maintained must be 0 or 1')"): 1,
    ("out_variant.py", "ValueError(f'Cannot parse Out variant: {token!r}')"): 1,
    ("out_variant.py", "ValueError(f'Cannot parse {kind} keyword arg: {token!r}')"): 1,
    ("out_variant.py", "ValueError(f'toggle takes no keyword arguments: {token!r}')"): 1,
    (
        "out_variant.py",
        "ValueError(f'{kind} does not support keyword argument(s): {sorted(unknow...",
    ): 1,
    (
        "out_variant.py",
        "ValueError(f'{kind} missing keyword argument(s) {sorted(missing)}: {toke...",
    ): 1,
    ("out_variant.py", "ValueError(f'{kind} needs a target operand: {token!r}')"): 1,
    ("position.py", "ValueError(f'Not a Position token: {token!r}')"): 1,
    ("position.py", "ValueError(f'Not a raw Position token: {token!r}')"): 1,
    ("raw.py", "ValueError(f'Invalid field spec: {spec!r}')"): 1,
    ("raw.py", "ValueError(f'Not a raw token: {token!r}')"): 1,
    ("raw.py", "ValueError(f'raw({class_name},...): type marker is 0xTTTT and part count..."): 1,
    ("return_.py", "ValueError('return expects no arguments')"): 1,
    ("return_.py", "ValueError(f'Cannot parse return instruction: {token!r}')"): 1,
    ("search.py", "ValueError('search missing result or found kwargs')"): 1,
    ("search.py", "ValueError(f'Cannot parse search expression: {expr!r}')"): 1,
    ("search.py", "ValueError(f'search expects 1 positional arg (expression), got {len(call..."): 1,
    ("send_receive.py", "ValueError(f'Cannot parse target: {raw!r}')"): 1,
    ("send_receive.py", "ValueError(f'Unknown target type: {cls_name!r}')"): 1,
    ("send_receive.py", "ValueError(f'Unsupported send_receive instruction: {call.name!r}')"): 1,
    ("shift.py", "ValueError(f'Cannot parse shift range: {token!r}')"): 1,
    ("shift.py", "ValueError(f'Cannot parse shift: {token!r}')"): 1,
    ("shift.py", "ValueError(f'shift expects a range arg (start..end): {token!r}')"): 1,
    ("timer.py", "ValueError(\"off_delay can't be retentive (no .reset() pin): CLICK's Time..."): 1,
    ("timer.py", "ValueError(f'Cannot parse timer: {token!r}')"): 1,
    ("timer.py", "ValueError(f'Unknown timer unit: {unit!r}')"): 1,
    ("timer.py", "ValueError(f'{timer_type} expects 2 positional args (done, acc), got {le..."): 1,
    ("timer.py", "ValueError(f'{timer_type} missing preset or unit kwargs: {token!r}')"): 1,
    ("velocity.py", "ValueError(f'Not a Velocity token: {token!r}')"): 1,
    ("velocity.py", "ValueError(f'Not a raw Velocity token: {token!r}')"): 1,
}

ALLOWED: dict[str, dict[Key, int]] = {
    "REGEX": REGEX_ALLOWED,
    "BANK_SET": BANK_SET_ALLOWED,
    "VALUE_ERROR": VALUE_ERROR_ALLOWED,
}


def _differences(kind: str) -> tuple[list[str], list[str]]:
    """(new instances, listed instances the code no longer has) for guard ``kind``."""
    found = scan()[kind]
    allowed = Counter(ALLOWED[kind])
    new = [f"{name}: {snip} (x{n})" for (name, snip), n in sorted((found - allowed).items())]
    gone = [f"{name}: {snip} (x{n})" for (name, snip), n in sorted((allowed - found).items())]
    return new, gone


def _check(kind: str, advice: str) -> None:
    new, gone = _differences(kind)
    assert not new, f"new {kind} in instructions/ ({advice}):\n" + "\n".join(new)
    assert not gone, f"{kind} entries no longer in the code; remove them:\n" + "\n".join(gone)


def test_no_new_constant_regex() -> None:
    _check("REGEX", "parse constants and addresses with laddercodec.operands")


def test_no_new_bank_set() -> None:
    _check("BANK_SET", "build bank sets from laddercodec.operands.banks")


def test_no_new_value_error() -> None:
    _check("VALUE_ERROR", "a refused field value raises FieldError")


_SAMPLE = """
import re

_HEX = re.compile(r"[0-9A-F]+h")
_CALL = re.compile(r"call\\((.*)\\)")
BITS = frozenset({"X", "Y"})
DEST = BITS | {"C"}
OPS = frozenset({"==", "!="})


def check(value):
    if re.fullmatch(r"\\$[0-9A-F]{2}", value):
        return
    if re.fullmatch(r"out\\((.+)\\)", value):
        return
    raise ValueError(f"bad {value!r}")


def find_blob_boundary(raw):
    raise ValueError("Truncated")
"""


def test_scan_finds_each_kind(tmp_path: Path) -> None:
    (tmp_path / "raw.py").write_text(_SAMPLE, encoding="utf-8")
    found = scan(tmp_path)
    assert found["REGEX"] == Counter(
        {
            ("raw.py", "[0-9A-F]+h"): 1,
            ("raw.py", "call\\((.*)\\)"): 1,
            ("raw.py", "\\$[0-9A-F]{2}"): 1,
        }
    )
    assert found["BANK_SET"] == Counter(
        {("raw.py", "frozenset({'X', 'Y'})"): 1, ("raw.py", "{'C'}"): 1}
    )
    # The blob-parse function's ValueError is exempt; the other one is found.
    assert found["VALUE_ERROR"] == Counter({("raw.py", "ValueError(f'bad {value!r}')"): 1})
