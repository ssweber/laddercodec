"""Which tags Click's SCR files leave out, measured on native SCR + clipboard pairs.

Click's program files (``Scr*.tmp``) store a tag only when it differs from its
default; the clipboard stores every tag.  ``survey()`` pairs each SCR blob with the
clipboard blob of the same instruction (same class, same non-empty operands) and
counts, per (class, tag), the clipboard values seen when SCR left the tag out and
when it kept it.  ``mismatches()`` lists the tags SCR left out at a value other
than ``binary_helpers.tag_default`` returns.

Used by ``tests/test_instruction_defaults.py`` and ``devtools/scr_defaults_survey.py``.
"""

from __future__ import annotations

import gzip
import importlib
from collections import defaultdict
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from laddercodec import decode, decode_program
from laddercodec.binary_helpers import _STANDARD_SENTINEL, _tag_wire_type, tag_default

_decode_program_mod = importlib.import_module("laddercodec.decode_program")
_raw_mod = importlib.import_module("laddercodec.instructions.raw")

FIXTURES = Path(__file__).parent / "fixtures"

#: SCR fixtures whose clipboard copy is synthetic (see scr_captures/README.md).
_SYNTHETIC = {"time_drums"}

#: Wire types whose omission ``tag_default`` doesn't model (flags: absent = unset;
#: variants: an all-zero array is left out) and the func code each family derives.
_UNCHECKED_WIRES = {"flag", "variant_u16", "variant_string"}
_FUNC_CODE = 0x3218

Tags = dict[int, str]
Counts = dict[tuple[str, int], dict[str, int]]


def fixture_pairs() -> list[tuple[Path, Path]]:
    """Every native (scr, clipboard) pair under tests/fixtures."""
    pairs: list[tuple[Path, Path]] = []
    for scr in sorted((FIXTURES / "scr_captures").glob("*.scr")):
        if scr.stem in _SYNTHETIC:
            continue
        for clip in (scr.with_suffix(".bin"), scr.with_suffix(".bin.gz")):
            if clip.exists():
                pairs.append((scr, clip))
    for scr in sorted((FIXTURES / "tumbler").rglob("*.scr")):
        clip = scr.with_name(f"{scr.stem}.clipboard.bin")
        if clip.exists():
            pairs.append((scr, clip))
    return pairs


def read_clipboard(path: Path) -> bytes:
    data = path.read_bytes()
    return gzip.decompress(data) if path.suffix == ".gz" else data


@contextmanager
def _wrapped(module: Any, name: str, wrapper: Callable[[Callable], Callable]) -> Iterator[None]:
    original = getattr(module, name)
    setattr(module, name, wrapper(original))
    try:
        yield
    finally:
        setattr(module, name, original)


def _scr_tags(data: bytes) -> list[tuple[str, Tags]]:
    """Each SCR blob's class name and tags (variant arrays as their repr)."""
    log: list[tuple[str, Tags]] = []

    def wrap(original: Callable) -> Callable:
        def recording(*args: Any, **kwargs: Any) -> Any:
            out = original(*args, **kwargs)
            tags = dict(out[2])
            for tag, entries in {**out[4], **out[5]}.items():
                tags[tag] = repr(entries)
            log.append((out[0], tags))
            return out

        return recording

    with _wrapped(_decode_program_mod, "_parse_scr_tags", wrap):
        decode_program(data)
    return log


def _clipboard_tags(data: bytes) -> list[tuple[str, Tags]]:
    """Each clipboard blob's class name and raw tag values (before flag normalising)."""
    log: list[tuple[str, Tags]] = []
    classes: list[str] = []

    def wrap_decompose(original: Callable) -> Callable:
        def recording(blob: bytes) -> Any:
            out = original(blob)
            classes.append(out[0])
            return out

        return recording

    def wrap_fields(original: Callable) -> Callable:
        def recording(fields: list[tuple[int, bytes, str]]) -> Any:
            tags: Tags = {}
            variants: dict[int, dict[int, str]] = defaultdict(dict)
            for tag, sentinel, value in fields:
                if sentinel == _STANDARD_SENTINEL:
                    tags[tag] = value
                else:
                    variants[tag][int.from_bytes(sentinel, "little")] = value
            for tag, entries in variants.items():
                tags[tag] = repr(entries)
            log.append((classes[-1] if classes else "?", tags))
            return original(fields)

        return recording

    with (
        _wrapped(_raw_mod, "_decompose_blob", wrap_decompose),
        _wrapped(_raw_mod, "_fields_to_tag_dicts", wrap_fields),
    ):
        decode(data)
    return log


@dataclass
class Survey:
    pairs: int = 0
    unpaired: int = 0
    omitted: Counts = field(default_factory=lambda: defaultdict(lambda: defaultdict(int)))
    kept: Counts = field(default_factory=lambda: defaultdict(lambda: defaultdict(int)))


def survey(pairs: list[tuple[Path, Path]]) -> Survey:
    result = Survey(pairs=len(pairs))
    for scr_path, clip_path in pairs:
        clip_by_class: dict[str, list[Tags]] = defaultdict(list)
        for class_name, tags in _clipboard_tags(read_clipboard(clip_path)):
            clip_by_class[class_name].append(tags)
        for class_name, scr_tags in _scr_tags(scr_path.read_bytes()):
            operands = {k: v for k, v in scr_tags.items() if _tag_wire_type(k) == "string" and v}
            candidates = clip_by_class.get(class_name, [])
            match = next(
                (c for c in candidates if all(c.get(k) == v for k, v in operands.items())), None
            )
            if match is None:
                result.unpaired += 1
                continue
            candidates.remove(match)
            for tag, value in match.items():
                if tag:
                    counts = result.kept if tag in scr_tags else result.omitted
                    counts[(class_name, tag)][value] += 1
    return result


def is_checked(tag: int) -> bool:
    return tag != _FUNC_CODE and _tag_wire_type(tag) not in _UNCHECKED_WIRES


def mismatches(result: Survey) -> list[tuple[str, int, str, list[str]]]:
    """``(class, tag, default, values)`` for each tag SCR left out at a non-default value."""
    found = []
    for (class_name, tag), values in sorted(result.omitted.items()):
        if not is_checked(tag):
            continue
        default = tag_default(tag, class_name)
        numeric = _tag_wire_type(tag) != "string"
        bad = sorted(v for v in values if v != default and not (numeric and v == ""))
        if bad:
            found.append((class_name, tag, default, bad))
    return found
