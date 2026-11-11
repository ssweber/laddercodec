"""Compare each rung's AF blob across CLICK copy-backs and our re-encode.

Usage: uv run python scratchpad/click-v4/captures/compare_af.py A.bin [B.bin ...]

For every rung (comment line 1 = id), prints the func code (0x3218) per source and
every tag whose value differs between sources.  Sources: each .bin given, then
"ours" = encode(decode(first .bin)).
"""

from __future__ import annotations

import sys
from pathlib import Path

from laddercodec import encode
from laddercodec.decode import decode, inspect_cells
from laddercodec.instructions.raw import _decompose_blob


def _rungs(data: bytes) -> list:
    out = decode(data)
    return out if isinstance(out, list) else [out]


def _af_fields(data: bytes, count: int) -> list[dict[str, str] | None]:
    """Per rung: field key -> value.  A repeated tag is keyed ``tag[n]`` (n-th occurrence)."""
    cells = inspect_cells(data, [(i, 0, "AF") for i in range(count)])
    out: list[dict[str, str] | None] = []
    for cell in cells:
        blob = cell.raw[0x25:-0x10] if cell.raw else b""
        try:
            _cls, _type, _parts, _extra, fields = _decompose_blob(blob)
        except Exception:  # noqa: BLE001 - empty / NOP cell
            out.append(None)
            continue
        counts: dict[int, int] = {}
        for tag, _s, _v in fields:
            counts[tag] = counts.get(tag, 0) + 1
        seen: dict[int, int] = {}
        keyed: dict[str, str] = {}
        for tag, _s, value in fields:
            n = seen.get(tag, 0)
            seen[tag] = n + 1
            keyed[f"{tag:04x}[{n}]" if counts[tag] > 1 else f"{tag:04x}"] = value
        out.append(keyed)
    return out


def main() -> None:
    paths = [Path(p) for p in sys.argv[1:]]
    datas = [p.read_bytes() for p in paths]
    rungs = _rungs(datas[0])
    n = len(rungs)
    sources = {p.stem: _af_fields(d, n) for p, d in zip(paths, datas, strict=True)}
    try:
        sources["ours"] = _af_fields(encode(rungs), n)
    except Exception as exc:  # noqa: BLE001
        print(f"(re-encode failed: {exc})")
    width = max(len(s) for s in sources)
    for i, rung in enumerate(rungs):
        rid = (rung.comment or "").split("\n")[0] or f"rung{i}"
        per = {name: fields[i] for name, fields in sources.items()}
        print(f"== {rid}")
        for name, f in per.items():
            print(f"  {name:{width}}  3218={f.get('3218') if f else None}")
        tags = sorted({t for f in per.values() if f for t in f})
        for tag in tags:
            values = {name: (f.get(tag) if f else None) for name, f in per.items()}
            if len(set(values.values())) > 1 and tag != "3218":
                print(f"  diff {tag}: " + "  ".join(f"{k}={v!r}" for k, v in values.items()))


if __name__ == "__main__":
    main()
