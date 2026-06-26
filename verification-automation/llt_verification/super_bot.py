#!/usr/bin/env python3
"""CLI entrypoint for the LLT Super Bot."""

from __future__ import annotations

import json
import sys

from bot.super_bot import run_super_bot


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python super_bot.py FAF-LLR-401")
        print("       python super_bot.py 'verify requirement FAF-LLR-401'")
        print("Options:")
        print("  --dry-run")
        print("  --continue-on-failure")
        print("  --json")
        sys.exit(1)

    dry_run = "--dry-run" in sys.argv
    continue_on_failure = "--continue-on-failure" in sys.argv
    json_only = "--json" in sys.argv
    args = [arg for arg in sys.argv[1:] if not arg.startswith("--")]

    if not args:
        print("Error: no requirement specified")
        sys.exit(1)

    result = run_super_bot(
        args[0],
        dry_run=dry_run,
        continue_on_failure=continue_on_failure,
    )

    if not json_only:
        print("\n" + "=" * 60)
        print("SUPER BOT REPORT")
        print("=" * 60)

    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
