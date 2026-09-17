#!/usr/bin/env python3
"""Copy the portable skill into a host's discovery directory, without overwriting."""
import argparse
import shutil
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--target", choices=["claude", "codex"])
    group.add_argument("--directory", type=Path, help="Framework's skill parent directory")
    args = parser.parse_args()
    parent = args.directory
    if parent is None:
        parent = Path.home() / (".claude/skills" if args.target == "claude" else ".agents/skills")
    destination = parent.expanduser().absolute() / "laptop-link"
    if destination.exists() or destination.is_symlink():
        parser.error(f"Already exists: {destination}. Review it before replacing or removing it.")
    source = Path(__file__).resolve().parent.parent / "skills/laptop-link"
    shutil.copytree(source, destination)
    print(f"Installed {destination}")
    print("Register the laptop-link-mcp server separately, then reload your host's skills.")


if __name__ == "__main__":
    main()
