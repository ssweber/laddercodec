"""Test that no tracked file holds an address inside a CLICK DLL.

The repo says what a CLICK rule is, and never where its code sits inside a CLICK DLL.
:func:`dll_address` decides what counts as such an address. The test applies it to each
line of every tracked file.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

#: Spellings of a location in a CLICK DLL or executable, in any letter case (the DLL
#: images load at base ``0x1000 << 16``):
#:
#: - eight hex digits starting ``100``, alone or after ``0x``, ``_`` (``sub_``, ``FUN_``,
#:   ``LAB_``) or a space, with ``_`` between digits allowed and a trailing ``h``;
#: - ``@`` and eight hex digits;
#: - an offset from a DLL name: ``.dll+`` and ``0x`` digits or four or more hex digits
#:   holding a digit (``h`` may follow), or ``.dll!0x...`` and ``.dll:0x...``;
#: - ``0x`` and six or more hex digits, unless the value is one of
#:   :data:`ALLOWED_LONG_HEX`.
#:
#: A short offset written apart from its DLL (``offset 0x`` and four digits ``in X.dll``)
#: is out of scope: it reads like any other small hex value.
_DLL_ADDRESS_RE = re.compile(
    r"(?<![0-9a-z])(?:0x)?1_?0_?0(?:_?[0-9a-f]){5}h?(?![0-9a-z])"
    r"|@[0-9a-f]{8}(?![0-9a-z])"
    r"|\.dll\s*\+\s*(?:0x[0-9a-f]+|(?=[0-9a-f]*[0-9])[0-9a-f]{4,}h?)(?![0-9a-z])"
    r"|\.dll\s*[!:]\s*0x[0-9a-f]+"
    r"|\b0x(?P<long>[0-9a-f]{6,})\b",
    re.IGNORECASE,
)

#: ``0x`` values of six or more hex digits that are data, not locations. Each key is an
#: exact value in upper case, and each value is the reason that it is allowed.
ALLOWED_LONG_HEX: dict[str, str] = {
    "FFFFFFFF": "all-ones 32-bit mask or sentinel",
    "80000000": "int32 sign bit (counter span check)",
    "10FFFF": "highest Unicode code point (decoder)",
    "00000001": "structural flag value in the binary format",
    "200000": "2 MiB image window in a disassembly helper script",
}


def dll_address(text: str) -> str | None:
    """Return the first DLL or executable location ``text`` holds, or None."""
    for match in _DLL_ADDRESS_RE.finditer(text):
        long = match.group("long")
        if long is not None and long.upper() in ALLOWED_LONG_HEX:
            continue
        return match.group(0)
    return None


# Each key is a path and each value the reason. List only files that a tool generates,
# which cannot hold a DLL address.
ALLOWED: dict[str, str] = {
    "uv.lock": "written by uv: package URLs and hashes, whose hex runs can look like an address",
}


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
        "Inst_RD 100" + digits + "H",
    ):
        assert dll_address(text), text
    for text in ("0x8bc0", "0x271e", "0x0A60", "0x6fff", "0x10e", "0x1201", "+0x19", "x1000"):
        assert not dll_address(text), text


def test_long_hex_pattern_matches_six_digits_or_more() -> None:
    value = "0x5A" + "7B9B"
    assert dll_address(f"writer at {value}")
    assert dll_address(f"{value}/{value}")
    assert not dll_address("command IDs 0x8036/0x802D, tag 0x1201")
    assert not dll_address("0x12345")


def test_allowed_values_are_exact_and_explained() -> None:
    for value, reason in ALLOWED_LONG_HEX.items():
        assert value == value.upper() and len(value) >= 6, value
        assert dll_address("0x" + value) is None, value
        assert reason, value


def _scan(text: str) -> list[tuple[int, str]]:
    return [
        (number, line.strip()[:100])
        for number, line in enumerate(text.splitlines(), 1)
        if dll_address(line) is not None
    ]


# Built here so this file holds no address itself.
_FAKE = f"{(0x1000 << 16) + 0x1234:08x}"
_BASE = f"{0x1000 << 16:x}"
_DLL = "Inst_SD.dll"

#: Each case is (text, refused). The list holds each form that :func:`dll_address` matches,
#: and text that only looks like one.
FORMS = [
    (f"Inst_SD.dll 0x{_FAKE}", True),
    (f"Inst_SD.dll 0X{_FAKE.upper()}", True),
    (f"baseEx.dll @{_FAKE}", True),
    (f"Inst_SD.dll sub_{_FAKE}", True),
    (f"FUN_{_FAKE}", True),
    (f"LAB_{_FAKE}", True),
    (f"Inst_SD.dll {_FAKE}", True),
    (f"Inst_SD.dll {_FAKE}h", True),
    (f"Inst_SD.dll {_FAKE}H", True),
    (f"Inst_SD.dll 0x{_FAKE[:4]}_{_FAKE[4:]}", True),
    (f"mask 0x{_BASE}", True),
    (f"capture 0x{(0x1A2B << 16) + 0x3C4D:08X}.bin", True),
    (f"writer at 0x{(0x5A << 16) + 0x7B9B:X}", True),
    (f"{_DLL}+0x1234", True),
    (f"{_DLL} + 1234", True),
    (f"{_DLL}+6cb1h", True),
    (f"{_DLL}!0x1234", True),
    (f"{_DLL}:0x1234", True),
    ("Inst_SD.dll, Send local banks", False),
    ("Inst_Copy.dll + dialog", False),
    ("Inst_SD.dll + 2 fields", False),
    ("Inst_SD.dll + dead", False),
    ("Inst_SD.dll: Send local banks", False),
    ("CL195", False),
    ("OBJ-004", False),
    ("mask 0x3f", False),
    ("0xFFFFFFFF sentinel", False),
    (f"value {_FAKE}0", False),
    ("offset 0x6cb1 in Inst_SD.dll", False),  # out of scope: see _DLL_ADDRESS_RE
]


@pytest.mark.parametrize(("text", "refused"), FORMS, ids=[f[0] for f in FORMS])
def test_file_scan_matches_the_forms(text: str, refused: bool) -> None:
    assert bool(_scan(text)) is refused


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
