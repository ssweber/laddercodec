"""Compile/run the local vendor metadata/serialization probe without packaging JARs."""

import argparse
import os
import subprocess
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, fromfile_prefix_chars="@")
    parser.add_argument("--javac", type=Path, required=True)
    parser.add_argument("--java", type=Path, required=True)
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--class-name", help="Serialize a default instruction instead of inventorying"
    )
    args = parser.parse_args()
    build = Path("build/productivity-java").resolve()
    build.mkdir(parents=True, exist_ok=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    source = Path(__file__).parent / "java/InspectProductivity.java"
    subprocess.run([str(args.javac), "-d", str(build), str(source)], check=True)
    classpath = os.pathsep.join((str(build), str(args.suite / "lib/*")))
    arguments = (
        ["serialize", args.class_name]
        if args.class_name
        else ["inventory", str(args.suite / "lib/productivity.jar")]
    )
    runtime = build / "runtime"
    environment = os.environ.copy()
    for variable in ("ALLUSERSPROFILE", "PROGRAMDATA", "APPDATA", "LOCALAPPDATA"):
        folder = runtime / variable.lower()
        folder.mkdir(parents=True, exist_ok=True)
        environment[variable] = str(folder)
    temporary = runtime / "temp"
    temporary.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            str(args.java),
            "-Djava.awt.headless=true",
            f"-Djava.io.tmpdir={temporary}",
            f"-Dsimserver.path={args.suite / 'service'}",
            f"-Duiserver.path={args.suite / 'data/hmisimulator'}",
            "-cp",
            classpath,
            "InspectProductivity",
            *arguments,
            str(args.output.resolve()),
        ],
        check=True,
        timeout=120,
        cwd=runtime,
        env=environment,
    )


if __name__ == "__main__":
    main()
