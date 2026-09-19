"""Read Windows clipboard formats without replacing or clearing clipboard data."""

import argparse
import ctypes as c
import hashlib
import json
import time
from ctypes import wintypes as w
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("output", type=Path, nargs="?", default=Path("build/productivity/captures"))
args = parser.parse_args()
out = args.output / time.strftime("capture-%Y%m%d-%H%M%S")
out.mkdir(parents=True, exist_ok=True)
u = c.WinDLL("user32", use_last_error=True)
k = c.WinDLL("kernel32", use_last_error=True)
u.OpenClipboard.argtypes = [w.HWND]
u.GetClipboardData.argtypes = [w.UINT]
u.GetClipboardData.restype = w.HANDLE
u.GetClipboardOwner.restype = w.HWND
u.GetClipboardFormatNameW.argtypes = [w.UINT, w.LPWSTR, c.c_int]
k.GlobalSize.argtypes = [w.HANDLE]
k.GlobalSize.restype = c.c_size_t
k.GlobalLock.argtypes = [w.HANDLE]
k.GlobalLock.restype = c.c_void_p
k.GlobalUnlock.argtypes = [w.HANDLE]
owner = u.GetClipboardOwner()
pid = w.DWORD()
u.GetWindowThreadProcessId.argtypes = [w.HWND, c.POINTER(w.DWORD)]
u.GetWindowThreadProcessId(owner, c.byref(pid))
for _attempt in range(20):
    if u.OpenClipboard(None):
        break
    time.sleep(0.05)
else:
    raise c.WinError(c.get_last_error())
formats = []
try:
    fmt = 0
    while fmt := u.EnumClipboardFormats(fmt):
        name = c.create_unicode_buffer(512)
        u.GetClipboardFormatNameW(fmt, name, 512)
        row = {"id": fmt, "name": name.value}
        # Bitmap, palette, metafile and owner-display handles are not HGLOBAL.
        if fmt in (2, 3, 9, 14, 0x80, 0x82, 0x83, 0x8E):
            row["skipped"] = "non-HGLOBAL graphics format"
        else:
            handle = u.GetClipboardData(fmt)
            size = k.GlobalSize(handle) if handle else 0
            row["size"] = size
            if size and size < 100_000_000:
                pointer = k.GlobalLock(handle)
                if pointer:
                    try:
                        blob = c.string_at(pointer, size)
                    finally:
                        k.GlobalUnlock(handle)
                    filename = f"format-{fmt}.bin"
                    (out / filename).write_bytes(blob)
                    row.update(
                        file=filename, sha256=hashlib.sha256(blob).hexdigest(), head=blob[:96].hex()
                    )
        formats.append(row)
finally:
    u.CloseClipboard()
report = {"owner_pid": pid.value, "formats": formats}
(out / "manifest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print(out)
print(json.dumps(report, indent=2))
