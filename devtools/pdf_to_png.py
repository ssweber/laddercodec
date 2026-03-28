# /// script
# requires-python = ">=3.11"
# dependencies = ["pymupdf"]
# ///
"""Convert PDF pages to PNG files for visual inspection."""

import sys
from pathlib import Path

import fitz  # pymupdf

pdf_path = Path(sys.argv[1])
out_dir = pdf_path.parent
doc = fitz.open(pdf_path)

for i, page in enumerate(doc):
    pix = page.get_pixmap(dpi=200)
    out = out_dir / f"{pdf_path.stem}_page{i + 1}.png"
    pix.save(str(out))
    print(f"  {out}")

print(f"Done: {len(doc)} pages")
