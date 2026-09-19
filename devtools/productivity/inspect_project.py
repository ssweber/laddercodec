"""Inspect a Productivity archive without extracting files or modifying it."""

import argparse
from pathlib import Path

from laddercodec.productivity import decode_program, decode_project


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    args = parser.parse_args()
    project = decode_project(args.project.read_bytes())
    print(f"Header: {project.header.hex()}; entries: {len(project.entries)}; checksums verified")
    for entry in project.entries:
        print(f"  {entry.name}: {len(entry.data)} bytes")
    for name in project.program_names:
        print(name)
        for row in decode_program(project.read(name)).rungs:
            for element in row.elements:
                instruction = element.instruction
                if instruction is not None:
                    tags = ", ".join(f"{tag.name} ({tag.system_id})" for tag in instruction.tags)
                    print(
                        f"  {row.number}.{row.subrung} [{element.position}] {instruction.kind}: {tags}"
                    )


if __name__ == "__main__":
    main()
