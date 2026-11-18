"""Refuse any regex, bank-name literal or ValueError raise in ``instructions/`` beyond those listed.

Constants, bank sets and field refusals are being moved into :mod:`laddercodec.operands`.
The lists below hold each instance of the three kinds that ``src/laddercodec/instructions/``
still has, keyed by file and source text (:func:`_key`). The scan fails on an instance that
the lists do not hold. It also fails on a listed instance that the code no longer has, so a
change that removes an instance must also remove its entry.

- ``REGEX``: a call to a ``re`` function (``compile``, ``match``, ``fullmatch``,
  ``search``, ``sub``, ``subn``, ``split``, ``findall``, ``finditer``) that was imported
  by ``import re``, ``import re as x`` or ``from re import ...``.
- ``BANK_NAMES``: a set, tuple or list literal, or a ``set`` or ``frozenset`` call on one,
  whose items are all text and include at least one bank name. A dict literal counts when
  its keys meet the same test. A call of :func:`laddercodec.operands.banks.banks` or
  :func:`~laddercodec.operands.banks.mask`, such as ``banks(Bank.DS | Bank.DD)``, counts
  too, under any name that an import binds and through the module (``b.banks(...)``). So
  does a ``Bank`` member, a ``Bank`` call, a ``Bank`` subscript with a constant key, or an
  operator chain of them, outside such a call: ``Bank.DD | Bank.DF``, ``Bank(0x3f)``,
  ``Bank['DS']``. A ``mask()`` call inside a ``banks()`` call is part of that call.
- ``VALUE_ERROR``: a raise of ``ValueError``, with or without a call. A raise of a name
  bound to ``ValueError`` counts too, and so does a raise of a ``ValueError`` subclass
  defined in ``instructions/`` or of a class of :mod:`laddercodec.errors` (``CsvError``,
  ``EncodeError``, ...). A raise in a function listed in ``BLOB_PARSE`` does not count.
  Those functions report malformed bytes, and they keep raising ``ValueError``. A raise of
  ``FieldError`` does not count, because ``FieldError`` is how a refused field is reported.
"""

from __future__ import annotations

import ast
import copy
from collections import Counter
from pathlib import Path
from typing import NamedTuple

from laddercodec import errors
from laddercodec.operands.address import ADDRESS_BANKS
from laddercodec.operands.banks import Bank

INSTRUCTIONS = Path(__file__).resolve().parents[1] / "src" / "laddercodec" / "instructions"

_REGEX_FUNCS = frozenset(
    {"compile", "match", "fullmatch", "search", "sub", "subn", "split", "findall", "finditer"}
)
_SEQUENCES = (ast.Set, ast.List, ast.Tuple)

#: The functions that parse blob bytes. A ``ValueError`` raised in one reports malformed data.
BLOB_PARSE = frozenset({("raw.py", "_read_utf16le_boundary"), ("raw.py", "find_blob_boundary")})

Key = tuple[str, str]

#: The ``ValueError`` subclasses in :mod:`laddercodec.errors`. The scan counts a raise of one
#: as a ``ValueError``.
TREE_ERRORS = frozenset(
    name
    for name, value in vars(errors).items()
    if isinstance(value, type) and issubclass(value, ValueError)
)


# ---------------------------------------------------------------------------
# Keys
# ---------------------------------------------------------------------------


def _fstring_text(node: ast.JoinedStr) -> str:
    """Return an f-string's source between its quotes, in the same form on every Python version."""
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
    """Rewrites ``f"a {x!r}"`` as ``f('a {x!r}')``. The call unparses the same on 3.11 and 3.12+."""

    def visit_JoinedStr(self, node: ast.JoinedStr) -> ast.AST:
        return ast.Call(ast.Name("f", ast.Load()), [ast.Constant(_fstring_text(node))], [])


def _key(node: ast.AST) -> str:
    """Return the node's source text, with each f-string in a form that every Python version
    unparses the same."""
    return ast.unparse(_FStringsAsCalls().visit(copy.deepcopy(node)))


# ---------------------------------------------------------------------------
# Detectors
# ---------------------------------------------------------------------------


def _re_names(tree: ast.Module) -> tuple[set[str], set[str]]:
    """Return two sets: the names in ``tree`` bound to the ``re`` module, and those bound to a
    ``re`` function."""
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


class BankNames(NamedTuple):
    """The names that one module binds to parts of :mod:`laddercodec.operands.banks`."""

    #: The names bound to :func:`~laddercodec.operands.banks.banks` and to
    #: :func:`~laddercodec.operands.banks.mask`.
    calls: frozenset[str]
    #: The names bound to the module itself, as in ``from ..operands import banks as b``.
    modules: frozenset[str]
    #: The names bound to :class:`~laddercodec.operands.banks.Bank`.
    flags: frozenset[str]


def bank_names(tree: ast.Module) -> BankNames:
    """Return the names in ``tree`` bound to :mod:`laddercodec.operands.banks`, to its
    ``banks`` and ``mask`` functions and to its ``Bank`` class.

    A name imported from a package (``from ..operands import banks``) is the module. A
    ``banks``, ``mask`` or ``Bank`` imported from any other module is the function or the
    class, so a re-export (``from ..model import Bank``) binds it too.
    """
    calls: set[str] = set()
    modules: set[str] = set()
    flags: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            source = (node.module or "").split(".")[-1]
            for alias in node.names:
                bound = alias.asname or alias.name
                if source in {"operands", ""} and alias.name == "banks":
                    modules.add(bound)
                elif alias.name in {"banks", "mask"}:
                    calls.add(bound)
                elif alias.name == "Bank":
                    flags.add(bound)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[-1] == "banks" and alias.asname:
                    modules.add(alias.asname)
    return BankNames(frozenset(calls), frozenset(modules), frozenset(flags))


def _is_banks_module(expr: ast.expr, names: BankNames) -> bool:
    if isinstance(expr, ast.Name):
        return expr.id in names.modules
    # ``laddercodec.operands.banks`` or ``operands.banks``, read through a parent package.
    return isinstance(expr, ast.Attribute) and ast.unparse(expr).endswith("operands.banks")


def _is_banks_call(node: ast.AST, names: BankNames) -> bool:
    """Return whether ``node`` calls ``banks()`` or ``mask()``, by a bound name or through
    the module."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name):
        return func.id in names.calls
    return (
        isinstance(func, ast.Attribute)
        and func.attr in {"banks", "mask"}
        and _is_banks_module(func.value, names)
    )


def _is_flags_class(expr: ast.expr, names: BankNames) -> bool:
    """Return whether ``expr`` names the ``Bank`` class, by a bound name or through the
    module."""
    if isinstance(expr, ast.Name):
        return expr.id in names.flags
    return (
        isinstance(expr, ast.Attribute)
        and expr.attr == "Bank"
        and _is_banks_module(expr.value, names)
    )


def _is_member(node: ast.AST, names: BankNames) -> bool:
    """Return whether ``node`` makes ``Bank`` flags: a member (``Bank.DS``), a call
    (``Bank(0x3f)``) or a subscript with a constant key (``Bank['DS']``)."""
    if isinstance(node, ast.Attribute):
        return node.attr in Bank.__members__ and _is_flags_class(node.value, names)
    if isinstance(node, ast.Call):
        return _is_flags_class(node.func, names)
    if isinstance(node, ast.Subscript):
        return isinstance(node.slice, ast.Constant) and _is_flags_class(node.value, names)
    return False


def _member_names(node: ast.AST) -> list[str]:
    """Return the names of the banks that a node accepted by :func:`_is_member` makes."""
    if isinstance(node, ast.Attribute):
        return [node.attr]
    if isinstance(node, ast.Subscript):
        assert isinstance(node.slice, ast.Constant)
        return [str(node.slice.value)]
    assert isinstance(node, ast.Call)
    value = node.args[0] if len(node.args) == 1 else None
    if isinstance(value, ast.Constant) and isinstance(value.value, int):
        return [name for name, bank in Bank.__members__.items() if value.value & bank]
    return []


def _members(node: ast.AST, names: BankNames) -> list[str]:
    """Return the names of the banks that each ``Bank`` member, call and subscript in
    ``node`` makes."""
    return [name for n in ast.walk(node) if _is_member(n, names) for name in _member_names(n)]


def _is_flags(node: ast.AST, names: BankNames) -> bool:
    """Return whether ``node`` is a ``Bank`` member, call or subscript, or an operator chain
    that holds one, such as ``Bank.DD | Bank.DF``."""
    if isinstance(node, (ast.BinOp, ast.UnaryOp)):
        return any(_is_member(n, names) for n in ast.walk(node))
    return _is_member(node, names)


def _text_items(elts: list[ast.expr]) -> list[str] | None:
    items = [e.value for e in elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    return items if items and len(items) == len(elts) else None


def _bank_items(node: ast.AST, names: BankNames) -> list[str] | None:
    """Return the text items of a set, tuple or list literal, or the keys of a dict literal.

    A ``set`` or ``frozenset`` call on a set, tuple or list literal counts as that literal.
    ``names`` holds the names that the module binds to :mod:`laddercodec.operands.banks`.
    For a call of ``banks()``, and for a ``Bank`` member or an operator chain of them,
    return the name of each ``Bank`` member in it. For a call of ``mask()``, return its text
    arguments. The list is empty for a call such as ``banks(BITS)``. Return None for any
    other node, for an empty literal, and for one with an item or key that is not text.
    """
    if _is_banks_call(node, names):
        assert isinstance(node, ast.Call)
        texts = [a.value for a in node.args if isinstance(a, ast.Constant)]
        return _members(node, names) + [t for t in texts if isinstance(t, str)]
    if _is_flags(node, names):
        return _members(node, names)
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


def _names_banks(node: ast.AST, names: BankNames) -> bool:
    if _is_banks_call(node, names) or _is_flags(node, names):
        return True
    items = _bank_items(node, names)
    # One bank name among the items is enough, so a set with a misspelled bank still counts.
    # This also counts a few literals that are not bank sets, such as the wire tokens
    # ``("T", "|")`` and the blob names ``("RD", "SD")``.
    return items is not None and any(item in ADDRESS_BANKS for item in items)


def _is_bank_literal(node: ast.AST, parents: dict[ast.AST, ast.AST], names: BankNames) -> bool:
    """Return whether ``node`` is one instance of a bank-name literal.

    ``parents`` maps each node of the module to its parent. ``frozenset({...})`` is one
    instance, not two. A ``Bank`` chain, and a call of ``banks()`` or ``mask()``, is one
    instance. Inside another of these, it is part of that one's instance.
    """
    if not _names_banks(node, names):
        return False
    parent = parents.get(node)
    if isinstance(node, _SEQUENCES) and isinstance(parent, ast.Call):
        return not _names_banks(parent, names)
    if not (_is_banks_call(node, names) or _is_flags(node, names)):
        return True
    while parent is not None:
        if _is_banks_call(parent, names) or _is_flags(parent, names):
            return False
        parent = parents.get(parent)
    return True


def _value_error_names(trees: list[ast.Module]) -> set[str]:
    """Return the names that count as ``ValueError``.

    They are ``ValueError``, the ``ValueError`` subclasses in :mod:`laddercodec.errors`, and
    each name in ``trees`` that is bound to one of these or is a class that subclasses one.
    """
    names = {"ValueError", *TREE_ERRORS}

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
    """Return every instance of each guarded kind in the ``.py`` files in ``root``, counted by
    (file, key)."""
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
        names = bank_names(tree)
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
            elif _is_bank_literal(node, parents, names):
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
    ("contact.py", "re.fullmatch('(rise|fall)\\\\((.+)\\\\)', token)"): 1,
    ("contact.py", "re.fullmatch('immediate\\\\((.+)\\\\)', token)"): 1,
    ("copy.py", "re.compile('^to_(text|value|binary|ascii)(?:\\\\((.*)\\\\))?$', re.DOTALL)"): 1,
    ("copy.py", "re.fullmatch('copy\\\\((.+)\\\\)', token)"): 1,
    ("counter.py", "re.fullmatch('(count_up|count_down)\\\\((.+)\\\\)', token)"): 1,
    ("end.py", "re.fullmatch('end\\\\(\\\\s*\\\\)', token)"): 1,
    ("forloop.py", "re.compile('[0-9]+(\\\\s+[0-9]+)+')"): 1,
    ("forloop.py", "re.fullmatch('break\\\\(\\\\s*\\\\)', token)"): 1,
    ("forloop.py", "re.fullmatch('continue\\\\(\\\\s*\\\\)', token)"): 1,
    ("forloop.py", "re.fullmatch('for\\\\((.+)\\\\)', token)"): 1,
    ("forloop.py", "re.fullmatch('next\\\\(\\\\s*\\\\)', token)"): 1,
    ("out_variant.py", "re.fullmatch('(toggle|debounce|flasher|timed)\\\\((.+)\\\\)', token)"): 1,
    ("out_variant.py", "re.fullmatch('immediate\\\\((.+)\\\\)', arg)"): 1,
    (
        "raw.py",
        "re.compile('([0-9a-fA-F]{4})(?:\\\\[([0-9]+)\\\\])?(?::([0-9a-fA-F]{8}))?=(.*)')",
    ): 1,
    ("raw.py", "re.fullmatch('(?:0[xX])?[0-9A-Fa-f]+', parts[0])"): 1,
    ("raw.py", "re.fullmatch('[0-9]+', parts[1])"): 1,
    ("return_.py", "re.fullmatch('return\\\\(\\\\s*\\\\)', token)"): 1,
    (
        "search.py",
        "re.fullmatch('(.+?)\\\\.\\\\.(.+?)\\\\s*(==|!=|>=|<=|>|<)\\\\s*(.+)', expr, re.DOTALL)",
    ): 1,
    (
        "send_receive.py",
        "re.compile('([0-9]{1,3})\\\\.([0-9]{1,3})\\\\.([0-9]{1,3})\\\\.([0-9]{1,3})')",
    ): 1,
    ("send_receive.py", "re.compile('^([A-Za-z_][A-Za-z0-9_]*)\\\\((.+)\\\\)$', re.DOTALL)"): 1,
    ("shift.py", "re.fullmatch('shift\\\\((.+)\\\\)', token)"): 1,
    ("timer.py", "re.fullmatch('(on_delay|off_delay)\\\\((.+)\\\\)', token)"): 1,
}

BANK_NAMES_ALLOWED: dict[Key, int] = {
    ("comparison.py", "frozenset({'TD', 'CTD', 'DS', 'DD', 'DF', 'SD'})"): 1,
    ("comparison.py", "frozenset({'TXT'})"): 1,
    ("comparison.py", "frozenset({'XD', 'YD', 'DH'})"): 1,
    ("contact.py", "('T', '|')"): 1,
    ("copy.py", "frozenset({'C', 'DS', 'DH'})"): 1,
    ("copy.py", "frozenset({'C'})"): 2,
    ("copy.py", "frozenset({'DD', 'CTD'})"): 1,
    ("copy.py", "frozenset({'DD', 'DF'})"): 2,
    ("copy.py", "frozenset({'DD'})"): 1,
    ("copy.py", "frozenset({'DH'})"): 3,
    ("copy.py", "frozenset({'DS', 'DD', 'DH', 'DF', 'SD'})"): 1,
    ("copy.py", "frozenset({'DS', 'DD', 'DH', 'DF', 'TD', 'CTD', 'SD'})"): 1,
    ("copy.py", "frozenset({'DS', 'DD', 'DH', 'DF', 'TD', 'CTD'})"): 1,
    ("copy.py", "frozenset({'DS', 'DD', 'DH', 'DF'})"): 1,
    ("copy.py", "frozenset({'DS', 'DD', 'DH', 'TXT'})"): 1,
    ("copy.py", "frozenset({'DS'})"): 2,
    ("copy.py", "frozenset({'TXT'})"): 5,
    ("copy.py", "frozenset({'X', 'Y', 'T', 'CT', 'SC'})"): 1,
    ("copy.py", "frozenset({'Y', 'C'})"): 3,
    ("copy.py", "{'TXT'}"): 2,
    ("copy.py", "{'XD'}"): 1,
    ("copy.py", "{'Y', 'C'}"): 1,
    ("counter.py", "frozenset({'DS', 'DD'})"): 1,
    ("counter.py", "{'CT'}"): 1,
    ("counter.py", "{'CTD'}"): 1,
    ("drum.py", "{'C'}"): 1,
    ("drum.py", "{'DS'}"): 3,
    ("drum.py", "{'TD'}"): 1,
    ("drum.py", "{'Y', 'C'}"): 1,
    ("forloop.py", "frozenset({'DS', 'DD', 'TD', 'CTD', 'SD'})"): 1,
    ("math_formula.py", "banks(Bank.DH | Bank.XD | Bank.YD)"): 1,
    ("math_formula.py", "banks(Bank.DH)"): 1,
    ("math_formula.py", "banks(Bank.DS | Bank.DD | Bank.DF | Bank.TD | Bank.CTD | Bank.SD)"): 1,
    ("math_formula.py", "banks(Bank.DS | Bank.DD)"): 1,
    ("math_formula.py", "banks(Bank.X | Bank.Y | Bank.C | Bank.T | Bank.SC)"): 1,
    ("math.py", "frozenset({'DH', 'YD'})"): 1,
    ("math.py", "frozenset({'DS', 'DD', 'DF', 'TD', 'CTD', 'SD'})"): 1,
    ("out_variant.py", "frozenset({'TD'})"): 1,
    ("out_variant.py", "{'DS'}"): 1,
    ("search.py", "frozenset({'C'})"): 1,
    ("search.py", "frozenset({'DS', 'DD', 'DH', 'DF', 'TD', 'CTD', 'TXT'})"): 1,
    ("search.py", "frozenset({'DS'})"): 1,
    ("send_receive.py", "('DD', 'DF')"): 1,
    ("send_receive.py", "('DS', 'DD', 'DF', 'DH', 'YD', 'TXT')"): 1,
    ("send_receive.py", "('DS', 'DH')"): 1,
    ("send_receive.py", "('RD', 'SD')"): 1,
    ("send_receive.py", "('YD', 'TXT')"): 1,
    ("send_receive.py", "frozenset({'C'})"): 1,
    ("send_receive.py", "frozenset({'CTD', 'DD', 'DF'})"): 1,
    ("send_receive.py", "frozenset({'CTD', 'DS', 'DD', 'DH', 'DF', 'SD', 'TD', 'TXT'})"): 1,
    ("send_receive.py", "frozenset({'CTD', 'DS', 'DD', 'DH', 'DF', 'TD', 'SD', 'TXT'})"): 1,
    ("send_receive.py", "frozenset({'DD', 'CTD', 'DF', 'TXT'})"): 1,
    ("send_receive.py", "frozenset({'DD', 'CTD'})"): 1,
    ("send_receive.py", "frozenset({'DD', 'DF', 'CTD'})"): 1,
    ("send_receive.py", "frozenset({'DF'})"): 1,
    ("send_receive.py", "frozenset({'DH', 'XD', 'YD'})"): 1,
    ("send_receive.py", "frozenset({'DS', 'DD'})"): 1,
    ("send_receive.py", "frozenset({'DS', 'DH', 'SD', 'TD', 'YD', 'TXT'})"): 1,
    ("send_receive.py", "frozenset({'DS', 'DH', 'XD', 'YD', 'TD', 'SD', 'TXT'})"): 1,
    ("send_receive.py", "frozenset({'DS', 'TD', 'SD'})"): 1,
    ("send_receive.py", "frozenset({'TXT'})"): 1,
    ("send_receive.py", "frozenset({'Y', 'C'})"): 2,
    ("shift.py", "frozenset({'C'})"): 1,
    ("timer.py", "{'DS'}"): 1,
    ("timer.py", "{'T'}"): 1,
    ("timer.py", "{'TD'}"): 1,
}

VALUE_ERROR_ALLOWED: dict[Key, int] = {
    (
        "call.py",
        "CsvError(f('Could not read {token!r} as a Call instruction. Write it as call(\"name\"), with the subroutine name in double quotes.'))",
    ): 1,
    ("coil.py", "CsvError(f('Coil does not support keyword argument(s): {sorted(unknown)}'))"): 1,
    (
        "coil.py",
        "CsvError(f('Immediate must be an inner wrapper (e.g. out(immediate(Y1))): {token!r}'))",
    ): 1,
    ("coil.py", "CsvError(_COIL_FORM.format(token=token))"): 3,
    (
        "coil.py",
        "CsvError(f(\"Could not read the range in {token!r}. Write it as two addresses joined by '..', such as out(C1..C8).\"))",
    ): 1,
    (
        "coil.py",
        "CsvError(f(\"{token!r} writes a range with ':'. Write it with '..', such as out(C1..C8).\"))",
    ): 1,
    (
        "comparison.py",
        "CsvError(f('Could not read {token!r} as a compare contact. Write two operands joined by ==, !=, <, >, <= or >=, such as DS1==1.'))",
    ): 1,
    (
        "contact.py",
        "CsvError(f('{token!r} has a wire down, and a {class_name} holds no wire. Wrap the contact in a Tee, such as Tee({class_name}.from_csv_token({token[2:]!r})).'))",
    ): 1,
    (
        "__init__.py",
        "WriterError(f(\"Tee holds an UnknownCondition ({len(self.contact.raw)} bytes), and no CSV token holds one. Replace the contact, such as Tee(Contact('X001')).\"))",
    ): 1,
    ("copy.py", "WriterError(f('Unknown convert: {self.convert!r}'))"): 1,
    ("copy.py", "CsvError(f('Unsupported copy-family instruction: {call.name!r}'))"): 1,
    ("copy.py", "CsvError(f('{name} does not support keyword argument(s): {sorted(unknown)}'))"): 1,
    (
        "copy.py",
        "CsvError(f('blockcopy expects 2 positional args (src_range, dest_range), got {len(call.args)}'))",
    ): 1,
    (
        "copy.py",
        "CsvError(f('copy expects 2 positional args (source, dest), got {len(args)}: {token!r}'))",
    ): 1,
    (
        "copy.py",
        "CsvError(f('copy expects 2 positional args (source, dest), got {len(call.args)}'))",
    ): 1,
    (
        "copy.py",
        "CsvError(f('fill expects 2 positional args (value, dest_range), got {len(call.args)}'))",
    ): 1,
    ("copy.py", "CsvError(f('to_{fmt} options must be keyword arguments: {raw!r}'))"): 1,
    ("copy.py", "CsvError(f('to_{fmt} takes no arguments: {raw!r}'))"): 1,
    (
        "copy.py",
        "CsvError(f('{call.name} expects 2 positional args (source, dest_range), got {len(call.args)}'))",
    ): 1,
    (
        "copy.py",
        "CsvError(f('{call.name} expects 2 positional args (src_range, dest), got {len(call.args)}'))",
    ): 1,
    (
        "copy.py",
        "CsvError(f('Could not read convert={raw}. Write to_value, to_ascii, to_text(...) or to_binary(...), such as convert=to_value.'))",
    ): 1,
    (
        "copy.py",
        "CsvError(f('Could not read {token!r} as a copy. Write it as copy(source,dest), such as copy(DS1,DS2).'))",
    ): 1,
    (
        "copy.py",
        "CsvError(f(\"Could not read the range {arg!r}. Write the {role} of {name} as two addresses joined by '..', such as DS1..DS10.\"))",
    ): 1,
    (
        "copy.py",
        "CsvError(f(\"{arg!r} is not a range. Write the {role} of {name} as two addresses joined by '..', such as DS1..DS10.\"))",
    ): 1,
    (
        "counter.py",
        "EncodeError(f('Unsupported counter variant: {self.kind}(down={self.down_enabled}, reset={self.reset_enabled})'))",
    ): 1,
    (
        "counter.py",
        "CsvError(f('{kind} expects 2 positional args (done, accumulator), got {len(args)}: {token!r}'))",
    ): 1,
    ("counter.py", "CsvError(f('{kind} missing preset kwarg: {token!r}'))"): 1,
    ("counter.py", "CsvError(f('{self.kind} requires a .reset() pin row'))"): 1,
    (
        "counter.py",
        "CsvError(f('Could not read {token!r} as a counter. Write it as count_up(done,accumulator,preset=...) or count_down(...), such as count_up(CT1,CTD1,preset=100).'))",
    ): 1,
    ("drum.py", "CsvError('Drum requires a .reset() pin row')"): 1,
    ("drum.py", "CsvError('time_event_drum needs accumulator=')"): 1,
    ("drum.py", "CsvError(f('{call.name} needs unit='))"): 1,
    ("drum.py", "EncodeError(f('Unsupported {self.kind} unit: {self.unit!r}'))"): 1,
    ("drum.py", "EncodeError(str(exc))"): 1,
    (
        "drum.py",
        "CsvError(f('time_event_drum accumulator must be a TD address: {accumulator!r}'))",
    ): 1,
    (
        "drum.py",
        "CsvError(f('time_event_drum needs one preset and one event per step (None for unused): {len(presets)} presets, {len(events)} events'))",
    ): 1,
    (
        "drum.py",
        "CsvError(f('{val!r} is not a list. Write it in square brackets, such as [Y001,Y002].'))",
    ): 1,
    (
        "drum.py",
        "CsvError(f('{val!r} is not a pattern. Write one bracketed row of 0s and 1s per step, such as [[1,0],[0,1]].'))",
    ): 1,
    ("email.py", "CsvError(f('Not a raw Email token: {token!r}'))"): 1,
    ("email.py", "CsvError(f('Not an Email token: {token!r}'))"): 1,
    (
        "end.py",
        "CsvError(f('Could not read {token!r} as an End instruction. Write it as end().'))",
    ): 1,
    ("forloop.py", "CsvError(f('for does not support keyword argument(s): {sorted(unknown)}'))"): 1,
    ("forloop.py", "CsvError(_FOR_FORM.format(token=token))"): 2,
    (
        "forloop.py",
        "CsvError(f('Could not read {token!r} as a Break instruction. Write it as break().'))",
    ): 1,
    (
        "forloop.py",
        "CsvError(f('Could not read {token!r} as a Continue instruction. Write it as continue().'))",
    ): 1,
    (
        "forloop.py",
        "CsvError(f('Could not read {token!r} as a Next instruction. Write it as next().'))",
    ): 1,
    ("home.py", "CsvError(f('Not a Home token: {token!r}'))"): 1,
    ("home.py", "CsvError(f('Not a raw Home token: {token!r}'))"): 1,
    ("math.py", "CsvError(f(\"math mode must be 'decimal' or 'hex', got {mode_arg!r}\"))"): 1,
    (
        "math.py",
        "CsvError(f('math expects 2 positional args (expression, dest), got {len(call.args)}'))",
    ): 1,
    (
        "out_variant.py",
        "CsvError(f('{kind} does not support keyword argument(s): {sorted(unknown)}'))",
    ): 1,
    (
        "out_variant.py",
        "CsvError(f('{kind} missing keyword argument(s) {sorted(missing)}: {token!r}'))",
    ): 1,
    ("out_variant.py", "CsvError(f('{kind} needs a target operand: {token!r}'))"): 1,
    (
        "out_variant.py",
        'CsvError(f("Could not read {token!r} as a toggle, debounce, flasher or timed coil. Write the coil\'s address first, such as toggle(C1) or timed(C1,on_acc=TD1,on_preset=1000,unit=Tms)."))',
    ): 1,
    (
        "out_variant.py",
        'CsvError(f("Could not read {token!r}. After the coil\'s address, {kind} takes only keyword arguments, such as on_acc=TD1."))',
    ): 1,
    (
        "out_variant.py",
        'CsvError(f("Could not read {token!r}. toggle takes only the coil\'s address, such as toggle(C1) or toggle(immediate(Y001))."))',
    ): 1,
    ("position.py", "CsvError(f('Not a Position token: {token!r}'))"): 1,
    ("position.py", "CsvError(f('Not a raw Position token: {token!r}'))"): 1,
    ("return_.py", "CsvError('return expects no arguments')"): 1,
    (
        "return_.py",
        "CsvError(f('Could not read {token!r} as a Return instruction. Write it as return().'))",
    ): 1,
    ("send_receive.py", "CsvError(f('{call.name} needs a {name}= keyword'))"): 1,
    (
        "search.py",
        "CsvError(f('search expects 1 positional arg (expression), got {len(call.args)}'))",
    ): 1,
    (
        "search.py",
        "CsvError('search needs result= and found=, such as search(DS1..DS10 == DS20,result=DS30,found=C1).')",
    ): 1,
    (
        "search.py",
        "CsvError(f('Could not read the search expression {expr!r}. Write the table, an operator and a value, such as DS1..DS10 == DS20.'))",
    ): 1,
    ("shift.py", "CsvError(f('shift expects a range arg (start..end): {token!r}'))"): 1,
    ("shift.py", "CsvError(_SHIFT_FORM.format(token=token))"): 2,
    (
        "timer.py",
        "CsvError(f('{kind} expects 2 positional args (done, accumulator), got {len(args)}: {token!r}'))",
    ): 1,
    ("timer.py", "CsvError(f('{kind} missing preset or unit kwargs: {token!r}'))"): 1,
    (
        "timer.py",
        "CsvError(f('Could not read {token!r} as a timer. Write it as on_delay(done,accumulator,preset=...,unit=...) or off_delay(...), such as on_delay(T1,TD1,preset=1000,unit=Tms).'))",
    ): 1,
    ("velocity.py", "CsvError(f('Not a Velocity token: {token!r}'))"): 1,
    ("velocity.py", "CsvError(f('Not a raw Velocity token: {token!r}'))"): 1,
}

ALLOWED: dict[str, dict[Key, int]] = {
    "REGEX": REGEX_ALLOWED,
    "BANK_NAMES": BANK_NAMES_ALLOWED,
    "VALUE_ERROR": VALUE_ERROR_ALLOWED,
}


def _differences(kind: str) -> tuple[list[str], list[str]]:
    """Return the instances of ``kind`` that are not listed, and the listed ones that the code
    no longer has."""
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
from ..operands import banks as bank_module
from ..operands.banks import Bank, banks as bank_names, mask
from ..operands.banks import Bank as Flags
from ..model import Bank as Reexported

_HEX = re.compile(r"[0-9A-F]+h")
_WORD = regex.compile(r"[A-Z]*")
BITS = frozenset({"X", "Y"})
DEST = BITS | {"C"}
OPS = frozenset({"==", "!="})
WORDS = ("XD", "YD")
ROWS = ["DS", "DD"]
LIMITS = {"DS": 1, "DD": 2}
WIDE = bank_names(Bank.DD | Bank.DF)
NOT_BANKS = banks(0x40)
VIA_MODULE = bank_module.banks(Flags.DS | Flags.DH)
FLAGS = Flags.DD | Flags.DF
ONE = Flags.TXT
MODULE_FLAG = bank_module.Bank.CTD
MASKED = mask("DS", "DD")
NOT_FLAGS = Other.DD | Other.DF
VIA_MODEL = Reexported.SD
BY_VALUE = Flags(0x3f)
BY_NAME = Flags["DS"]
NESTED = bank_names(mask("DH"))
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


def parse(token):
    raise CsvError(f"Cannot parse {token!r}")


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
            ("raw.py", "bank_names(Bank.DD | Bank.DF)"): 1,
            ("raw.py", "bank_module.banks(Flags.DS | Flags.DH)"): 1,
            ("raw.py", "Flags.DD | Flags.DF"): 1,
            ("raw.py", "Flags.TXT"): 1,
            ("raw.py", "bank_module.Bank.CTD"): 1,
            ("raw.py", "mask('DS', 'DD')"): 1,
            ("raw.py", "Reexported.SD"): 1,
            ("raw.py", "Flags(63)"): 1,
            ("raw.py", "Flags['DS']"): 1,
            ("raw.py", "bank_names(mask('DH'))"): 1,
        }
    )
    # The scan skips the ValueError in find_blob_boundary, which BLOB_PARSE lists, and finds
    # the others.
    assert found["VALUE_ERROR"] == Counter(
        {
            ("raw.py", "ValueError"): 1,
            ("raw.py", "Refused(value)"): 1,
            ("raw.py", "WorseToken(f('bad {value!r:>4}'))"): 1,
            ("raw.py", "ValueError(f('bad {value!r}'))"): 1,
            ("raw.py", "CsvError(f('Cannot parse {token!r}'))"): 1,
        }
    )


def test_key_is_the_full_text() -> None:
    long = "x" * 200
    node = ast.parse(f"raise ValueError(f'{long} {{a}}')").body[0]
    assert isinstance(node, ast.Raise) and node.exc is not None
    assert _key(node.exc) == f"ValueError(f('{long} {{a}}'))"
