r"""Compare two JSON outputs of ``fixture_snapshot.py`` or ``operand_probe.py``.

Both tools write ``{"tool": ..., "meta": {...}, "cases": {key: value}}``. The first file is
the base and the second is the branch. The script compares ``cases`` value by value, and
values of different JSON types differ, so ``1``, ``1.0`` and ``true`` all differ. From
``meta`` it compares only ``scope``, such as the fixture root and ``--limit``. The rest of
``meta`` holds counts and summaries of ``cases``.

    uv run python -I devtools/identity_diff.py a.json b.json
    uv run python -I devtools/identity_diff.py --tiers [--expected FILE] a.json b.json

Without ``--tiers``, the script prints one line for each difference. It exits 1 if there is
a difference or the two files come from different tools, and 0 if the cases are identical.

With ``--tiers``, the script splits the differences into two tiers. The tools record an
exception as ``!Class`` in place of the result of the step that raised it. They record its
message in the case's ``errors`` list, as ``[class, message]``. They record a warning as
``Class: message``. The first tier is what must stay identical:

- every value of a case: accept or refuse, the exception class, the CSV written, the bytes
  and the decode result;
- the class of every exception and warning;
- each name ending in ``Error``, ``Exception`` or ``Warning`` that an exception's message
  holds;
- the set of cases. No case may be added or removed.

A case that differs only in the text of a message or a warning is listed separately and is
not a failure. A case whose first tier differs is a failure, unless an entry of the
expected-diff file allows it. That file is ``expected_diff.txt`` beside this script, or the
file given with ``--expected``. This mode exits 1 if there is a failure or the tools
differ, and 0 otherwise.

Both modes exit 2 without comparing when an input cannot be read or has no ``cases``
object, when either lists a ``meta.refused_baselines`` entry, when the scopes differ, or
when both have no cases. ``--tiers`` also exits 2 when the expected-diff file cannot be
read, and when a kind (b) entry matches a differing case whose base is not a crash.

The expected-diff file is plain text. A line that starts with ``#`` is a comment. Every
other line that is not blank is an entry, with its parts separated by `` | ``::

    <case key> | family=<family> | kind=<a or b> [| keys=<k>,<k>] [| new=<verdict>] | <reason>

- The key must match a whole case key. In the key, ``*`` stands for any run of characters
  other than ``/``, ``\*`` for a star and ``\\`` for a backslash.
- ``family`` names the instruction family that the entry belongs to: bits, data, flow, move
  or comm. Each family's change is made on its own branch.
- ``kind`` is ``a`` when CLICK shows that the base's verdict is wrong. A verdict is ``ok``,
  or a refusal with ``FieldError`` or ``AddressError``. ``kind`` is ``b`` when the base
  raised any other exception, which is a crash and not a verdict. A kind (b) entry must
  have ``new``.
- ``keys`` names the record keys (``new``, ``csv``, ...) in which the entry allows a
  first-tier difference. An entry without ``keys`` allows a difference in any key, and also
  allows a case that was added or removed.
- ``new`` names the verdict that the branch must give, such as ``ok`` or ``!FieldError``.
- The reason states the rule that the branch's verdict follows. Neither the key nor the
  reason may contain `` | ``. The reason must not start with ``<option>=`` or be an option
  name alone.

The script judges an entry only on a case whose key the entry matches and whose first tier
differs (:meth:`Expected.judge`). The dry run in ``classify_dryrun.py`` judges entries the
same way. The entry allows the case when each of these conditions that applies holds:

- Kind (b): both sides have the case, and the base's ``new`` is a crash. A crash is
  ``!<Class>`` where Class is neither ``FieldError`` nor ``AddressError``. Every differing
  key that the base holds also records a crash. A differing key that the base lacks is one
  that the crash left out. If both sides have the case and these conditions fail, the entry
  is misused, and the run reports it and exits 2.
- ``new``: the branch's whole record shows the verdict, not only its ``new``. For ``ok``,
  the record has no ``errors``, ``read`` and ``dec`` are ``=``, and ``tag``, if the record
  has one, does not end in `` None``, ``!<Class>`` or `` refused[<fields>]``. For ``!X``,
  ``new`` and ``read`` are ``!X``, every class in ``errors`` is X, ``dec`` is
  ``= refused[<fields>]`` or ``None``, and ``tag``, if the record has one, ends in
  `` refused[<fields>]`` or `` None``. `` refused[<fields>]`` means that the blob decoder
  built the instruction and the instruction holds the refusal. `` None`` means that the
  decoder returned no instruction, because no decoded instruction can hold the value. In
  the dry run, a record holds only ``new``, so there the check covers only ``new``.
- ``keys``: both sides have the case, and every differing key is named in ``keys``.

The script lists each entry that allows no case as matching no difference. That is never
an error.
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
    """Return the two outputs, or the exit status if they cannot be compared."""
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
    """Print the differences between two tool outputs, and return the exit status.

    The status is 0 if the cases are identical, and 1 if they differ or the tools differ. It
    is 2 if the outputs cannot be compared. That happens when a file cannot be read or has
    no ``cases``, when either lists a refused probe baseline, when the scopes differ, or when
    neither has any cases.
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

#: Matches a class name in an exception message, such as an exception that the message
#: names or wraps.
_INNER_CLASS = re.compile(r"\b[A-Z][A-Za-z0-9_]*(?:Error|Exception|Warning)\b")

#: The record keys whose list holds ``<WarningClass>: <message>`` strings.
_WARNING_KEYS = ("warn", "warnings", "write_warn")

#: The expected-diff file read by default.
EXPECTED = Path(__file__).resolve().parent / "expected_diff.txt"

#: The instruction families that an expected-diff entry can belong to.
FAMILIES = ("bits", "data", "flow", "move", "comm")

#: The exception classes that record a refusal of a field value, which is a verdict. Any
#: other exception class records a crash.
VERDICT_CLASSES = frozenset({"FieldError", "AddressError"})

#: The parts an entry may hold between its key and its reason.
_OPTIONS = ("family", "kind", "keys", "new")


def first_tier(record: Any) -> Any:
    """Return the first tier of one case: ``record`` without its message text.

    Each exception in ``errors`` becomes its class and the class names that its message
    holds. Each warning becomes its class. Every other value is unchanged.
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
    """Return the regular expression for the case-key pattern ``key``.

    In ``key``, ``*`` is any run of characters other than ``/``, ``\\*`` is a star and
    ``\\\\`` is a backslash. Any other character stands for itself, and so does a lone
    backslash.
    """
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
    """The result of judging an expected-diff entry on one differing case."""

    #: True if the entry allows the case.
    allowed: bool
    #: Why the entry is misused on the case, or empty if it is not misused.
    problem: str = ""


class Expected(NamedTuple):
    """One entry of the expected-diff file."""

    line: int
    key: str
    reason: str
    #: The instruction family that the entry belongs to, one of :data:`FAMILIES`.
    family: str
    #: ``a`` (CLICK shows the base verdict is wrong) or ``b`` (the base crashed).
    kind: str
    #: The record keys in which the entry allows a first-tier difference. Empty allows any key.
    fields: tuple[str, ...] = ()
    #: The verdict that the branch must give, or ``None`` to allow any verdict.
    new: str | None = None

    def matches(self, case_key: str) -> bool:
        return _pattern(self.key).fullmatch(case_key) is not None

    def judge(self, base: Any, branch: Any, verdict_only: bool = False) -> Judgement:
        """Judge a case that the entry matches and whose first tier differs.

        Return a :class:`Judgement` that says whether the entry allows the case. ``base`` and
        ``branch`` are the case's two records, and ``None`` stands for a side that lacks the
        case. Set ``verdict_only`` when the records hold only ``new``, as the dry run's
        records do. A ``new`` pin then checks only ``new``.
        """
        differing = _differing(base, branch)
        if self.kind == "b":
            if not (isinstance(base, dict) and isinstance(branch, dict)):
                return Judgement(False)  # an added or removed case has no crash to replace
            crash = _not_a_crash(base, differing)
            if crash:
                return Judgement(False, f"line {self.line}: {self.key}: {crash}")
        if self.new is not None and not _pinned(branch, self.new, verdict_only):
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
    """Return the entry on one line of the expected-diff file.

    Raise :class:`ValueError` with a message that says what is wrong if the line is malformed.
    """
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
    """Return the class of the crash that ``value`` records, or ``None`` if it records none.

    A text value records a crash when its last word is ``!<Class>`` and Class is neither
    ``FieldError`` nor ``AddressError``.
    """
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"(?:.* )?!(\w+)", value, re.DOTALL)
    if match is None or match.group(1) in VERDICT_CLASSES:
        return None
    return match.group(1)


def _holds_crash(value: Any) -> bool:
    """Return True if a recorded value is a crash.

    The value is a crash if it is text that ends in a crash ``!<Class>``, which may follow a
    prefix such as a tag number. It is also a crash if it is an ``errors`` list that is not
    empty and in which every class is a crash.
    """
    if isinstance(value, list):
        return bool(value) and all(
            isinstance(error, list) and error and _crash_class(f"!{error[0]}") for error in value
        )
    return _crash_class(value) is not None


def _not_a_crash(base: dict[str, Any], differing: set[str] | None) -> str:
    """Return why a kind (b) entry cannot cover the base record, or empty text if it can."""
    new = base.get("new")
    if _crash_class(new) is None or new != f"!{_crash_class(new)}":
        return f"the base gives new={new!r}, not a crash"
    for key in sorted(differing if differing is not None else base):
        if key in base and not _holds_crash(base[key]):
            return f"the base's {key} differs and is {_short(base[key], 80)}, not a crash"
    return ""


def _pinned(branch: Any, pin: str, verdict_only: bool = False) -> bool:
    """Return True if the branch record shows the verdict ``pin``.

    The whole record must show the verdict, not only its ``new``. With ``verdict_only``,
    only ``new`` is checked.
    """
    if not isinstance(branch, dict) or branch.get("new") != pin:
        return False
    if verdict_only:
        return True
    errors = branch.get("errors") or []
    classes = {error[0] if isinstance(error, list) and error else None for error in errors}
    tag = branch.get("tag")
    if pin == "ok":
        refused = isinstance(tag, str) and re.search(_REFUSED_TAG, tag) is not None
        return not classes and not refused and branch.get("read") == branch.get("dec") == "="
    dec = branch.get("dec")
    return (
        classes <= {pin[1:]}
        and (tag is None or (isinstance(tag, str) and re.search(_HELD_OR_NONE, tag) is not None))
        and branch.get("read") == pin
        and (dec == "None" or (isinstance(dec, str) and re.fullmatch(_HELD_SAME, dec) is not None))
    )


#: Matches a ``tag`` value whose blob the decoder refused. The decoder returned no
#: instruction, raised, or built an instruction that holds a refusal.
_REFUSED_TAG = r"(?: None|!\w+| refused\[[^\]]+\])\Z"
#: Matches a ``tag`` value for a refused value. The decoder built an instruction that holds
#: the refusal, or returned no instruction.
_HELD_OR_NONE = r"(?: None| refused\[[^\]]+\])\Z"
#: Matches a ``dec`` value for a refused value. The decoder built the instruction as written
#: (``=``), and the instruction holds the refusal.
_HELD_SAME = r"= refused\[[^\]]+\]"


def read_expected(path: str | Path) -> list[Expected]:
    """Return the entries of an expected-diff file.

    Raise :class:`ValueError`, naming the line, at the first malformed line.
    """
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
    """Return the record keys whose first tier differs, or ``None`` unless both are records."""
    if not (isinstance(a, dict) and isinstance(b, dict)):
        return None
    ta, tb = first_tier(a), first_tier(b)
    return {k for k in set(ta) | set(tb) if diff_cases({"k": ta.get(k)}, {"k": tb.get(k)})}


def _print_cases(cases: dict[str, list[str]], indent: str) -> None:
    for lines in cases.values():
        for line in lines:
            print(f"{indent}{line}")


def diff_tiers(path_a: str | Path, path_b: str | Path, expected_path: str | Path = EXPECTED) -> int:
    """Print the differences between two tool outputs in two tiers, and return the exit status.

    The status is 0 if every case that differs beyond its message text is allowed by an
    expected-diff entry. It is 1 if such a case is not allowed, or if the tools differ. It is
    2 if the outputs cannot be compared, if the expected-diff file cannot be read, or if an
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
    """Print to stderr each differing case on which an entry was misused."""
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
