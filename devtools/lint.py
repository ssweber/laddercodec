import argparse
import subprocess
import sys
from pathlib import Path

from funlog import log_calls
from rich import get_console, reconfigure
from rich import print as rprint

# Use Path objects to ensure slashes are correct for the current OS/Shell
SRC_PATHS = [str(Path("src")), str(Path("tests")), str(Path("devtools"))]

# No emojis on legacy windows.
reconfigure(emoji=not get_console().options.legacy_windows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run lint/type checks for the repository.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Run read-only checks suitable for CI (no autofix).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rprint()

    errcount = 0

    # 1. Ruff Linter
    if args.check:
        errcount += run(["ruff", "check", *SRC_PATHS])
    else:
        errcount += run(["ruff", "check", "--fix", *SRC_PATHS])

    # 2. Ruff Formatter
    if args.check:
        errcount += run(["ruff", "format", "--check", *SRC_PATHS])
    else:
        errcount += run(["ruff", "format", *SRC_PATHS])

    errcount += run(["ty", "check"])

    rprint()

    if errcount != 0:
        rprint(f"[bold red]:x: Lint failed with {errcount} errors.[/bold red]")
    else:
        rprint("[bold green]:white_check_mark: Lint passed![/bold green]")
    rprint()

    return errcount


@log_calls(level="warning", show_timing_only=True)
def run(cmd: list[str]) -> int:
    rprint()
    # Join with native separators for display
    display_cmd = " ".join(cmd)
    rprint(f"[bold green]:arrow_forward: {display_cmd}[/bold green]")

    errcount = 0
    try:
        subprocess.run(cmd, text=True, check=True)
    except subprocess.CalledProcessError as e:
        rprint(f"[bold red]Error: {e}[/bold red]")
        errcount = 1
    except FileNotFoundError as e:
        rprint(f"[bold red]Executable not found: {e}[/bold red]")
        errcount = 1

    return errcount


if __name__ == "__main__":
    sys.exit(main())
