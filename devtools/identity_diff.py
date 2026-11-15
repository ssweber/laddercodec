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
the bytes, the decode result), the class of every exception and warning, the class names
an exception's message holds, and no case added or removed.  A case that differs only in
message or warning text is listed apart and is not a failure.  A case whose first tier
differs is a failure unless an entry of the expected-diff file (``--expected``, default
``expected_diff.txt`` beside this script) allows it.  The mode exits 1 on a failure or when
the tools differ, 0 otherwise.

Both modes exit 2 without comparing when an input cannot be read or has no ``cases``
object, when either lists a ``meta.refused_baselines`` entry, when the scopes differ, or
when both have no cases; ``--tiers`` also when the expected-diff file cannot be read.

The expected-diff file is plain text: a line starting with ``#`` is a comment, and every
other non-blank line is ``<case key> | <reason>`` or ``<case key> | keys=<k>,<k> | <reason>``.
The key matches a case key whole: ``*`` stands for any run of characters, ``\*`` for a
star and ``\\`` for a backslash.  With ``keys=``, the entry allows a first-tier
difference in those record keys only (``new``, ``csv``, ...); without, in any, and a case
added or removed.  The reason states the rule the new verdict follows.
"""

from __future__ import annotations

import argparse
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
_WARNING_KEYS = ("warn", "warnings")

#: The expected-diff file read by default.
EXPECTED = Path(__file__).resolve().parent / "expected_diff.txt"


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


def _pattern(key: str) -> re.Pattern[str]:
    """A case-key pattern: ``*`` is any run of characters, ``\\*`` a star, ``\\\\`` a
    backslash; any other character, a lone backslash included, stands for itself."""
    out: list[str] = []
    index = 0
    while index < len(key):
        char = key[index]
        follow = key[index + 1 : index + 2]
        if char == "\\" and follow in ("*", "\\"):
            out.append(re.escape(follow))
            index += 2
            continue
        out.append(".*" if char == "*" else re.escape(char))
        index += 1
    return re.compile("".join(out), re.DOTALL)


class Expected(NamedTuple):
    """One entry of the expected-diff file."""

    line: int
    key: str
    reason: str
    #: The record keys whose first-tier difference the entry allows; empty for all.
    fields: tuple[str, ...] = ()

    def matches(self, case_key: str) -> bool:
        return _pattern(self.key).fullmatch(case_key) is not None

    def allows(self, differing: set[str] | None) -> bool:
        """Whether the entry allows a case whose first tier differs in ``differing`` keys
        (``None``: the case was added or removed, or is not a record)."""
        if not self.fields:
            return True
        return differing is not None and differing <= set(self.fields)

    def label(self) -> str:
        keys = f" | keys={','.join(self.fields)}" if self.fields else ""
        return f"{self.key}{keys} | {self.reason}"


def read_expected(path: str | Path) -> list[Expected]:
    """The entries of an expected-diff file; :class:`ValueError` names a malformed line."""
    entries: list[Expected] = []
    with open(path, encoding="utf-8") as handle:
        for number, raw in enumerate(handle, 1):
            text = raw.strip()
            if not text or text.startswith("#"):
                continue
            head, sep, reason = text.rpartition(" | ")
            fields: tuple[str, ...] = ()
            rest, mid, last = head.rpartition(" | ")
            if mid and last.startswith("keys="):
                head = rest
                fields = tuple(f.strip() for f in last[len("keys=") :].split(","))
                if not all(fields):
                    raise ValueError(f"{path}:{number}: an empty name in {last!r}")
            if not sep or not head.strip() or not reason.strip():
                raise ValueError(
                    f"{path}:{number}: not '<case key> [| keys=<k>,...] | <reason>': {text!r}"
                )
            entries.append(Expected(number, head.strip(), reason.strip(), fields))
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
    or the tools differ; 2: not comparable, or the expected-diff file cannot be read.
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
        differing = _differing(a.get(key), b.get(key)) if key in a and key in b else None
        entry = next((e for e in entries if e.matches(key) and e.allows(differing)), None)
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
    return 1 if failures else 0


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
