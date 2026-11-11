"""Record what a laddercodec source tree makes of every test fixture.

    uv run python -I devtools/fixture_snapshot.py <src_dir> <out.json>
    uv run python -I devtools/fixture_snapshot.py --diff a.json b.json

``<src_dir>`` is the ``src`` directory of the checkout under test; it goes first on
``sys.path`` so ``import laddercodec`` loads it rather than the installed package.

Every ``.bin``, ``.bin.gz``, ``.scr`` and ``.tmp`` under ``tests/fixtures`` is decoded to
its CSV token text per rung (unknown cells as ``?UnknownInstruction:<len>:<sha256>``,
``raw(...)`` tokens as written).  Every ``.csv`` is read strictly and with
``strict=False`` (``read_relaxed`` is ``"="`` when the two agree).  The decoded or read
rungs are then recorded as:

- ``csv``: sha256 of the CSV writer's rows (decoded files only);
- ``encode`` and ``encode_nicknames``: sha256 of ``encode()`` and of
  ``encode(..., show_nicknames=True)``;
- ``v4_only``: ``find_v4_only()`` as ``[rung index, token text]`` pairs.

A step that raises records ``!<ExceptionClass>: <message>``, with the fixture root and the
src directory written ``<fixtures>`` and ``<src>``; warnings raised while a file is
processed are listed under its ``warnings``.

``--diff`` prints only the differences between two outputs and exits 1 if there is any.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.util
import json
import re
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


#: (pattern, replacement) pairs that turn machine paths in messages into stable names.
_SCRUB: list[tuple[re.Pattern[str], str]] = []


def set_scrub_roots(roots: dict[str, Path]) -> None:
    """Write each root path (either slash style, any case) in messages as its name."""
    _SCRUB.clear()
    resolved = {name: str(root.resolve()) for name, root in roots.items()}
    for name, text in sorted(resolved.items(), key=lambda item: -len(item[1])):
        for form in sorted({text.replace("\\", "/"), text.replace("/", "\\")}):
            pattern = re.escape(form) + r"((?:[\\/][^\s'\"]*)?)"
            _SCRUB.append((re.compile(pattern, re.IGNORECASE), name))


def scrub(text: str) -> str:
    """``text`` with machine paths under the roots written ``<name>/rel/path``."""
    for pattern, name in _SCRUB:
        text = pattern.sub(lambda m, name=name: name + m.group(1).replace("\\", "/"), text)
    return text


def error_text(exc: BaseException) -> str:
    return scrub(f"!{type(exc).__name__}: {exc}")


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


def _encode_sha(laddercodec: Any, rungs: Any, **kwargs: Any) -> str:
    try:
        return sha256(laddercodec.encode(rungs, **kwargs))
    except Exception as exc:
        return error_text(exc)


def _v4_only(laddercodec: Any, rungs: list[Any]) -> Any:
    try:
        found = laddercodec.find_v4_only(rungs)
    except Exception as exc:
        return error_text(exc)
    return [[index, token_text(token)] for index, token in found]


def _encodings(laddercodec: Any, rungs: list[Any], encode_arg: Any) -> dict[str, Any]:
    """Encoded-bytes hashes (plain and with nicknames shown) and the v4-only instructions."""
    if not rungs:
        return {"encode": None, "encode_nicknames": None, "v4_only": []}
    return {
        "encode": _encode_sha(laddercodec, encode_arg),
        "encode_nicknames": _encode_sha(laddercodec, encode_arg, show_nicknames=True),
        "v4_only": _v4_only(laddercodec, rungs),
    }


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
    record.update(_encodings(laddercodec, rungs, encode_arg))
    return record


def read_file(laddercodec: Any, path: Path) -> dict[str, Any]:
    try:
        relaxed: Any = [rung_record(r) for r in laddercodec.read_csv(path, strict=False)]
    except Exception as exc:
        relaxed = error_text(exc)
    try:
        rungs = laddercodec.read_csv(path)
    except Exception as exc:
        return {"read": error_text(exc), "read_relaxed": relaxed}
    encode_arg: Any = rungs[0] if len(rungs) == 1 else rungs
    record: dict[str, Any] = {"rungs": [rung_record(rung) for rung in rungs]}
    record["read_relaxed"] = "=" if relaxed == record["rungs"] else relaxed
    record.update(_encodings(laddercodec, rungs, encode_arg))
    return record


def fixture_files(root: Path) -> list[Path]:
    files = [
        path
        for path in root.rglob("*")
        if path.is_file() and (path.name.endswith(DECODE_SUFFIXES) or path.suffix == ".csv")
    ]
    return sorted(files, key=lambda p: p.relative_to(root).as_posix())


def snapshot(src_dir: str, fixtures: Path, limit: int | None = None) -> dict[str, Any]:
    laddercodec = load_laddercodec(src_dir)
    set_scrub_roots({"<fixtures>": fixtures, "<src>": Path(src_dir)})
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
            record["warnings"] = [scrub(f"{w.category.__name__}: {w.message}") for w in caught]
        cases[key] = record
    failed = sorted(
        key
        for key, value in cases.items()
        if any(isinstance(v, str) and v.startswith("!") for v in value.values())
    )
    try:
        root = fixtures.relative_to(FIXTURES.parent.parent).as_posix()
    except ValueError:
        root = fixtures.as_posix()
    meta = {
        "files": len(cases),
        "files_with_a_failed_step": failed,
        "scope": {"fixtures": root, "limit": limit},
    }
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
