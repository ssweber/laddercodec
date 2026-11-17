"""Print each instruction blob of an SCR file above the matching blob of a clipboard capture.

The blobs pair up by type marker, and then by their order among the blobs of that type.
"""

from __future__ import annotations

import struct
import sys


def hexline(data: bytes, label: str = "") -> str:
    h = " ".join(f"{b:02x}" for b in data)
    a = "".join(chr(b) if 0x20 <= b < 0x7F else "." for b in data)
    return f"  {label:6s} {h}  {a}"


def find_type_markers(data: bytes) -> list[tuple[int, int]]:
    """Return (offset, marker) for each InstructionType marker (0x2711-0x2730) in *data*.

    The search reads a u16 at every byte offset, so it can also match bytes that are not a
    marker.
    """
    results = []
    for i in range(len(data) - 1):
        marker = struct.unpack_from("<H", data, i)[0]
        if 0x2711 <= marker <= 0x2730:
            results.append((i, marker))
    return results


def extract_scr_blob(data: bytes, type_offset: int) -> tuple[str, bytes, int]:
    """Return the class name, the bytes and the start offset of an SCR blob.

    *type_offset* is the offset of the blob's type marker. The blob starts at the length byte
    of its class name, and the bytes run from there to the end of *data*. If no class name
    is found, return ``"???"`` and start at the type marker.
    """
    # In SCR, a blob starts with [u8 byte_len] [UTF-16LE class name], and the type marker
    # follows the name. Step back from the marker to the first byte whose value is the
    # number of bytes between that byte and the marker.
    for back in range(2, 50):
        pos = type_offset - back
        if pos < 0:
            break
        str_len = data[pos]
        if str_len == back - 1:
            # Length byte matches distance
            raw_str = data[pos + 1 : pos + 1 + str_len]
            if len(raw_str) % 2 == 1:
                raw_str = raw_str + b"\x00"
            try:
                name = raw_str.decode("utf-16-le").rstrip("\x00")
                if name and name[0].isupper() and name.isascii():
                    blob_start = pos
                    return name, data[blob_start:], blob_start
            except (UnicodeDecodeError, ValueError):
                continue
    return "???", data[type_offset:], type_offset


def extract_clip_blob(data: bytes, type_offset: int) -> tuple[str, bytes, int]:
    """Return the class name, the bytes and the start offset of a clipboard blob.

    *type_offset* is the offset of the blob's type marker. The blob starts with its class
    name, at offset +0x25 of its cell, and the bytes run from there to the end of *data*. If
    no class name is found, return ``"???"`` and start at the type marker.
    """
    # In the clipboard format, a cell's data at +0x25 starts with the UTF-16LE class name and
    # a 00 00 terminator. The type marker follows. Step back from the marker to find the
    # terminator, then step back again to the start of the name.
    for back in range(4, 60, 2):
        pos = type_offset - back
        if pos < 0:
            break
        # Check for double null before type offset
        if data[pos] != 0 or data[pos + 1] != 0:
            continue
        # pos and pos+1 hold the null terminator, and the name ends there. Step back two
        # bytes at a time to the null pair before the name.
        str_start = pos - 2
        while str_start >= 0 and not (data[str_start] == 0 and data[str_start + 1] == 0):
            str_start -= 2
        str_start += 2  # skip the preceding null pair
        if str_start < pos:
            try:
                name = data[str_start:pos].decode("utf-16-le")
                if name and name[0].isupper() and name.isascii():
                    return name, data[str_start:], str_start
            except (UnicodeDecodeError, ValueError):
                continue
    return "???", data[type_offset:], type_offset


def main() -> None:
    scr_path = sys.argv[1]
    clip_path = sys.argv[2]

    with open(scr_path, "rb") as f:
        scr = f.read()
    with open(clip_path, "rb") as f:
        clip = f.read()

    scr_markers = find_type_markers(scr)
    clip_markers = find_type_markers(clip)

    print("=" * 72)
    print("INSTRUCTION BLOB COMPARISON: SCR vs CLIP")
    print("=" * 72)

    # Match up by type
    scr_by_type: dict[int, list[int]] = {}
    clip_by_type: dict[int, list[int]] = {}
    for off, typ in scr_markers:
        scr_by_type.setdefault(typ, []).append(off)
    for off, typ in clip_markers:
        clip_by_type.setdefault(typ, []).append(off)

    all_types = sorted(set(scr_by_type) | set(clip_by_type))
    for typ in all_types:
        scr_offsets = scr_by_type.get(typ, [])
        clip_offsets = clip_by_type.get(typ, [])
        print(f"\n{'=' * 72}")
        print(f"Type {typ:#06x}: SCR has {len(scr_offsets)}, CLIP has {len(clip_offsets)}")

        for i, (s_off, c_off) in enumerate(zip(scr_offsets, clip_offsets, strict=False)):
            s_name, s_blob, s_start = extract_scr_blob(scr, s_off)
            c_name, c_blob, c_start = extract_clip_blob(clip, c_off)

            preview = 80
            print(f"\n  --- {s_name} (instance {i}) ---")
            print(f"  SCR  @ {s_start:#06x} (type @ {s_off:#06x}):")
            for j in range(0, min(preview, len(s_blob)), 16):
                chunk = s_blob[j : j + 16]
                print(hexline(chunk, f"+{j:02x}:"))
            print(f"  CLIP @ {c_start:#06x} (type @ {c_off:#06x}):")
            for j in range(0, min(preview, len(c_blob)), 16):
                chunk = c_blob[j : j + 16]
                print(hexline(chunk, f"+{j:02x}:"))

            # Print the 24 bytes from each type marker on, one line above the other, so that
            # the fields after the marker line up.
            print("\n  Key offsets from type marker:")
            s_after = scr[s_off : s_off + 24]
            c_after = clip[c_off : c_off + 24]
            print(f"    SCR:  {' '.join(f'{b:02x}' for b in s_after)}")
            print(f"    CLIP: {' '.join(f'{b:02x}' for b in c_after)}")


if __name__ == "__main__":
    main()
