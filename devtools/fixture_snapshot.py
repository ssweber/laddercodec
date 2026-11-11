"""Record what a laddercodec source tree makes of every test fixture.

    uv run python -I devtools/fixture_snapshot.py <src_dir> <out.json>
    uv run python -I devtools/fixture_snapshot.py --diff a.json b.json

``<src_dir>`` is the ``src`` directory of the checkout under test; it goes first on
``sys.path`` so ``import laddercodec`` loads it rather than the installed package.

Every ``.bin``, ``.bin.gz``, ``.scr`` and ``.tmp`` under ``tests/fixtures`` is decoded to
its CSV token text per rung (unknown cells as ``?UnknownInstruction:<len>:<sha256>``,
``raw(...)`` tokens as written), then written back through the CSV writer and re-encoded;
those two results are recorded as a sha256 of their output.  Every ``.csv`` is read and
encoded, recorded as its tokens and a sha256 of the encoded bytes.  A step that raises
records ``!<ExceptionClass>: <message>``; warnings raised while a file is processed are
listed under its ``warnings``.

``--diff`` prints only the differences between two outputs and exits 1 if there is any.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.util
import json
import sys
import warnings
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
DECODE_SUFFIXES = (".bin", ".bin.gz", ".scr", ".tmp")


def load_laddercodec(src_dir: str) -> Any:
    """Import laddercodec from ``src_dir``; refuse a copy loaded from anywhere else."""
    src = Path(src_dir).resolve()
    if not (src / "laddercodec" / "__init__.py").is_file():
        raise SystemExit(f"{src} has no laddercodec package")
    sys.path.insert(0, str(src))
    import laddercodec

    loaded = Path(laddercodec.__file__).resolve().parent.parent
    if loaded != src:
        raise SystemExit(f"laddercodec loaded from {loaded}, not {src}")
    return laddercodec


def error_text(exc: BaseException) -> str:
    return f"!{type(exc).__name__}: {exc}"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def token_text(token: Any) -> str:
    """CSV text of one decoded cell; pinned boxes add their pin rows."""
    from laddercodec.instructions import UnknownCondition, UnknownInstruction
    from laddercodec.model import AfInstruction, ConditionInstruction, PinnedInstruction

    if isinstance(token, str):
        return token
    if isinstance(token, (UnknownCondition, UnknownInstruction)):
        return f"?{type(token).__name__}:{len(token.raw)}:{sha256(token.raw)}"
    if isinstance(token, (AfInstruction, ConditionInstruction)):
        try:
            text = token.to_csv()
        except Exception as exc:
            return f"{type(token).__name__}{error_text(exc)}"
        if isinstance(token, PinnedInstruction):
            text += f" @pins={list(token.pin_rows)} {list(token.pin_labels())}"
        return text
    return f"?{type(token).__name__}:{token!r}"


def _trim(row: list[str]) -> list[str]:
    end = len(row)
    while end and row[end - 1] == "":
        end -= 1
    return row[:end]


def rung_record(rung: Any) -> dict[str, Any]:
    return {
        "rows": rung.logical_rows,
        "comment": rung.comment,
        "rtf": None if rung.comment_rtf is None else sha256(rung.comment_rtf),
        "conditions": [_trim([token_text(t) for t in row]) for row in rung.conditions],
        "af": [token_text(t) for t in rung.instructions],
    }


def _writer_sha(rungs: list[Any]) -> str:
    from laddercodec.csv.writer import decoded_rung_to_rows

    try:
        rows = [decoded_rung_to_rows(rung) for rung in rungs]
    except Exception as exc:
        return error_text(exc)
    return sha256(json.dumps(rows, ensure_ascii=False).encode("utf-8"))


def _encode_sha(laddercodec: Any, rungs: Any) -> str:
    try:
        return sha256(laddercodec.encode(rungs))
    except Exception as exc:
        return error_text(exc)


def decode_file(laddercodec: Any, path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    if path.name.endswith(".gz"):
        data = gzip.decompress(data)
    record: dict[str, Any] = {}
    if path.suffix in (".scr", ".tmp"):
        try:
            program = laddercodec.decode_program(data)
        except Exception as exc:
            return {"decode": error_text(exc)}
        record["name"] = program.name
        record["prog_idx"] = program.prog_idx
        rungs = list(program.rungs)
        encode_arg: Any = rungs[0] if len(rungs) == 1 else rungs
    else:
        try:
            decoded = laddercodec.decode(data)
        except Exception as exc:
            return {"decode": error_text(exc)}
        rungs = decoded if isinstance(decoded, list) else [decoded]
        encode_arg = decoded
    record["rungs"] = [rung_record(rung) for rung in rungs]
    record["csv"] = _writer_sha(rungs)
    record["reencode"] = _encode_sha(laddercodec, encode_arg) if rungs else None
    return record


def read_file(laddercodec: Any, path: Path) -> dict[str, Any]:
    try:
        rungs = laddercodec.read_csv(path)
    except Exception as exc:
        return {"read": error_text(exc)}
    encode_arg: Any = rungs[0] if len(rungs) == 1 else rungs
    return {
        "rungs": [rung_record(rung) for rung in rungs],
        "encode": _encode_sha(laddercodec, encode_arg) if rungs else None,
    }


def fixture_files(root: Path) -> list[Path]:
    files = [
        path
        for path in root.rglob("*")
        if path.is_file() and (path.name.endswith(DECODE_SUFFIXES) or path.suffix == ".csv")
    ]
    return sorted(files, key=lambda p: p.relative_to(root).as_posix())


def snapshot(src_dir: str, fixtures: Path, limit: int | None = None) -> dict[str, Any]:
    laddercodec = load_laddercodec(src_dir)
    files = fixture_files(fixtures)
    if limit is not None:
        files = files[:limit]
    cases: dict[str, Any] = {}
    for path in files:
        key = path.relative_to(fixtures).as_posix()
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            if path.suffix == ".csv":
                record = read_file(laddercodec, path)
            else:
                record = decode_file(laddercodec, path)
        if caught:
            record["warnings"] = [f"{w.category.__name__}: {w.message}" for w in caught]
        cases[key] = record
    failed = sorted(
        key
        for key, value in cases.items()
        if any(isinstance(v, str) and v.startswith("!") for v in value.values())
    )
    meta = {"files": len(cases), "files_with_a_failed_step": failed}
    return {"tool": "fixture_snapshot", "meta": meta, "cases": cases}


def load_diff_module() -> Any:
    path = Path(__file__).resolve().parent / "identity_diff.py"
    spec = importlib.util.spec_from_file_location("identity_diff", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("src_dir", nargs="?", help="src directory holding laddercodec")
    parser.add_argument("out", nargs="?", help="JSON output path")
    parser.add_argument("--diff", nargs=2, metavar=("A", "B"), help="compare two outputs")
    parser.add_argument("--fixtures", type=Path, default=FIXTURES, help="fixture root")
    parser.add_argument("--limit", type=int, help="only the first N fixture files")
    args = parser.parse_args(argv)
    if args.diff:
        return load_diff_module().diff_files(*args.diff)
    if not args.src_dir or not args.out:
        parser.error("src_dir and out are required unless --diff is given")
    doc = snapshot(args.src_dir, args.fixtures.resolve(), args.limit)
    with open(args.out, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(doc, handle, ensure_ascii=False, sort_keys=True, indent=1)
        handle.write("\n")
    print(f"{doc['meta']['files']} files -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
