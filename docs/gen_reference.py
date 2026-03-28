"""Generate curated MkDocs API reference pages for laddercodec public exports."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path

import mkdocs_gen_files

PACKAGE = "laddercodec"


@dataclass(frozen=True)
class ReferencePage:
    slug: str
    title: str
    tier: str
    summary: str
    symbols: tuple[str, ...]


PAGES: tuple[ReferencePage, ...] = (
    ReferencePage(
        slug="codec",
        title="Codec API",
        tier="Stable Core",
        summary="Encode and decode Click clipboard binary.",
        symbols=("encode", "decode", "Rung"),
    ),
    ReferencePage(
        slug="csv",
        title="CSV I/O API",
        tier="Stable Core",
        summary="Read and write Click Ladder CSV files.",
        symbols=("read_csv", "write_csv"),
    ),
    ReferencePage(
        slug="instructions",
        title="Instructions API",
        tier="Stable Core",
        summary="Domain objects for ladder logic instructions.",
        symbols=("Contact", "CompareContact", "Coil", "Timer", "RawInstruction"),
    ),
)


def _validate_manifest() -> None:
    exported = set(import_module(PACKAGE).__all__)
    assigned = [symbol for page in PAGES for symbol in page.symbols]
    counts = Counter(assigned)

    duplicates = sorted(symbol for symbol, count in counts.items() if count > 1)
    assigned_set = set(counts)
    missing = sorted(exported - assigned_set)
    extra = sorted(assigned_set - exported)

    if not (duplicates or missing or extra):
        return

    parts: list[str] = [f"API reference manifest does not match {PACKAGE}.__all__."]
    if duplicates:
        parts.append(f"Duplicate symbols: {', '.join(duplicates)}")
    if missing:
        parts.append(f"Missing exported symbols: {', '.join(missing)}")
    if extra:
        parts.append(f"Unknown symbols not exported: {', '.join(extra)}")
    raise RuntimeError(" ".join(parts))


def _write_reference_page(page: ReferencePage) -> None:
    doc_rel_path = Path("reference/api") / f"{page.slug}.md"
    lines = [
        f"# {page.title}",
        "",
        f"**Tier:** {page.tier}",
        "",
        page.summary,
        "",
    ]
    for symbol in page.symbols:
        lines.append(f"::: {PACKAGE}.{symbol}")
        lines.append("")

    with mkdocs_gen_files.open(doc_rel_path, "w") as fd:
        fd.write("\n".join(lines).rstrip() + "\n")
    mkdocs_gen_files.set_edit_path(doc_rel_path, Path("docs/gen_reference.py"))


def _write_index() -> None:
    stable_pages = [page for page in PAGES if page.tier == "Stable Core"]
    advanced_pages = [page for page in PAGES if page.tier != "Stable Core"]
    lines = [
        "# API Reference",
        "",
        "This section is generated from an explicit, versioned public API manifest.",
        "",
        "## Stable Core Pages",
        "",
    ]
    for page in stable_pages:
        lines.append(f"- [{page.title}](api/{page.slug}.md)")

    if advanced_pages:
        lines.extend(["", "## Advanced Pages", ""])
        for page in advanced_pages:
            lines.append(f"- [{page.title}](api/{page.slug}.md)")

    with mkdocs_gen_files.open("reference/index.md", "w") as fd:
        fd.write("\n".join(lines).rstrip() + "\n")
    mkdocs_gen_files.set_edit_path("reference/index.md", Path("docs/gen_reference.py"))


_validate_manifest()
for ref_page in PAGES:
    _write_reference_page(ref_page)
_write_index()
