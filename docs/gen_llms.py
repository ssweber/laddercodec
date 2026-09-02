"""Generate a concise llms.txt index for the rendered Zensical site."""

from __future__ import annotations

import argparse
import fnmatch
from collections.abc import Iterator, Sequence
from pathlib import Path, PurePosixPath
from urllib.parse import urljoin

import yaml


ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "mkdocs.yml"
DOCS_DIR = ROOT / "docs"


def _navigation_titles(nav: list[object]) -> dict[str, str]:
    titles: dict[str, str] = {}

    def visit(items: Sequence[object]) -> None:
        for item in items:
            if not isinstance(item, dict):
                continue
            for title, target in item.items():
                if isinstance(target, str):
                    titles[target] = str(title)
                elif isinstance(target, list):
                    visit(target)

    visit(nav)
    return titles


def _source_uris(pattern: str) -> Iterator[str]:
    candidates = sorted(
        path.relative_to(DOCS_DIR).as_posix() for path in DOCS_DIR.rglob("*.md")
    )
    yield from fnmatch.filter(candidates, pattern)


def _destination_uri(source_uri: str) -> str:
    source = PurePosixPath(source_uri)
    if source.name == "index.md":
        parent = source.parent.as_posix()
    else:
        parent = source.with_suffix("").as_posix()
    return "" if parent == "." else f"{parent}/"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the LLM documentation index.")
    parser.add_argument("site", type=Path, help="Rendered Zensical site directory")
    args = parser.parse_args()

    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    site_dir = args.site.resolve()
    if not site_dir.is_dir():
        raise RuntimeError(f"Rendered site directory does not exist: {site_dir}")

    base_url = config["site_url"]
    if not base_url.endswith("/"):
        base_url += "/"
    titles = _navigation_titles(config["nav"])

    output = f"# {config['site_name']}\n\n"
    if description := config.get("site_description"):
        output += f"> {description}\n\n"

    seen: set[str] = set()
    for section, patterns in config["extra"]["llmstxt"]["sections"].items():
        output += f"## {section}\n\n"
        for pattern in patterns:
            matches = list(_source_uris(pattern)) if "*" in pattern else [pattern]
            for source_uri in matches:
                if source_uri in seen:
                    continue
                seen.add(source_uri)
                title = titles.get(source_uri)
                if title is None:
                    raise RuntimeError(f"Navigation title not found for {source_uri}")
                destination_uri = _destination_uri(source_uri)
                html_path = site_dir / Path(destination_uri) / "index.html"
                if not html_path.is_file():
                    raise RuntimeError(f"Rendered page not found: {html_path}")
                output += f"- [{title}]({urljoin(base_url, destination_uri)})\n"
        output += "\n"

    (site_dir / "llms.txt").write_text(output, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
