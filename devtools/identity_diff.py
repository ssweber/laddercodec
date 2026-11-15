r"""Compare two JSON outputs of ``fixture_snapshot.py`` or ``operand_probe.py``.

Both tools write ``{"tool": ..., "meta": {...}, "cases": {key: value}}``.  ``cases`` is
compared value by value, with the JSON type counted (``1``, ``1.0`` and ``true`` differ).
Of ``meta``, only ``scope`` (fixture root, ``--limit``) is checked: the rest holds counts
and summaries derived from ``cases``.

    uv run python -I devtools/identity_diff.py a.json b.json
    uv run python -I devtools/identity_diff.py --tiers [--expected FILE] a.json b.json

Plain, it prints one line per difference and exits 1 if there is any or the two come from
different tools, 0 if the cases are identical.

``--tiers`` sorts the differences by case.  The tools record an exception as
``!Class`` where it happened and its message under the case's ``errors``, as
``[class, message]``; a warning is ``Class: message``.  The first tier must stay
identical: every value of a case (accept or refuse, the exception class, the CSV written,
the bytes, the decode result), the class of every exception and warning, each name ending
in ``Error``, ``Exception`` or ``Warning`` that an exception's message holds, and no case
added or removed.  A case that differs only in message or warning text is listed apart and
is not a failure.  A case whose first tier differs is a failure unless an entry of the
expected-diff file (``--expected``, default ``expected_diff.txt`` beside this script)
allows it.  The mode exits 1 on a failure or when the tools differ, 0 otherwise.

Both modes exit 2 without comparing when an input cannot be read or has no ``cases``
object, when either lists a ``meta.refused_baselines`` entry, when the scopes differ, or
when both have no cases.  ``--tiers`` also exits 2 when the expected-diff file cannot be
read, and when a kind (b) entry matches a differing case whose base is not a crash.

The expected-diff file is plain text: a line starting with ``#`` is a comment, and every
other non-blank line is an entry, its parts separated by `` | ``::

    <case key> | family=<family> | kind=<a or b> [| keys=<k>,<k>] [| new=<verdict>] | <reason>

- The key matches a case key whole: ``*`` stands for any run of characters other than
  ``/``, ``\*`` for a star and ``\\`` for a backslash.
- ``family`` names the family branch the entry belongs to (bits, data, flow, move, comm).
- ``kind`` is ``a`` when CLICK shows the base verdict is wrong, ``b`` when the base raised
  something other than a ``FieldError`` or ``AddressError``: a crash, not a verdict.  A
  kind (b) entry needs ``new``.
- ``keys`` names the record keys (``new``, ``csv``, ...) whose first-tier difference the
  entry allows; without it the entry allows any, and a case added or removed.
- ``new`` pins the branch's ``new`` value the entry allows (``ok``, ``!FieldError``, ...).
- The reason states the rule the new verdict follows.  Neither key nor reason holds `` | ``,
  and the reason does not start with an option name.

An entry is judged only on a case whose key it matches and whose first tier differs
(:meth:`Expected.judge`), and the dry run judges it the same way.  It allows the case when:

- for kind (b), both sides have the case, the base's ``new`` is a crash (``!<Class>``, Class
  neither ``FieldError`` nor ``AddressError``), and every differing key the base holds is a
  crash too (a key the base lacks is one the crash left out).  When both sides have the
  case but this does not hold, the entry is misused: the run reports it and exits 2;
- with ``new``, the branch's ``new`` is the pin, and its ``read`` and ``dec``, when it has
  them, agree: ``=`` for ``ok``; for ``!X``, ``read`` is ``!X`` and ``dec`` is ``None``
  (the blob decoder refuses the value);
- with ``keys``, both sides have the case and the differing keys are among them.

An entry that allows no case is listed as matching no difference, which is never an error.
"""

from __future__ import annotations

import argparse
import functools
import json
import re
import sys
from pathlib import Path
from typing import Any, NamedTuple


def _short(value: Any, width: int = 400) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return text if len(text) <= width else text[: width - 3] + "..."


def _walk(path: str, a: Any, b: Any, out: list[str]) -> None:
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b), key=str):
            sub = f"{path}.{key}"
            if key not in b:
                out.append(f"- {sub}: {_short(a[key])}")
            elif key not in a:
                out.append(f"+ {sub}: {_short(b[key])}")
            else:
                _walk(sub, a[key], b[key], out)
        return
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for index, (x, y) in enumerate(zip(a, b, strict=True)):
            _walk(f"{path}[{index}]", x, y, out)
        return
    if type(a) is not type(b) or a != b:
        out.append(f"~ {path}: {_short(a)} -> {_short(b)}")


def diff_cases(a: dict[str, Any], b: dict[str, Any]) -> list[str]:
    """Return one line per difference between two ``cases`` dicts."""
    out: list[str] = []
    for key in sorted(set(a) | set(b)):
        if key not in b:
            out.append(f"- {key}: {_short(a[key])}")
        elif key not in a:
            out.append(f"+ {key}: {_short(b[key])}")
        else:
            _walk(key, a[key], b[key], out)
    return out


def _load(path_a: str | Path, path_b: str | Path) -> tuple[dict, dict] | int:
    """The two outputs, or the exit status when they cannot be compared."""
    docs = []
    for path in (path_a, path_b):
        try:
            with open(path, encoding="utf-8") as handle:
                docs.append(json.load(handle))
        except (OSError, ValueError) as exc:
            print(f"cannot read {path}: {exc}", file=sys.stderr)
            return 2
    for path, doc in zip((path_a, path_b), docs, strict=True):
        if not isinstance(doc, dict) or not isinstance(doc.get("cases"), dict):
            print(f"{path} is not a tool output: no 'cases' object", file=sys.stderr)
            return 2
        refused = (doc.get("meta") or {}).get("refused_baselines")
        if refused:
            print(
                f"{path}: the tree refused probe baseline(s) {', '.join(map(str, refused))}; "
                "their cases are not a valid comparison",
                file=sys.stderr,
            )
            return 2
    a, b = docs
    if a.get("tool") != b.get("tool"):
        print(f"tool differs: {a.get('tool')!r} vs {b.get('tool')!r}")
        return 1
    scope_a = a.get("meta", {}).get("scope")
    scope_b = b.get("meta", {}).get("scope")
    if scope_a != scope_b:
        print(f"scope differs, the outputs are not comparable: {scope_a!r} vs {scope_b!r}")
        return 2
    if not a["cases"] and not b["cases"]:
        print("both outputs have no cases: nothing was compared", file=sys.stderr)
        return 2
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")  # ty: ignore[not-callable]
    return a, b


def diff_files(path_a: str | Path, path_b: str | Path) -> int:
    """Print the differences between two tool outputs; return the exit status.

    0: identical cases; 1: differences or different tools; 2: not comparable (unreadable,
    no ``cases``, a refused probe baseline, different scope, or no cases on either side).
    """
    loaded = _load(path_a, path_b)
    if isinstance(loaded, int):
        return loaded
    a, b = loaded
    lines = diff_cases(a["cases"], b["cases"])
    for line in lines:
        print(line)
    print(f"{len(lines)} difference(s) in {len(a['cases'])} vs {len(b['cases'])} cases")
    return 1 if lines else 0


# ---------------------------------------------------------------------------
# Two tiers
# ---------------------------------------------------------------------------

#: A class name inside an exception message (an exception a message names or wraps).
_INNER_CLASS = re.compile(r"\b[A-Z][A-Za-z0-9_]*(?:Error|Exception|Warning)\b")

#: Case keys whose list holds ``<WarningClass>: <message>`` strings.
_WARNING_KEYS = ("warn", "warnings", "write_warn")

#: The expected-diff file read by default.
EXPECTED = Path(__file__).resolve().parent / "expected_diff.txt"

#: The family branches an expected-diff entry can belong to.
FAMILIES = ("bits", "data", "flow", "move", "comm")

#: The exception classes that are a field's verdict; any other is a crash.
VERDICT_CLASSES = frozenset({"FieldError", "AddressError"})

#: The parts an entry may hold between its key and its reason.
_OPTIONS = ("family", "kind", "keys", "new")


def first_tier(record: Any) -> Any:
    """What of one case must stay identical: ``record`` without message text.

    An exception in ``errors`` keeps its class and the class names its message holds; a
    warning keeps its class.  Every other value stays whole.
    """
    if not isinstance(record, dict):
        return record
    out = dict(record)
    errors = out.get("errors")
    if isinstance(errors, list):
        out["errors"] = [
            [error[0], _INNER_CLASS.findall(error[1])]
            if isinstance(error, list) and len(error) == 2 and isinstance(error[1], str)
            else error
            for error in errors
        ]
    for key in _WARNING_KEYS:
        items = out.get(key)
        if isinstance(items, list):
            out[key] = [item.split(": ", 1)[0] if isinstance(item, str) else item for item in items]
    return out


@functools.cache
def _pattern(key: str) -> re.Pattern[str]:
    """A case-key pattern: ``*`` is any run of characters other than ``/``, ``\\*`` a star,
    ``\\\\`` a backslash; any other character, a lone backslash included, stands for
    itself."""
    out: list[str] = []
    index = 0
    while index < len(key):
        char = key[index]
        follow = key[index + 1 : index + 2]
        if char == "\\" and follow in ("*", "\\"):
            out.append(re.escape(follow))
            index += 2
            continue
        out.append("[^/]*" if char == "*" else re.escape(char))
        index += 1
    return re.compile("".join(out), re.DOTALL)


class Judgement(NamedTuple):
    """What an entry says of one differing case."""

    #: The entry allows the case.
    allowed: bool
    #: Why the entry cannot be used on the case at all; empty when it can.
    problem: str = ""


class Expected(NamedTuple):
    """One entry of the expected-diff file."""

    line: int
    key: str
    reason: str
    #: The family branch the entry belongs to, one of :data:`FAMILIES`.
    family: str
    #: ``a`` (CLICK shows the base verdict is wrong) or ``b`` (the base crashed).
    kind: str
    #: The record keys whose first-tier difference the entry allows; empty for all.
    fields: tuple[str, ...] = ()
    #: The branch's ``new`` value the entry allows; ``None`` for any.
    new: str | None = None

    def matches(self, case_key: str) -> bool:
        return _pattern(self.key).fullmatch(case_key) is not None

    def judge(self, base: Any, branch: Any) -> Judgement:
        """Whether the entry allows a case whose key it matches and whose first tier differs;
        ``base`` and ``branch`` are the case's records, ``None`` on a side that lacks it."""
        differing = _differing(base, branch)
        if self.kind == "b":
            if not (isinstance(base, dict) and isinstance(branch, dict)):
                return Judgement(False)  # a case added or removed replaces no crash
            crash = _not_a_crash(base, differing)
            if crash:
                return Judgement(False, f"line {self.line}: {self.key}: {crash}")
        if self.new is not None and not _pinned(branch, self.new):
            return Judgement(False)
        if self.fields and (differing is None or not differing <= set(self.fields)):
            return Judgement(False)
        return Judgement(True)

    def label(self) -> str:
        parts = [self.key, f"family={self.family}", f"kind={self.kind}"]
        if self.fields:
            parts.append(f"keys={','.join(self.fields)}")
        if self.new is not None:
            parts.append(f"new={self.new}")
        return " | ".join([*parts, self.reason])


def _entry(path: str | Path, number: int, text: str) -> Expected:
    """One entry line; :class:`ValueError` says what is wrong with it."""
    where = f"{path}:{number}"
    parts = [part.strip() for part in text.split(" | ")]
    if len(parts) < 2 or not parts[0] or not parts[-1]:
        raise ValueError(f"{where}: not '<case key> | <option>=<value> ... | <reason>': {text!r}")
    options: dict[str, str] = {}
    for part in parts[1:-1]:
        name, eq, value = part.partition("=")
        if not eq or name not in _OPTIONS:
            raise ValueError(f"{where}: {part!r} is not <option>=<value> for one of {_OPTIONS}")
        if name in options:
            raise ValueError(f"{where}: {name}= appears twice")
        if not value:
            raise ValueError(f"{where}: {name}= has no value")
        options[name] = value
    family = options.get("family")
    if family not in FAMILIES:
        raise ValueError(f"{where}: family= is one of {', '.join(FAMILIES)}, not {family!r}")
    kind = options.get("kind")
    if kind not in ("a", "b"):
        raise ValueError(f"{where}: kind= is a or b, not {kind!r}")
    fields: tuple[str, ...] = ()
    if "keys" in options:
        fields = tuple(f.strip() for f in options["keys"].split(","))
        if not all(fields):
            raise ValueError(f"{where}: an empty name in keys={options['keys']}")
    if kind == "b" and "new" not in options:
        raise ValueError(f"{where}: a kind (b) entry states its new verdict with new=")
    reason = parts[-1]
    if reason.partition("=")[0] in _OPTIONS:
        raise ValueError(f"{where}: no reason after the options: {reason!r} is an option")
    return Expected(number, parts[0], reason, family, kind, fields, options.get("new"))


def _crash_class(value: Any) -> str | None:
    """The class of a recorded crash: the last word of a text value when it is
    ``!<Class>`` and Class is not a field's verdict; ``None`` otherwise."""
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"(?:.* )?!(\w+)", value, re.DOTALL)
    if match is None or match.group(1) in VERDICT_CLASSES:
        return None
    return match.group(1)


def _holds_crash(value: Any) -> bool:
    """Whether a recorded value is a crash: ``!<Class>`` (after a tag prefix), or an
    ``errors`` list whose every class is one."""
    if isinstance(value, list):
        return bool(value) and all(
            isinstance(error, list) and error and _crash_class(f"!{error[0]}") for error in value
        )
    return _crash_class(value) is not None


def _not_a_crash(base: dict[str, Any], differing: set[str] | None) -> str:
    """Why a base record is not a crash a kind (b) entry may cover; empty when it is."""
    new = base.get("new")
    if _crash_class(new) is None or new != f"!{_crash_class(new)}":
        return f"the base gives new={new!r}, not a crash"
    for key in sorted(differing if differing is not None else base):
        if key in base and not _holds_crash(base[key]):
            return f"the base's {key} differs and is {_short(base[key], 80)}, not a crash"
    return ""


def _pinned(branch: Any, pin: str) -> bool:
    """Whether a branch record gives ``pin`` as its ``new``, with ``read`` and ``dec``
    (when it has them) agreeing."""
    if not isinstance(branch, dict) or branch.get("new") != pin:
        return False
    read, dec = ("=", "=") if pin == "ok" else (pin, "None")
    return branch.get("read", read) == read and branch.get("dec", dec) == dec


def read_expected(path: str | Path) -> list[Expected]:
    """The entries of an expected-diff file; :class:`ValueError` names a malformed line."""
    entries: list[Expected] = []
    with open(path, encoding="utf-8") as handle:
        for number, raw in enumerate(handle, 1):
            text = raw.strip()
            if text and not text.startswith("#"):
                entries.append(_entry(path, number, text))
    return entries


def _one(cases: dict[str, Any], key: str, tier: bool) -> dict[str, Any]:
    if key not in cases:
        return {}
    return {key: first_tier(cases[key]) if tier else cases[key]}


def _differing(a: Any, b: Any) -> set[str] | None:
    """The record keys whose first tier differs; ``None`` unless both are records."""
    if not (isinstance(a, dict) and isinstance(b, dict)):
        return None
    ta, tb = first_tier(a), first_tier(b)
    return {k for k in set(ta) | set(tb) if diff_cases({"k": ta.get(k)}, {"k": tb.get(k)})}


def _print_cases(cases: dict[str, list[str]], indent: str) -> None:
    for lines in cases.values():
        for line in lines:
            print(f"{indent}{line}")


def diff_tiers(path_a: str | Path, path_b: str | Path, expected_path: str | Path = EXPECTED) -> int:
    """Print the differences between two tool outputs in two tiers; return the exit status.

    0: no case differs beyond its messages, apart from expected-diff entries; 1: one does,
    or the tools differ; 2: not comparable, the expected-diff file cannot be read, or an
    entry is misused on a differing case (:meth:`Expected.judge`).
    """
    try:
        entries = read_expected(expected_path)
    except (OSError, ValueError) as exc:
        print(f"cannot read the expected-diff file: {exc}", file=sys.stderr)
        return 2
    loaded = _load(path_a, path_b)
    if isinstance(loaded, int):
        return loaded
    a, b = loaded[0]["cases"], loaded[1]["cases"]
    problems: list[str] = []
    failures: dict[str, list[str]] = {}
    expected: dict[Expected, dict[str, list[str]]] = {}
    messages: dict[str, list[str]] = {}
    for key in sorted(set(a) | set(b)):
        raw = diff_cases(_one(a, key, False), _one(b, key, False))
        if not raw:
            continue
        lines = diff_cases(_one(a, key, True), _one(b, key, True))
        if not lines:
            messages[key] = raw
            continue
        entry = None
        for candidate in entries:
            if not candidate.matches(key):
                continue
            judgement = candidate.judge(a.get(key), b.get(key))
            if judgement.problem:
                problems.append(f"{key}: {judgement.problem}")
            elif judgement.allowed and entry is None:
                entry = candidate
        if entry is None:
            failures[key] = lines
        else:
            expected.setdefault(entry, {})[key] = lines
    print(f"must stay identical: {len(failures)} case(s) differ")
    _print_cases(failures, "  ")
    count = sum(len(cases) for cases in expected.values())
    print(f"allowed by expected-diff entries ({expected_path}): {count} case(s)")
    for entry, cases in expected.items():
        print(f"  {entry.label()}")
        _print_cases(cases, "    ")
    print(f"message wording only: {len(messages)} case(s)")
    _print_cases(messages, "  ")
    unused = [e for e in entries if e not in expected]
    if unused:
        print(f"expected-diff entries that match no difference: {len(unused)}")
        for e in unused:
            print(f"  line {e.line}: {e.key}")
    print(
        f"{len(failures)} failure(s), {count} expected, {len(messages)} message-only "
        f"case(s) in {len(a)} vs {len(b)} cases"
    )
    if problems:
        print_problems(problems, expected_path)
        return 2
    return 1 if failures else 0


def print_problems(problems: list[str], expected_path: str | Path) -> None:
    """Report the entries misused on a differing case (to stderr)."""
    print(
        f"{expected_path}: {len(problems)} differing case(s) an entry matches but cannot "
        "cover (a kind (b) entry covers only a base that crashed):",
        file=sys.stderr,
    )
    for problem in problems:
        print(f"  {problem}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("a", help="base output")
    parser.add_argument("b", help="branch output")
    parser.add_argument("--tiers", action="store_true", help="list message-only changes apart")
    parser.add_argument(
        "--expected", type=Path, help=f"expected-diff file for --tiers (default {EXPECTED.name})"
    )
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    if args.expected is not None and not args.tiers:
        parser.error("--expected needs --tiers")
    if args.tiers:
        return diff_tiers(args.a, args.b, args.expected or EXPECTED)
    return diff_files(args.a, args.b)


if __name__ == "__main__":
    raise SystemExit(main())
