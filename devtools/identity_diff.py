"""Compare two JSON outputs of ``fixture_snapshot.py`` or ``operand_probe.py``.

Both tools write ``{"tool": ..., "meta": {...}, "cases": {key: value}}``.  ``cases`` is
compared value by value, with the JSON type counted (``1``, ``1.0`` and ``true`` differ).
Of ``meta``, only ``scope`` (fixture root, ``--limit``) is checked: the rest holds counts
and summaries derived from ``cases``.

    uv run python -I devtools/identity_diff.py a.json b.json
    uv run python -I devtools/identity_diff.py --tiers [--expected FILE] a.json b.json

Plain, it prints one line per difference and exits 1 if there is any or the two come from
different tools, 0 if the cases are identical.

``--tiers`` sorts the differences by case.  The tools record an exception as
``!Class: message``.  With the message cut off, every case must stay identical: accept or
refuse, the exception class, the CSV written, the bytes, the decode result, and no case
added or removed.  A case that differs only in a message is listed apart and is not a
failure.  A case that differs in more is a failure unless the expected-diff file
(``--expected``, default ``expected_diff.txt`` beside this script) lists it.  The mode exits
1 on a failure or when the tools differ, 0 otherwise.

Both modes exit 2 without comparing when an input cannot be read or has no ``cases``
object, when either lists a ``meta.refused_baselines`` entry, when the scopes differ, or
when both have no cases; ``--tiers`` also when the expected-diff file cannot be read.

The expected-diff file is plain text: a line starting with ``#`` is a comment, and every
other non-blank line is ``<case key> | <reason>``.  The key matches a case key whole; ``*``
in it stands for any run of characters.  The reason states the rule the new verdict follows.
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

#: An exception as the tools record it, ``!Class: message``; the message runs to the end of
#: the string.  A lowercase word after ``!`` (``!value:``, ``!probe:``) is the probe's own
#: note, kept whole up to the exception it holds.
_ERROR = re.compile(r"!([A-Z][A-Za-z0-9_]*): .*", re.DOTALL)

#: The expected-diff file read by default.
EXPECTED = Path(__file__).resolve().parent / "expected_diff.txt"


def without_messages(value: Any) -> Any:
    """``value`` with every recorded exception cut to ``!Class``."""
    if isinstance(value, str):
        return _ERROR.sub(lambda m: f"!{m.group(1)}", value, count=1)
    if isinstance(value, dict):
        return {key: without_messages(item) for key, item in value.items()}
    if isinstance(value, list):
        return [without_messages(item) for item in value]
    return value


class Expected(NamedTuple):
    """One entry of the expected-diff file."""

    line: int
    key: str
    reason: str

    def matches(self, case_key: str) -> bool:
        pattern = ".*".join(re.escape(part) for part in self.key.split("*"))
        return re.fullmatch(pattern, case_key, re.DOTALL) is not None


def read_expected(path: str | Path) -> list[Expected]:
    """The entries of an expected-diff file; :class:`ValueError` names a malformed line."""
    entries: list[Expected] = []
    with open(path, encoding="utf-8") as handle:
        for number, raw in enumerate(handle, 1):
            text = raw.strip()
            if not text or text.startswith("#"):
                continue
            key, sep, reason = text.rpartition(" | ")
            if not sep or not key.strip() or not reason.strip():
                raise ValueError(f"{path}:{number}: not '<case key> | <reason>': {text!r}")
            entries.append(Expected(number, key.strip(), reason.strip()))
    return entries


def _one(cases: dict[str, Any], key: str, normalize: bool) -> dict[str, Any]:
    if key not in cases:
        return {}
    return {key: without_messages(cases[key]) if normalize else cases[key]}


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
    failures: list[str] = []
    expected: dict[Expected, list[str]] = {}
    messages: list[str] = []
    for key in sorted(set(a) | set(b)):
        raw = diff_cases(_one(a, key, False), _one(b, key, False))
        if not raw:
            continue
        lines = diff_cases(_one(a, key, True), _one(b, key, True))
        if not lines:
            messages += raw
            continue
        entry = next((e for e in entries if e.matches(key)), None)
        if entry is None:
            failures += lines
        else:
            expected.setdefault(entry, []).extend(lines)
    print(f"must stay identical: {len(failures)} difference(s)")
    for line in failures:
        print(f"  {line}")
    count = sum(len(lines) for lines in expected.values())
    print(f"expected-diff entries ({expected_path}): {count} difference(s)")
    for entry, lines in expected.items():
        print(f"  {entry.key} | {entry.reason}")
        for line in lines:
            print(f"    {line}")
    print(f"message wording only: {len(messages)} difference(s)")
    for line in messages:
        print(f"  {line}")
    unused = [e for e in entries if e not in expected]
    if unused:
        print(f"expected-diff entries that match no difference: {len(unused)}")
        for e in unused:
            print(f"  line {e.line}: {e.key}")
    print(
        f"{len(failures)} failure(s), {count} expected, {len(messages)} message-only "
        f"difference(s) in {len(a)} vs {len(b)} cases"
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
