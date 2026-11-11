"""Committed files carry no CLICK DLL addresses.

A citation names its evidence (an OBJ-xxx id, a Help topic, a capture, an arc.md ruling or
``DLL: <name>.dll, <dialog/field>``), never a location inside a CLICK DLL.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# A location in a DLL's image: 0x100xxxxx, a bare 100xxxxx (optionally with a trailing h),
# or @xxxxxxxx.
ADDRESS = re.compile(
    r"(?<![0-9A-Za-z_])(?:0x)?100[0-9A-Fa-f]{5}h?(?![0-9A-Za-z_])|@[0-9A-Fa-f]{8}\b"
)

# An 0x value of six or more hex digits is a location in an executable or DLL unless it is
# one of the data values below.  Exact values, upper-cased, each with its reason.
LONG_HEX = re.compile(r"\b0[xX]([0-9A-Fa-f]{6,})\b")
ALLOWED_VALUES: dict[str, str] = {
    "FFFFFFFF": "all-ones 32-bit mask or sentinel",
    "80000000": "int32 sign bit (counter span check)",
    "10FFFF": "highest Unicode code point (decoder)",
    "00000001": "structural flag value in the binary format",
    "00000004": "CREATE_SUSPENDED process flag in devtools/mergeq",
    "00000200": "Win32 process flag in devtools/mergeq",
    "200000": "2 MiB image window in a disassembly helper script",
}

# path -> reason.  Keep empty.
ALLOWED: dict[str, str] = {}


def _tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True
    ).stdout
    return [p for p in out.decode("utf-8").split("\0") if p]


def test_address_pattern_matches_the_forms_in_use() -> None:
    digits = "0aabb"  # built here so this file holds no address itself
    for text in (
        "0x100" + digits,
        "@100" + digits,
        "Inst_Search 100" + digits,
        "at 100" + digits,
        "range ..0x100" + digits,
        "Inst_RD 100" + digits + "h",
    ):
        assert ADDRESS.search(text), text
    for text in ("0x8bc0", "0x271e", "0x0A60", "0x6fff", "0x10e", "0x1201", "+0x19", "x1000"):
        assert not ADDRESS.search(text), text


def test_long_hex_pattern_matches_six_digits_or_more() -> None:
    value = "0x5A" + "7B9B"
    assert LONG_HEX.search(f"writer at {value}")
    assert LONG_HEX.search(f"{value}/{value}")
    assert not LONG_HEX.search("command IDs 0x8036/0x802D, tag 0x1201")
    assert not LONG_HEX.search("0x12345")


def test_allowed_values_are_exact_and_explained() -> None:
    for value, reason in ALLOWED_VALUES.items():
        assert value == value.upper() and LONG_HEX.fullmatch("0x" + value), value
        assert reason, value


def _scan(text: str) -> list[tuple[int, str]]:
    hits = []
    for number, line in enumerate(text.splitlines(), 1):
        long_values = [m.group(1).upper() for m in LONG_HEX.finditer(line)]
        if ADDRESS.search(line) or any(v not in ALLOWED_VALUES for v in long_values):
            hits.append((number, line.strip()[:100]))
    return hits


def test_no_dll_addresses_in_tracked_files() -> None:
    hits = []
    for rel in _tracked_files():
        if rel in ALLOWED:
            continue
        try:
            text = (ROOT / rel).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        hits += [f"{rel}:{number}: {line}" for number, line in _scan(text)]
    assert not hits, "DLL or executable addresses in committed files:\n" + "\n".join(hits)
