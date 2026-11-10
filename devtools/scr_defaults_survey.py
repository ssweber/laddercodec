"""Report which tags Click's SCR files leave out, checked against tag_default.

Pairs each SCR blob with the clipboard blob of the same instruction and prints,
per (class, tag), the clipboard values seen when SCR left the tag out.  A line
marked ``MISMATCH`` is a tag left out at a value other than
``binary_helpers.tag_default`` returns: add it to ``_TAG_DEFAULTS`` or
``_CLASS_TAG_DEFAULTS``.  Flags, variant arrays and the func code (0x3218, which
each family derives) are listed but not checked.

``tests/test_instruction_defaults.py`` runs the same check over the fixture pairs.

Usage:
    uv run devtools/scr_defaults_survey.py                  # every fixture pair
    uv run devtools/scr_defaults_survey.py <scr> <bin> ...  # explicit pairs
    uv run devtools/scr_defaults_survey.py --mismatches     # only MISMATCH lines
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from scr_defaults import fixture_pairs, is_checked, mismatches, survey  # noqa: E402

from laddercodec.binary_helpers import _tag_wire_type  # noqa: E402


def main(argv: list[str]) -> int:
    only_mismatches = "--mismatches" in argv
    args = [a for a in argv if a != "--mismatches"]
    if len(args) % 2:
        print(__doc__)
        return 2
    pairs = (
        [(Path(s), Path(c)) for s, c in zip(args[::2], args[1::2], strict=True)]
        if args
        else fixture_pairs()
    )

    result = survey(pairs)
    bad = {(cls, tag): default for cls, tag, default, _ in mismatches(result)}
    print(f"{result.pairs} pairs, {result.unpaired} unpaired SCR blobs")
    for (class_name, tag), values in sorted(result.omitted.items()):
        if only_mismatches and (class_name, tag) not in bad:
            continue
        shown = {k[:30]: n for k, n in list(values.items())[:4]}
        kept = len(result.kept.get((class_name, tag), {}))
        if (class_name, tag) in bad:
            note = f"MISMATCH default={bad[(class_name, tag)]!r}"
        elif is_checked(tag):
            note = ""
        else:
            note = f"({'func code' if tag == 0x3218 else _tag_wire_type(tag)})"
        print(f"{class_name:10s} {tag:#06x}  omitted={shown}  kept={kept} distinct  {note}")
    print(f"{len(bad)} mismatch(es)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
