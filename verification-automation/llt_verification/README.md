# LLT Verification

This repository now behaves as a skill package first, with a bot pipeline behind it.

- Start with [SKILL.md](/Users/venkateshgogula/Desktop/llt_verification/SKILL.md).
- Read [references/flow.md](/Users/venkateshgogula/Desktop/llt_verification/references/flow.md) for the architecture and workflow.
- Read [references/trigger-tests.md](/Users/venkateshgogula/Desktop/llt_verification/references/trigger-tests.md) for activation checks.
- Use `python super_bot.py FAF-LLR-401` for the orchestrated bot flow.
- To point the bot at Poolside, set `POOLSIDE_BASE_URL`, `POOLSIDE_API_KEY`, `POOLSIDE_AGENT_MODEL`, and optionally `POOLSIDE_AGENT_NAME`.
- Use the Python entrypoints only as execution helpers behind the skill.
