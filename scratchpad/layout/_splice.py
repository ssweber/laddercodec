"""One-off: replace a span of a file (from START up to END) with the text of another file."""

import sys
from pathlib import Path

target, new, start, end = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], sys.argv[4]
src = target.read_text(encoding="utf-8")
i = src.index(start)
j = src.index(end, i)
target.write_text(src[:i] + new.read_text(encoding="utf-8") + src[j:], encoding="utf-8")
print("spliced", i, j)
