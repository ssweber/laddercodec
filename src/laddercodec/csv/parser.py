"""CSV row/file parser for Click Ladder canonical CSV rows."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Literal

from .ast import CanonicalRow, ParsedCsvFileAst, RowAst, RungAst
from .contract import TOTAL_COLUMNS, is_valid_marker, validate_header
from .token_parser import parse_af_token, parse_condition_token


def _detect_file_role(path: Path) -> tuple[Literal["main", "subroutine"], str | None]:
    if path.name == "main.csv":
        return "main", None
    if path.name.startswith("sub_") and path.suffix.lower() == ".csv":
        return "subroutine", path.stem[len("sub_") :]
    return "subroutine", None


def _canonical_row_from_fields(fields: list[str]) -> CanonicalRow:
    marker = fields[0].strip() if fields else ""
    if not is_valid_marker(marker):
        raise ValueError(f"Invalid marker {marker!r}; expected 'R', '#', or blank")

    # Comment rows may be short (just marker + text); pad to full width.
    # Preserve whitespace in column A for code-style comments (indentation).
    if marker == "#":
        padded = fields + [""] * (TOTAL_COLUMNS - len(fields))
        text = padded[1] if len(padded) > 1 else ""
        rest = tuple(cell.strip() for cell in padded[2:-1])
        conditions = (text,) + rest
        if any(cell for cell in conditions[1:]):
            raise ValueError("Comment rows may only populate column A text")
        return CanonicalRow(marker=marker, conditions=conditions, af="")

    if len(fields) != TOTAL_COLUMNS:
        raise ValueError(f"Expected {TOTAL_COLUMNS} columns; got {len(fields)}")

    conditions = tuple(cell.strip() for cell in fields[1:-1])
    af = fields[-1].strip()

    return CanonicalRow(marker=marker, conditions=conditions, af=af)


def _row_ast(canonical: CanonicalRow) -> RowAst:
    condition_nodes = tuple(parse_condition_token(token) for token in canonical.conditions)
    af_node = parse_af_token(canonical.af)
    return RowAst(canonical=canonical, condition_nodes=condition_nodes, af_node=af_node)


def _segment_rungs(rows: tuple[RowAst, ...]) -> tuple[RungAst, ...]:
    rungs: list[RungAst] = []
    current: list[RowAst] = []
    current_comments: list[RowAst] = []
    pending_comments: list[RowAst] = []

    for row in rows:
        if row.canonical.is_comment:
            if current:
                rungs.append(RungAst(comment_rows=tuple(current_comments), rows=tuple(current)))
                current = []
                current_comments = []
            pending_comments.append(row)
            continue

        if row.canonical.marker == "R":
            if current:
                rungs.append(RungAst(comment_rows=tuple(current_comments), rows=tuple(current)))
            current = [row]
            current_comments = pending_comments
            pending_comments = []
            continue

        if not current:
            raise ValueError("Continuation row encountered before first 'R' marker")

        current.append(row)

    if pending_comments:
        raise ValueError("Comment row encountered without following 'R' marker")

    if current:
        rungs.append(RungAst(comment_rows=tuple(current_comments), rows=tuple(current)))

    return tuple(rungs)


def _load_canonical_rows(path: Path) -> tuple[CanonicalRow, ...]:
    rows: list[CanonicalRow] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        header: list[str] | None = None
        for parsed in reader:
            if not parsed:
                continue
            if header is None:
                header = [cell.strip() for cell in parsed]
                validate_header(header)
                continue
            rows.append(_canonical_row_from_fields(parsed))

    if header is None:
        raise ValueError(f"CSV file {path} is empty; expected header row")
    return tuple(rows)


def parse_row(row: str) -> CanonicalRow:
    """Parse a single canonical CSV row string into a ``CanonicalRow``."""
    fields = next(csv.reader([row]), [])
    return _canonical_row_from_fields(fields)


def parse_csv_file(
    path: Path | str,
    syntax: Literal["canonical"] = "canonical",
) -> ParsedCsvFileAst:
    path_obj = Path(path)
    canonical_rows = _load_canonical_rows(path_obj)
    rows = tuple(_row_ast(canonical) for canonical in canonical_rows)
    rungs = _segment_rungs(rows)
    role, subroutine_slug = _detect_file_role(path_obj)
    return ParsedCsvFileAst(
        path=path_obj,
        role=role,
        subroutine_slug=subroutine_slug,
        rows=rows,
        rungs=rungs,
    )
