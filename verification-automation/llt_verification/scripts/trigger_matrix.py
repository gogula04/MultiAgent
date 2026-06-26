#!/usr/bin/env python3
"""Print the LLT verification trigger matrix."""

import argparse
import json
from pathlib import Path

POSITIVE_PROMPTS = [
    "verify requirement FAF-LLR-401",
    "verify requirement FAF-LLR-123",
    "verify requirement REQID",
    "verify FAF-LLR-401 end to end",
    "verify requirement FAF-LLR-401 and generate proof",
    "verify this requirement: FAF-LLR-401",
]

NEAR_MISS_PROMPTS = [
    "analyze requirement FAF-LLR-401",
    "summarize FAF-LLR-401",
    "review this requirement",
    "run tests for FAF-LLR-401",
    "explain FAF-LLR-401",
    "verify my code",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Print the LLT verification trigger matrix.")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the trigger matrix as JSON for eval tooling.",
    )
    args = parser.parse_args()

    payload = {
        "positive_prompts": POSITIVE_PROMPTS,
        "near_miss_prompts": NEAR_MISS_PROMPTS,
        "reference": str(Path(__file__).resolve().parent.parent / "references" / "trigger-tests.md"),
    }

    if args.json:
        print(json.dumps(payload, indent=2))
        return

    print("# LLT Verification Trigger Matrix")
    print()
    print("Positive prompts:")
    for prompt in POSITIVE_PROMPTS:
        print(f"- {prompt}")
    print()
    print("Near-miss prompts:")
    for prompt in NEAR_MISS_PROMPTS:
        print(f"- {prompt}")
    print()
    print("Reference:", payload["reference"])


if __name__ == "__main__":
    main()
