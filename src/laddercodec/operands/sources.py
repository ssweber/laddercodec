"""Where a field rule comes from: the kind of evidence and a public reference.

A reference names something a reader can find: an OBJ-xxx error id, a Help topic
(``CL173``), a capture file, an arc ruling, or a CLICK DLL and the dialog field it
checks (``Inst_SD.dll, Send local banks``).  It never holds an address inside a DLL.
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


#: An address inside a CLICK DLL (``0x1000`` or ``@1000`` and four more hex digits), which a
#: reference may not hold.
_DLL_ADDRESS_RE = re.compile(r"(?:0[xX]|@)1[0-9A-Fa-f]{7}")


@dataclass(frozen=True)
class Src:
    """The evidence for a rule: ``Src(SrcKind.HELP, "CL173")``."""

    kind: SrcKind
    ref: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, SrcKind):
            raise TypeError(f"Src.kind: {self.kind!r} is not a SrcKind")
        if not self.ref.strip():
            raise ValueError("Src.ref: a source names its reference")
        if _DLL_ADDRESS_RE.search(self.ref):
            raise ValueError(f"Src.ref: {self.ref!r} holds a DLL address; name the DLL and field")

    def __str__(self) -> str:
        return f"{self.kind.value}: {self.ref}"
