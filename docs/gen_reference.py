"""Generate curated API reference pages for laddercodec public exports."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path

PACKAGE = "laddercodec"
DOCS_DIR = Path(__file__).parent


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
        summary="Encode and decode Click clipboard binary and program files.",
        symbols=(
            "encode",
            "decode",
            "decode_program",
            "Rung",
            "Program",
            "Project",
            "find_v4_only",
            "is_v4_only",
            "check",
            "Finding",
            "FieldError",
            "AddressError",
            "Reason",
            "Code",
            "CLICK_IDS",
            "LaddercodecError",
            "DecodeError",
            "EncodeError",
            "WriterError",
            "CsvError",
            "LegacyEncodingWarning",
            "RefusedFieldWarning",
            "UndecodedRungWarning",
            "UndecodedCommentWarning",
        ),
    ),
    ReferencePage(
        slug="csv",
        title="CSV I/O API",
        tier="Stable Core",
        summary="Read and write Click Ladder CSV files.",
        symbols=("read_csv", "write_csv", "CsvLocation"),
    ),
    ReferencePage(
        slug="instructions",
        title="Instructions API",
        tier="Stable Core",
        summary=(
            "Domain objects for ladder logic instructions. `Email`, `Home`, `Position` and"
            " `Velocity` are provisional: their fields are named after CLICK's tag ids and"
            " will change."
        ),
        symbols=(
            "ConditionInstruction",
            "AfInstruction",
            "ConditionToken",
            "AfToken",
            "Contact",
            "CompareContact",
            "Tee",
            "Coil",
            "OutVariant",
            "Timer",
            "Counter",
            "Copy",
            "BlockCopy",
            "Fill",
            "Pack",
            "Unpack",
            "Shift",
            "Search",
            "Drum",
            "Math",
            "Call",
            "Return",
            "End",
            "ForLoop",
            "Next",
            "Break",
            "Continue",
            "Send",
            "Receive",
            "ModbusAddress",
            "ModbusRtuTarget",
            "ModbusTcpTarget",
            "RawInstruction",
            "Undecoded",
            "UnknownCondition",
            "UnknownInstruction",
            "Email",
            "Home",
            "Position",
            "Velocity",
            "constant_text",
            "replace",
        ),
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

    destination = DOCS_DIR / doc_rel_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _write_index() -> None:
    stable_pages = [page for page in PAGES if page.tier == "Stable Core"]
    advanced_pages = [page for page in PAGES if page.tier != "Stable Core"]
    lines = [
        "# API Reference",
        "",
        "This section is generated from an explicit, versioned public API manifest.",
        "",
        "Every name in `laddercodec.__all__` is public API; everything else is internal and may change in any release. Message text is not API: match on the exception class, its `code` or its fields.",
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

    destination = DOCS_DIR / "reference/index.md"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


_validate_manifest()
for ref_page in PAGES:
    _write_reference_page(ref_page)
_write_index()
