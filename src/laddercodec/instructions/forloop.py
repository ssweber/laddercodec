"""For/Next loop instructions (type markers 0x2725 and 0x2726).

Binary class names:
    - ``"For"``
    - ``"Next"``

CSV forms:
    - ``for(3,oneshot=0)``
    - ``for(DS1,oneshot=1)``
    - ``next()``
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..model import AfInstruction, InstructionType, _validate_operand
from .family import AfInstructionFamilySpec

if TYPE_CHECKING:
    from ..csv.ast import AfCall

FOR_TYPE_MARKER = 0x2700 | InstructionType.FOR_LOOP
NEXT_TYPE_MARKER = 0x2700 | InstructionType.NEXT

_FOR_FUNC_CODES: dict[bool, str] = {
    False: "9218",
    True: "9219",
}
_FUNC_CODE_TO_ONESHOT: dict[str, bool] = {v: k for k, v in _FOR_FUNC_CODES.items()}

_FOR_TAGS = (0x6065, 0x3218, 0x11F8, 0x0000)
_FOR_LITERAL_RE = re.compile(r"^\d+$")


def _validate_for_limit(value: str) -> str:
    text = value.strip()
    if not text:
        raise ValueError("for() limit cannot be blank")
    if _FOR_LITERAL_RE.fullmatch(text):
        return text
    return _validate_operand(text)


@dataclass
class ForLoop(AfInstruction):
    """FOR loop instruction."""

    limit: str
    oneshot: bool = False

    def __post_init__(self) -> None:
        self.limit = _validate_for_limit(self.limit)

    @classmethod
    def from_csv_token(cls, token: str) -> ForLoop:
        token = token.strip()
        m = re.fullmatch(r"for\((.+)\)", token)
        if not m:
            raise ValueError(f"Cannot parse for instruction: {token!r}")

        args: list[str] = []
        kwargs: dict[str, str] = {}
        for seg in (a.strip() for a in m.group(1).split(",")):
            if "=" in seg:
                k, v = seg.split("=", 1)
                kwargs[k.strip()] = v.strip()
            else:
                args.append(seg)

        if len(args) != 1:
            raise ValueError(f"for expects 1 positional arg (limit), got {len(args)}")
        unknown = set(kwargs) - {"oneshot"}
        if unknown:
            raise ValueError(f"for does not support keyword argument(s): {sorted(unknown)}")

        oneshot_raw = kwargs.get("oneshot", "0")
        if oneshot_raw not in {"0", "1"}:
            raise ValueError("for oneshot must be 0 or 1")

        return cls(limit=args[0], oneshot=oneshot_raw == "1")

    @property
    def func_code(self) -> str:
        return _FOR_FUNC_CODES[self.oneshot]

    def to_csv(self) -> str:
        return f"for({self.limit},oneshot={1 if self.oneshot else 0})"

    def cell_params(self) -> dict:
        return {}

    def build_blob(self) -> bytes:
        from ..binary_helpers import _tagged_field, _utf16le_null

        out = bytearray()
        out += _utf16le_null("For")
        out += struct.pack("<I", FOR_TYPE_MARKER)
        out += b"\x01\x00"  # part_count
        out += struct.pack("<I", 4)  # field_count
        out += _tagged_field(_FOR_TAGS[0], self.limit)
        out += _tagged_field(_FOR_TAGS[1], self.func_code)
        out += _tagged_field(_FOR_TAGS[2], "-1" if self.oneshot else "0")
        out += _tagged_field(_FOR_TAGS[3], "")
        return bytes(out)


@dataclass
class Next(AfInstruction):
    """NEXT loop instruction."""

    @classmethod
    def from_csv_token(cls, token: str) -> Next:
        token = token.strip()
        if not re.fullmatch(r"next\(\s*\)", token):
            raise ValueError(f"Cannot parse next instruction: {token!r}")
        return cls()

    def to_csv(self) -> str:
        return "next()"

    def cell_params(self) -> dict:
        return {}

    def build_blob(self) -> bytes:
        from ..binary_helpers import _tagged_field, _utf16le_null

        out = bytearray()
        out += _utf16le_null("Next")
        out += struct.pack("<I", NEXT_TYPE_MARKER)
        out += b"\x01\x00"  # part_count
        out += struct.pack("<I", 1)  # field_count
        out += _tagged_field(0x0000, "")
        return bytes(out)


def from_tags(
    class_name: str,
    type_code: int,
    tags: dict[int, str],
    tag_byte_lens: dict[int, int] | None = None,
    variant_u16_tags: dict[int, dict[int, int]] | None = None,
    variant_string_tags: dict[int, dict[int, str]] | None = None,
) -> ForLoop | Next | None:
    """Construct a ForLoop or Next from tag data (shared by both decoders)."""
    if class_name == "Next" and type_code == NEXT_TYPE_MARKER:
        return Next()

    if class_name == "For" and type_code == FOR_TYPE_MARKER:
        limit = tags.get(0x6065, "")
        if not limit:
            return None
        oneshot = 0x11F8 in tags
        try:
            return ForLoop(limit=limit, oneshot=oneshot)
        except ValueError:
            return None

    return None


def _parse_for_blob(raw: bytes, pos: int) -> ForLoop | None:
    from ..binary_helpers import _parse_tagged_fields_verbose

    if pos + 10 > len(raw):
        return None

    type_marker = int.from_bytes(raw[pos : pos + 4], "little")
    pos += 4
    part_count = int.from_bytes(raw[pos : pos + 2], "little")
    pos += 2
    field_count = int.from_bytes(raw[pos : pos + 4], "little")
    pos += 4

    if type_marker != FOR_TYPE_MARKER or part_count != 1 or field_count != 4:
        return None

    fields, _ = _parse_tagged_fields_verbose(raw, pos, field_count)
    if len(fields) != 4:
        return None

    for idx, tag in enumerate(_FOR_TAGS):
        if fields[idx][0] != tag or fields[idx][1] != b"\xff\xff\xff\xff":
            return None

    limit = fields[0][2]
    func_code = fields[1][2]
    oneshot_raw = fields[2][2]
    terminator = fields[3][2]

    if terminator not in {"", "\ufffd"}:
        return None

    if oneshot_raw in {"-1", "1"}:
        oneshot = True
    elif oneshot_raw == "0":
        oneshot = False
    else:
        return None

    func_oneshot = _FUNC_CODE_TO_ONESHOT.get(func_code)
    if func_oneshot is None:
        return None
    if func_oneshot != oneshot:
        oneshot = func_oneshot

    try:
        return ForLoop(limit=limit, oneshot=oneshot)
    except ValueError:
        return None


def _parse_next_blob(raw: bytes, pos: int) -> Next | None:
    from ..binary_helpers import _read_utf16le

    if pos + 10 > len(raw):
        return None

    type_marker = int.from_bytes(raw[pos : pos + 4], "little")
    pos += 4
    part_count = int.from_bytes(raw[pos : pos + 2], "little")
    pos += 2
    field_count = int.from_bytes(raw[pos : pos + 4], "little")
    pos += 4

    if type_marker != NEXT_TYPE_MARKER or part_count != 1 or field_count != 1:
        return None
    if pos + 6 > len(raw):
        return None

    tag = int.from_bytes(raw[pos : pos + 2], "little")
    marker = raw[pos + 2 : pos + 6]
    remainder = raw[pos + 6 :]
    if tag != 0x0000 or marker != b"\xff\xff\xff\xff":
        return None
    if remainder in {b"", b"\x00", b"\x00\x00"}:
        return Next()

    # Some decoded AF slices include trailing tail bytes after the field value.
    value, _ = _read_utf16le(raw, pos + 6)
    if value not in {"", "\ufffd"}:
        return None

    return Next()


def build_blob(obj: ForLoop | Next) -> bytes:
    """Build the instruction data blob for For/Next instructions."""
    return obj.build_blob()


def parse_blob(raw: bytes) -> ForLoop | Next | None:
    """Try to parse a ForLoop or Next instruction from an instruction blob."""
    from ..binary_helpers import _read_utf16le

    class_name, pos = _read_utf16le(raw, 0)
    if class_name == "For":
        return _parse_for_blob(raw, pos)
    if class_name == "Next":
        return _parse_next_blob(raw, pos)
    return None


def parse_af_call(call: AfCall) -> ForLoop | Next:
    """Parse an AF AST call into a ForLoop or Next."""
    if call.name == "for":
        return ForLoop.from_csv_token(call.to_token())
    return Next.from_csv_token(call.to_token())


SPEC = AfInstructionFamilySpec(
    family_name="loop",
    instruction_types=(ForLoop, Next),
    binary_class_names=("For", "Next"),
    parse_blob=parse_blob,
    from_tags=from_tags,
    csv_names=("for", "next"),
    parse_csv_call=parse_af_call,
)
