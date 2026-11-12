"""Ratchet: no new regex, bank-name literal or ValueError raise in ``instructions/``.

Constants, bank sets and field refusals are moving to :mod:`laddercodec.operands`.  Each
instance in ``src/laddercodec/instructions/`` today is listed below, keyed by file and its
source text (:func:`_key`); the scan fails on an instance the lists do not hold, and on a
listed instance the code no longer has.  A step that removes an instance removes its
entry.

- ``REGEX``: a call to a ``re`` function (``compile``, ``match``, ``fullmatch``,
  ``search``, ``sub``, ``subn``, ``split``, ``findall``, ``finditer``), through
  ``import re``, ``import re as x`` or ``from re import ...``.
- ``BANK_NAMES``: a set, tuple or list literal (or ``set``/``frozenset`` of one) whose
  items are all text and include a bank name, and a dict literal whose keys are.
- ``VALUE_ERROR``: a raise of ``ValueError``, called or bare, of a name bound to it, or of
  a ``ValueError`` subclass defined in ``instructions/``, outside the blob-parse functions
  in ``BLOB_PARSE``, which report malformed bytes and stay ``ValueError``.
"""

from __future__ import annotations

import ast
import copy
from collections import Counter
from pathlib import Path

from laddercodec.operands.address import ADDRESS_BANKS

INSTRUCTIONS = Path(__file__).resolve().parents[1] / "src" / "laddercodec" / "instructions"

_REGEX_FUNCS = frozenset(
    {"compile", "match", "fullmatch", "search", "sub", "subn", "split", "findall", "finditer"}
)
_SEQUENCES = (ast.Set, ast.List, ast.Tuple)

#: Functions that parse blob bytes; a ``ValueError`` there reports malformed data.
BLOB_PARSE = frozenset({("raw.py", "_read_utf16le_boundary"), ("raw.py", "find_blob_boundary")})

Key = tuple[str, str]


# ---------------------------------------------------------------------------
# Keys
# ---------------------------------------------------------------------------


def _fstring_text(node: ast.JoinedStr) -> str:
    """An f-string's source between the quotes, the same on every Python version."""
    parts = []
    for part in node.values:
        if isinstance(part, ast.Constant):
            parts.append(str(part.value).replace("{", "{{").replace("}", "}}"))
            continue
        assert isinstance(part, ast.FormattedValue)
        text = "{" + _key(part.value)
        if part.conversion != -1:
            text += "!" + chr(part.conversion)
        if isinstance(part.format_spec, ast.JoinedStr):
            text += ":" + _fstring_text(part.format_spec)
        parts.append(text + "}")
    return "".join(parts)


class _FStringsAsCalls(ast.NodeTransformer):
    """Write ``f"a {x!r}"`` as ``f('a {x!r}')``, which unparses alike on 3.11 and 3.12+."""

    def visit_JoinedStr(self, node: ast.JoinedStr) -> ast.AST:
        return ast.Call(ast.Name("f", ast.Load()), [ast.Constant(_fstring_text(node))], [])


def _key(node: ast.AST) -> str:
    """The node's source text, with f-strings in a version-independent form."""
    return ast.unparse(_FStringsAsCalls().visit(copy.deepcopy(node)))


# ---------------------------------------------------------------------------
# Detectors
# ---------------------------------------------------------------------------


def _re_names(tree: ast.Module) -> tuple[set[str], set[str]]:
    """(names bound to the ``re`` module, names bound to a ``re`` function) in ``tree``."""
    modules: set[str] = set()
    funcs: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(a.asname or a.name for a in node.names if a.name == "re")
        elif isinstance(node, ast.ImportFrom) and node.module == "re":
            funcs.update(a.asname or a.name for a in node.names if a.name in _REGEX_FUNCS)
    return modules, funcs


def _is_regex(node: ast.AST, modules: set[str], funcs: set[str]) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name):
        return func.id in funcs
    return (
        isinstance(func, ast.Attribute)
        and func.attr in _REGEX_FUNCS
        and isinstance(func.value, ast.Name)
        and func.value.id in modules
    )


def _text_items(elts: list[ast.expr]) -> list[str] | None:
    items = [e.value for e in elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    return items if items and len(items) == len(elts) else None


def _bank_items(node: ast.AST) -> list[str] | None:
    """The text items of a set/tuple/list literal, ``set``/``frozenset`` of one, or dict keys.

    None unless every item (every key) is text.
    """
    if isinstance(node, _SEQUENCES):
        return _text_items(node.elts)
    if isinstance(node, ast.Dict):
        keys = [k for k in node.keys if k is not None]
        return _text_items(keys) if len(keys) == len(node.keys) else None
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"set", "frozenset"}
        and len(node.args) == 1
        and isinstance(node.args[0], _SEQUENCES)
    ):
        return _text_items(node.args[0].elts)
    return None


def _names_banks(node: ast.AST) -> bool:
    items = _bank_items(node)
    # Any item, so a misspelled bank still counts; this also counts a few literals that are
    # not bank sets, such as the wire tokens ``("T", "|")`` and blob names ``("RD", "SD")``.
    return items is not None and any(item in ADDRESS_BANKS for item in items)


def _is_bank_literal(node: ast.AST, parent: ast.AST | None) -> bool:
    if not _names_banks(node):
        return False
    # ``frozenset({...})`` is one instance, not two.
    return not (
        isinstance(node, _SEQUENCES) and isinstance(parent, ast.Call) and _names_banks(parent)
    )


def _value_error_names(trees: list[ast.Module]) -> set[str]:
    """``ValueError``, the names bound to it and its subclasses defined in ``trees``."""
    names = {"ValueError"}

    def is_known(expr: ast.expr) -> bool:
        if isinstance(expr, ast.Name):
            return expr.id in names
        return isinstance(expr, ast.Attribute) and expr.attr in names

    while True:
        before = len(names)
        for tree in trees:
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and any(is_known(b) for b in node.bases):
                    names.add(node.name)
                elif isinstance(node, ast.Assign) and is_known(node.value):
                    names.update(t.id for t in node.targets if isinstance(t, ast.Name))
                elif isinstance(node, ast.ImportFrom) and node.module == "builtins":
                    names.update(a.asname or a.name for a in node.names if a.name in names)
        if len(names) == before:
            return names


def _raises_value_error(node: ast.AST, names: set[str]) -> bool:
    if not isinstance(node, ast.Raise) or node.exc is None:
        return False
    exc = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
    if isinstance(exc, ast.Name):
        return exc.id in names
    return isinstance(exc, ast.Attribute) and exc.attr in names


def scan(root: Path = INSTRUCTIONS) -> dict[str, Counter[Key]]:
    """Every instance of each guarded kind under ``root``, counted by (file, key)."""
    found: dict[str, Counter[Key]] = {
        "REGEX": Counter(),
        "BANK_NAMES": Counter(),
        "VALUE_ERROR": Counter(),
    }
    paths = sorted(root.glob("*.py"))
    trees = [ast.parse(path.read_text(encoding="utf-8")) for path in paths]
    error_names = _value_error_names(trees)
    for path, tree in zip(paths, trees, strict=True):
        name = path.name
        modules, funcs = _re_names(tree)
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
            if _is_regex(node, modules, funcs):
                found["REGEX"][(name, _key(node))] += 1
            elif _is_bank_literal(node, parents.get(node)):
                found["BANK_NAMES"][(name, _key(node))] += 1
            elif (
                _raises_value_error(node, error_names)
                and (name, function_of(node)) not in BLOB_PARSE
            ):
                assert isinstance(node, ast.Raise) and node.exc is not None
                found["VALUE_ERROR"][(name, _key(node.exc))] += 1
    return found


# ---------------------------------------------------------------------------
# Allowlists: the instances in instructions/ at the start of the operands move
# ---------------------------------------------------------------------------

REGEX_ALLOWED: dict[Key, int] = {
    ("call.py", 're.fullmatch(\'call\\\\("([^"]*)"\\\\)\', token)'): 1,
    ("coil.py", "re.fullmatch('(out|latch|reset)\\\\((.+)\\\\)', token)"): 1,
    ("coil.py", "re.fullmatch('immediate\\\\((.+)\\\\)', arg)"): 1,
    (
        "comparison.py",
        "re.compile('[+-]?(?:[0-9]+\\\\.?[0-9]*|\\\\.[0-9]+)(?:[eE][+-]?[0-9]+)?')",
    ): 1,
    ("comparison.py", "re.compile('[+-]?[0-9]+')"): 1,
    ("comparison.py", "re.compile('[0-9A-Fa-f]+[hH]')"): 1,
    ("contact.py", "re.fullmatch('(rise|fall)\\\\((.+)\\\\)', token)"): 1,
    ("contact.py", "re.fullmatch('immediate\\\\((.+)\\\\)', token)"): 1,
    ("copy.py", "re.compile('([A-Z]{1,3})\\\\[(.*)\\\\]')"): 1,
    ("copy.py", "re.compile('DD[0-9]+')"): 1,
    ("copy.py", "re.compile('DF[0-9]+')"): 1,
    (
        "copy.py",
        "re.compile('[+-]?(?:[0-9]+\\\\.?[0-9]*|\\\\.[0-9]+)(?:[eE][+-]?[0-9]+)?|[+-]?[0-9A-Fa-f]+[hH]')",
    ): 1,
    ("copy.py", "re.compile('[+-]?([0-9A-Fa-f]+)[hH]')"): 1,
    ("copy.py", "re.compile('[+-]?[0-9]+')"): 1,
    ("copy.py", "re.compile('^to_(text|value|binary|ascii)(?:\\\\((.*)\\\\))?$', re.DOTALL)"): 1,
    ("copy.py", "re.fullmatch('copy\\\\((.+)\\\\)', token)"): 1,
    ("copy.py", "re.match('[A-Z]*', operand)"): 1,
    ("counter.py", "re.compile('-?[0-9]+')"): 1,
    ("counter.py", "re.fullmatch('(count_up|count_down)\\\\((.+)\\\\)', token)"): 1,
    ("drum.py", "re.compile('[0-9]+')"): 1,
    ("drum.py", "re.compile('[A-Z]+[0-9]+')"): 1,
    ("end.py", "re.fullmatch('end\\\\(\\\\s*\\\\)', token)"): 1,
    ("forloop.py", "re.compile('[0-9]+')"): 1,
    ("forloop.py", "re.compile('[0-9]+(\\\\s+[0-9]+)+')"): 1,
    ("forloop.py", "re.fullmatch('break\\\\(\\\\s*\\\\)', token)"): 1,
    ("forloop.py", "re.fullmatch('continue\\\\(\\\\s*\\\\)', token)"): 1,
    ("forloop.py", "re.fullmatch('for\\\\((.+)\\\\)', token)"): 1,
    ("forloop.py", "re.fullmatch('next\\\\(\\\\s*\\\\)', token)"): 1,
    ("math.py", "re.compile('([A-Z]{1,3})([0-9]+u?)')"): 1,
    (
        "math.py",
        "re.compile('-?(?:(?:[0-9]+\\\\.[0-9]*|\\\\.[0-9]+)(?:[eE][+-]?[0-9]+)?|[0-9]+[eE][+-]?[0-9]+)')",
    ): 1,
    (
        "math.py",
        "re.compile('\\\\b(?:(?:CTD|CT|TD|TXT|SC|SD|DS|DD|DH|DF|X|Y|C|T)[0-9]+|(?:XD|YD)[0-9]+u?)\\\\b')",
    ): 1,
    ("math.py", "re.compile('\\\\b([A-Z]+)([0-9]+u?) : \\\\1([0-9]+u?)\\\\b')"): 1,
    ("math.py", "re.compile(_HEX_CONSTANT)"): 1,
    ("math.py", "re.compile(f('<[^>]*>|{_HEX_CONSTANT}|{_NUMBER}|\\\\w+|\\\\S'))"): 1,
    ("math.py", "re.compile(f('{_HEX_CONSTANT}|{_NUMBER}'))"): 1,
    ("math.py", "re.fullmatch('-?[0-9]+', token)"): 2,
    ("math.py", "re.fullmatch('H(-?[0-9]+)', token)"): 1,
    ("out_variant.py", "re.fullmatch('(toggle|debounce|flasher|timed)\\\\((.+)\\\\)', token)"): 1,
    ("out_variant.py", "re.fullmatch('[+-][0-9]+', value)"): 1,
    ("out_variant.py", "re.fullmatch('immediate\\\\((.+)\\\\)', arg)"): 1,
    (
        "raw.py",
        "re.compile('([0-9a-fA-F]{4})(?:\\\\[([0-9]+)\\\\])?(?::([0-9a-fA-F]{8}))?=(.*)')",
    ): 1,
    ("raw.py", "re.fullmatch('(?:0[xX])?[0-9A-Fa-f]+', parts[0])"): 1,
    ("raw.py", "re.fullmatch('[0-9]+', parts[1])"): 1,
    ("return_.py", "re.fullmatch('return\\\\(\\\\s*\\\\)', token)"): 1,
    ("search.py", "re.compile('[+-]?([0-9A-Fa-f]+)[hH]')"): 1,
    ("search.py", "re.fullmatch('(.+?)\\\\.\\\\.(.+?)\\\\s*(==|!=|>=|<=|>|<)\\\\s*(.+)', expr)"): 1,
    (
        "send_receive.py",
        "re.compile('([0-9]{1,3})\\\\.([0-9]{1,3})\\\\.([0-9]{1,3})\\\\.([0-9]{1,3})')",
    ): 1,
    ("send_receive.py", "re.compile('DS([1-9][0-9]*)')"): 1,
    ("send_receive.py", "re.compile('[0-9A-Fa-f]+h')"): 1,
    ("send_receive.py", "re.compile('^([A-Z]+)([0-9]+)$')"): 1,
    ("send_receive.py", "re.compile('^([A-Za-z_][A-Za-z0-9_]*)\\\\((.+)\\\\)$', re.DOTALL)"): 1,
    ("shift.py", "re.fullmatch('shift\\\\((.+)\\\\)', token)"): 1,
    ("timer.py", "re.compile('[0-9]+')"): 1,
    ("timer.py", "re.fullmatch('(on_delay|off_delay)\\\\((.+)\\\\)', token)"): 1,
}

BANK_NAMES_ALLOWED: dict[Key, int] = {
    ("coil.py", "frozenset({'Y', 'C', 'SC'})"): 1,
    ("comparison.py", "('T', '|')"): 1,
    ("comparison.py", "frozenset({'TD', 'CTD', 'DS', 'DD', 'DF', 'SD'})"): 1,
    ("comparison.py", "frozenset({'TXT'})"): 1,
    ("comparison.py", "frozenset({'XD', 'YD', 'DH'})"): 1,
    ("contact.py", "('T', '|')"): 1,
    ("contact.py", "frozenset({'X', 'Y', 'C', 'T', 'CT', 'SC'})"): 1,
    ("copy.py", "('X', 'Y')"): 1,
    ("copy.py", "('XD', 'YD')"): 2,
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
    ("copy.py", "frozenset({'DS', 'DD', 'DH', 'DF', 'XD', 'YD', 'TD', 'CTD', 'SD', 'TXT'})"): 1,
    ("copy.py", "frozenset({'DS', 'DD', 'DH', 'DF'})"): 1,
    ("copy.py", "frozenset({'DS', 'DD', 'DH', 'TXT'})"): 1,
    ("copy.py", "frozenset({'DS'})"): 2,
    ("copy.py", "frozenset({'TXT'})"): 5,
    ("copy.py", "frozenset({'X', 'Y', 'C', 'T', 'CT', 'SC'})"): 1,
    ("copy.py", "frozenset({'X', 'Y', 'T', 'CT', 'SC'})"): 1,
    ("copy.py", "frozenset({'Y', 'C'})"): 3,
    ("copy.py", "{'DS': 16, 'DH': 16, 'DD': 32, 'DF': 32}"): 1,
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
    ("math.py", "('XD', 'YD')"): 2,
    ("math.py", "frozenset({'CT'})"): 1,
    ("math.py", "frozenset({'DH', 'YD'})"): 1,
    ("math.py", "frozenset({'DS', 'DD', 'DF', 'TD', 'CTD', 'SD'})"): 1,
    ("math.py", "{'DS': 2, 'DH': 2, 'TD': 2, 'SD': 2, 'DD': 4, 'DF': 4, 'CTD': 4}"): 1,
    ("out_variant.py", "frozenset({'TD'})"): 1,
    ("out_variant.py", "{'DS'}"): 1,
    ("search.py", "frozenset({'C'})"): 1,
    ("search.py", "frozenset({'DS', 'DD', 'DH', 'DF', 'TD', 'CTD', 'TXT'})"): 1,
    ("search.py", "frozenset({'DS'})"): 1,
    ("send_receive.py", "('DD', 'DF')"): 1,
    ("send_receive.py", "('DS', 'DH')"): 1,
    ("send_receive.py", "('RD', 'SD')"): 1,
    ("send_receive.py", "('XD', 'YD')"): 2,
    ("send_receive.py", "('YD', 'TXT')"): 1,
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
    (
        "send_receive.py",
        "{'DS': frozenset({'DS', 'TD', 'SD'}), 'DD': frozenset({'DD', 'CTD'}), 'DF': frozenset({'DF'}), 'DH': frozenset({'DH', 'XD', 'YD'}), 'YD': frozenset({'DH', 'XD', 'YD'}), 'TXT': frozenset({'TXT'})}",
    ): 1,
    ("shift.py", "frozenset({'C'})"): 1,
    ("timer.py", "{'DS'}"): 1,
    ("timer.py", "{'T'}"): 1,
    ("timer.py", "{'TD'}"): 1,
}

VALUE_ERROR_ALLOWED: dict[Key, int] = {
    ("call.py", "ValueError(f('Cannot parse call instruction: {token!r}'))"): 1,
    ("coil.py", "ValueError('coil oneshot must be 0 or 1')"): 1,
    ("coil.py", "ValueError(f(\"Range delimiter ':' is unsupported: {token!r}\"))"): 1,
    ("coil.py", "ValueError(f('Cannot parse coil keyword arg: {token!r}'))"): 1,
    ("coil.py", "ValueError(f('Cannot parse coil range: {token!r}'))"): 1,
    ("coil.py", "ValueError(f('Cannot parse coil: {token!r}'))"): 2,
    ("coil.py", "ValueError(f('Coil does not support keyword argument(s): {sorted(unknown)}'))"): 1,
    (
        "coil.py",
        "ValueError(f('Immediate must be an inner wrapper (e.g. out(immediate(Y1))): {token!r}'))",
    ): 1,
    ("comparison.py", "ValueError(f('Cannot parse compare contact: {token!r}'))"): 1,
    ("contact.py", "ValueError('Immediate edge contacts are unsupported')"): 1,
    ("copy.py", "ValueError(f(\"Expected range with '..': {arg!r}\"))"): 1,
    ("copy.py", "ValueError(f('Cannot parse convert value: {raw!r}'))"): 1,
    ("copy.py", "ValueError(f('Cannot parse copy: {token!r}'))"): 1,
    ("copy.py", "ValueError(f('Cannot parse range: {arg!r}'))"): 1,
    ("copy.py", "ValueError(f('Unknown format: {self.format!r}'))"): 1,
    ("copy.py", "ValueError(f('Unsupported copy-family instruction: {call.name!r}'))"): 1,
    (
        "copy.py",
        "ValueError(f('blockcopy expects 2 positional args (src_range, dest_range), got {len(call.args)}'))",
    ): 1,
    (
        "copy.py",
        "ValueError(f('copy expects 2 positional args (source, dest), got {len(args)}: {token!r}'))",
    ): 1,
    (
        "copy.py",
        "ValueError(f('copy expects 2 positional args (source, dest), got {len(call.args)}'))",
    ): 1,
    (
        "copy.py",
        "ValueError(f('fill expects 2 positional args (value, dest_range), got {len(call.args)}'))",
    ): 1,
    ("copy.py", "ValueError(f('to_{fmt} options must be keyword arguments: {raw!r}'))"): 1,
    ("copy.py", "ValueError(f('to_{fmt} takes no arguments: {raw!r}'))"): 1,
    (
        "copy.py",
        "ValueError(f('{call.name} expects 2 positional args (source, dest_range), got {len(call.args)}'))",
    ): 1,
    (
        "copy.py",
        "ValueError(f('{call.name} expects 2 positional args (src_range, dest), got {len(call.args)}'))",
    ): 1,
    ("counter.py", "ValueError(f('Cannot parse counter: {token!r}'))"): 1,
    (
        "counter.py",
        "ValueError(f('Unsupported counter variant: {self.counter_type}(down={self.down_enabled}, reset={self.reset_enabled})'))",
    ): 1,
    (
        "counter.py",
        "ValueError(f('{counter_type} expects 2 positional args (done, current), got {len(args)}: {token!r}'))",
    ): 1,
    ("counter.py", "ValueError(f('{counter_type} missing preset kwarg: {token!r}'))"): 1,
    ("counter.py", "ValueError(f('{self.counter_type} requires a .reset() pin row'))"): 1,
    ("drum.py", "ValueError('Drum requires a .reset() pin row')"): 1,
    ("drum.py", "ValueError(f('A pattern cell is 0 or 1: {row_str!r}'))"): 1,
    ("drum.py", "ValueError(f('Expected list: {val!r}'))"): 1,
    ("drum.py", "ValueError(f('Expected nested list: {val!r}'))"): 1,
    ("drum.py", "ValueError(f('Unsupported time drum unit: {unit!r}'))"): 1,
    ("drum.py", "ValueError(f('Unsupported time_event_drum unit: {unit!r}'))"): 1,
    ("drum.py", "ValueError(f('Unsupported {self.drum_kind} drum unit: {self.unit!r}'))"): 1,
    (
        "drum.py",
        "ValueError(f('time_event_drum accumulator must be a TD address: {accumulator!r}'))",
    ): 1,
    (
        "drum.py",
        "ValueError(f('time_event_drum needs one preset and one event per step (None for unused): {len(presets)} presets, {len(events)} events'))",
    ): 1,
    ("email.py", "ValueError(f('Not a raw Email token: {token!r}'))"): 1,
    ("email.py", "ValueError(f('Not an Email token: {token!r}'))"): 1,
    ("end.py", "ValueError(f('Cannot parse end instruction: {token!r}'))"): 1,
    ("forloop.py", "ValueError('for oneshot must be 0 or 1')"): 1,
    ("forloop.py", "ValueError(f('Cannot parse break instruction: {token!r}'))"): 1,
    ("forloop.py", "ValueError(f('Cannot parse continue instruction: {token!r}'))"): 1,
    ("forloop.py", "ValueError(f('Cannot parse for instruction: {token!r}'))"): 1,
    ("forloop.py", "ValueError(f('Cannot parse next instruction: {token!r}'))"): 1,
    (
        "forloop.py",
        "ValueError(f('for does not support keyword argument(s): {sorted(unknown)}'))",
    ): 1,
    ("forloop.py", "ValueError(f('for expects 1 positional arg (limit), got {len(args)}'))"): 1,
    ("home.py", "ValueError(f('Not a Home token: {token!r}'))"): 1,
    ("home.py", "ValueError(f('Not a raw Home token: {token!r}'))"): 1,
    ("math.py", "ValueError(f(\"math mode must be 'decimal' or 'hex', got {mode_arg!r}\"))"): 1,
    (
        "math.py",
        "ValueError(f('math expects 2 positional args (expression, result), got {len(call.args)}'))",
    ): 1,
    ("out_variant.py", "ValueError('timed maintained must be 0 or 1')"): 1,
    ("out_variant.py", "ValueError(f('Cannot parse Out variant: {token!r}'))"): 1,
    ("out_variant.py", "ValueError(f('Cannot parse {kind} keyword arg: {token!r}'))"): 1,
    ("out_variant.py", "ValueError(f('toggle takes no keyword arguments: {token!r}'))"): 1,
    (
        "out_variant.py",
        "ValueError(f('{kind} does not support keyword argument(s): {sorted(unknown)}'))",
    ): 1,
    (
        "out_variant.py",
        "ValueError(f('{kind} missing keyword argument(s) {sorted(missing)}: {token!r}'))",
    ): 1,
    ("out_variant.py", "ValueError(f('{kind} needs a target operand: {token!r}'))"): 1,
    ("position.py", "ValueError(f('Not a Position token: {token!r}'))"): 1,
    ("position.py", "ValueError(f('Not a raw Position token: {token!r}'))"): 1,
    ("raw.py", "ValueError(f('Invalid field spec: {spec!r}'))"): 1,
    ("raw.py", "ValueError(f('Not a raw token: {token!r}'))"): 1,
    (
        "raw.py",
        "ValueError(f('raw({class_name},...): type marker is 0xTTTT and part count is digits'))",
    ): 1,
    ("return_.py", "ValueError('return expects no arguments')"): 1,
    ("return_.py", "ValueError(f('Cannot parse return instruction: {token!r}'))"): 1,
    ("search.py", "ValueError('search missing result or found kwargs')"): 1,
    ("search.py", "ValueError(f('Cannot parse search expression: {expr!r}'))"): 1,
    (
        "search.py",
        "ValueError(f('search expects 1 positional arg (expression), got {len(call.args)}'))",
    ): 1,
    ("send_receive.py", "ValueError(f('Cannot parse target: {raw!r}'))"): 1,
    ("send_receive.py", "ValueError(f('Unknown target type: {cls_name!r}'))"): 1,
    ("send_receive.py", "ValueError(f('Unsupported send_receive instruction: {call.name!r}'))"): 1,
    ("shift.py", "ValueError(f('Cannot parse shift range: {token!r}'))"): 1,
    ("shift.py", "ValueError(f('Cannot parse shift: {token!r}'))"): 1,
    ("shift.py", "ValueError(f('shift expects a range arg (start..end): {token!r}'))"): 1,
    ("timer.py", "ValueError(f('Cannot parse timer: {token!r}'))"): 1,
    ("timer.py", "ValueError(f('Unknown timer unit: {unit!r}'))"): 1,
    (
        "timer.py",
        "ValueError(f('{timer_type} expects 2 positional args (done, acc), got {len(args)}: {token!r}'))",
    ): 1,
    ("timer.py", "ValueError(f('{timer_type} missing preset or unit kwargs: {token!r}'))"): 1,
    ("velocity.py", "ValueError(f('Not a Velocity token: {token!r}'))"): 1,
    ("velocity.py", "ValueError(f('Not a raw Velocity token: {token!r}'))"): 1,
}

ALLOWED: dict[str, dict[Key, int]] = {
    "REGEX": REGEX_ALLOWED,
    "BANK_NAMES": BANK_NAMES_ALLOWED,
    "VALUE_ERROR": VALUE_ERROR_ALLOWED,
}


def _differences(kind: str) -> tuple[list[str], list[str]]:
    """(new instances, listed instances the code no longer has) for guard ``kind``."""
    found = scan()[kind]
    allowed = Counter(ALLOWED[kind])
    new = [f"{name}: {key} (x{n})" for (name, key), n in sorted((found - allowed).items())]
    gone = [f"{name}: {key} (x{n})" for (name, key), n in sorted((allowed - found).items())]
    return new, gone


def _check(kind: str, advice: str) -> None:
    new, gone = _differences(kind)
    assert not new, f"new {kind} in instructions/ ({advice}):\n" + "\n".join(new)
    assert not gone, f"{kind} entries no longer in the code; remove them:\n" + "\n".join(gone)


def test_no_new_regex() -> None:
    _check("REGEX", "parse constants and addresses with laddercodec.operands")


def test_no_new_bank_names() -> None:
    _check("BANK_NAMES", "build bank sets from laddercodec.operands.banks")


def test_no_new_value_error() -> None:
    _check("VALUE_ERROR", "a refused field value raises FieldError")


_SAMPLE = """
import re
import re as regex
from re import fullmatch as fm

_HEX = re.compile(r"[0-9A-F]+h")
_WORD = regex.compile(r"[A-Z]*")
BITS = frozenset({"X", "Y"})
DEST = BITS | {"C"}
OPS = frozenset({"==", "!="})
WORDS = ("XD", "YD")
ROWS = ["DS", "DD"]
LIMITS = {"DS": 1, "DD": 2}
FIELDS = {"source": 1}
Refused = ValueError


class BadToken(ValueError):
    pass


class WorseToken(BadToken):
    pass


def check(value):
    if fm(r'call\\("([^"]*)"\\)', value):
        return
    if re.split(",", value):
        return
    if value == "a":
        raise ValueError
    if value == "b":
        raise Refused(value)
    if value == "c":
        raise WorseToken(f"bad {value!r:>4}")
    raise ValueError(f"bad {value!r}")


def find_blob_boundary(raw):
    raise ValueError("Truncated")
"""


def test_scan_finds_each_kind(tmp_path: Path) -> None:
    (tmp_path / "raw.py").write_text(_SAMPLE, encoding="utf-8")
    found = scan(tmp_path)
    assert found["REGEX"] == Counter(
        {
            ("raw.py", "re.compile('[0-9A-F]+h')"): 1,
            ("raw.py", "regex.compile('[A-Z]*')"): 1,
            ("raw.py", 'fm(\'call\\\\("([^"]*)"\\\\)\', value)'): 1,
            ("raw.py", "re.split(',', value)"): 1,
        }
    )
    assert found["BANK_NAMES"] == Counter(
        {
            ("raw.py", "frozenset({'X', 'Y'})"): 1,
            ("raw.py", "{'C'}"): 1,
            ("raw.py", "('XD', 'YD')"): 1,
            ("raw.py", "['DS', 'DD']"): 1,
            ("raw.py", "{'DS': 1, 'DD': 2}"): 1,
        }
    )
    # The blob-parse function's ValueError is exempt; the others are found.
    assert found["VALUE_ERROR"] == Counter(
        {
            ("raw.py", "ValueError"): 1,
            ("raw.py", "Refused(value)"): 1,
            ("raw.py", "WorseToken(f('bad {value!r:>4}'))"): 1,
            ("raw.py", "ValueError(f('bad {value!r}'))"): 1,
        }
    )


def test_key_is_the_full_text() -> None:
    long = "x" * 200
    node = ast.parse(f"raise ValueError(f'{long} {{a}}')").body[0]
    assert isinstance(node, ast.Raise) and node.exc is not None
    assert _key(node.exc) == f"ValueError(f('{long} {{a}}'))"
