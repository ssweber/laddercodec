"""Where a field rule comes from: the kind of evidence and a public reference.

A reference names something a reader can find: an OBJ-xxx error id, a Help topic
(``CL173``), a capture file, an arc ruling, or a CLICK DLL and the dialog field it
checks (``Inst_SD.dll, Send local banks``).  :class:`Src` refuses a reference that holds
a DLL address in one of the spellings :func:`dll_address` knows.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class SrcKind(Enum):
    """The kind of evidence a rule rests on."""

    #: A CLICK DLL's dialog code: ``Inst_Copy.dll, Single Copy source``.
    DLL = "DLL"
    #: A CLICK Help topic: ``CL173``.
    HELP = "Help"
    #: A value typed into a CLICK dialog and its result.
    DIALOG = "Dialog"
    #: A native capture under ``tests/fixtures``.
    CAPTURE = "Capture"
    #: A user ruling recorded in the arc doc.
    RULING = "Ruling"
    #: A refusal laddercodec makes and CLICK does not.
    CODEC = "Codec"


#: Spellings of a location in a CLICK DLL (the images load at base 0x1000 << 16):
#:
#: - eight hex digits starting ``100``, alone or after ``0x``, ``_`` (``sub_``, ``FUN_``,
#:   ``LAB_``) or a space, with ``_`` between digits allowed and a trailing ``h``;
#: - ``@`` and eight hex digits;
#: - an offset from a DLL name: ``Inst_SD.dll+0x...``.
_DLL_ADDRESS_RE = re.compile(
    r"(?<![0-9a-z])(?:0x)?(?P<digits>1_?0_?0(?:_?[0-9a-f]){5})h?(?![0-9a-z])"
    r"|@[0-9a-f]{8}(?![0-9a-z])"
    r"|\.dll\s*\+\s*(?:0x)?[0-9a-f]",
    re.IGNORECASE,
)
#: The image base itself, which a mask or limit may hold as a value.
_IMAGE_BASE = f"{0x1000 << 16:x}"


def dll_address(text: str) -> str | None:
    """Return the first DLL location ``text`` holds, or None."""
    for match in _DLL_ADDRESS_RE.finditer(text):
        digits = match.group("digits")
        if digits is not None and digits.replace("_", "") == _IMAGE_BASE:
            continue
        return match.group(0)
    return None


@dataclass(frozen=True)
class Src:
    """The evidence for a rule: ``Src(SrcKind.HELP, "CL173")``."""

    kind: SrcKind
    ref: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, SrcKind):
            raise TypeError(f"Src.kind: {self.kind!r} is not a SrcKind")
        if not isinstance(self.ref, str):
            raise TypeError(f"Src.ref: {self.ref!r} is not text")
        if not self.ref.strip():
            raise ValueError("Src.ref: a source names its reference")
        if (found := dll_address(self.ref)) is not None:
            raise ValueError(
                f"Src.ref: {self.ref!r} holds the DLL address {found!r}; name the DLL and field"
            )

    def __str__(self) -> str:
        return f"{self.kind.value}: {self.ref}"
