# LLT Verification Agent

This repository contains a skill-guided, Poolside-only LLT verification agent built around a peer-agent workflow:

- [SKILL.md](/Users/venkateshgogula/Desktop/llt_verification/SKILL.md)
- [llt_verification_agent.py](/Users/venkateshgogula/Desktop/llt_verification/llt_verification_agent.py)
- [agent_runtime/](/Users/venkateshgogula/Desktop/llt_verification/agent_runtime)
- [agents/](/Users/venkateshgogula/Desktop/llt_verification/agents)
- [references/](/Users/venkateshgogula/Desktop/llt_verification/references)
- [references/legacy-extraction-prompts/](/Users/venkateshgogula/Desktop/llt_verification/references/legacy-extraction-prompts)
- [requirements.txt](/Users/venkateshgogula/Desktop/llt_verification/requirements.txt)

## Technical Stack

- LLM: Poolside `laguna_m_fp8_fp8kv_re_04_2026` model
- Embeddings: Local HuggingFace `BAAI/bge-m3` for dense retrieval in the current FAISS index
- Vector Store: FAISS
- Frameworks: LangChain community components and `langchain-huggingface`
- Runtime: coordinator plus peer agents with typed package handoffs
- Fallback extraction: legacy prompt bundle under `references/legacy-extraction-prompts/` for classification, IO extraction, expression extraction, math extraction, and format extraction when the deterministic parser leaves gaps

## Agent Shape

- Coordinator entrypoint: `llt_verification_agent.py`
- Coordinator: `agent_runtime/coordinator.py`
- Peer stages: `agent_runtime/stages/`
- Message/state helpers: `agent_runtime/message.py`, `agent_runtime/state.py`, `agent_runtime/validators.py`
- Stage configs: `agents/*.yaml`

## How To Use

- Start with [SKILL.md](/Users/venkateshgogula/Desktop/llt_verification/SKILL.md)
- Read [references/flow.md](/Users/venkateshgogula/Desktop/llt_verification/references/flow.md) for the peer-agent flow
- Use `python llt_verification_agent.py --index` to build the repo index
- Use `python llt_verification_agent.py "verify requirement FAF-LLR-401"` for the prompt-style agent invocation
- Use `python llt_verification_agent.py --query "verify requirement FAF-LLR-401"` for a RAG-backed question
- Use `python llt_verification_agent.py --interactive` for chat mode
- Use `python llt_verification_agent.py --verify "verify requirement FAF-LLR-401"` for the full verification flow

## Notes

- Poolside is the only runtime backend.
- Direct and Hybrid are method branches inside the peer workflow.
- The reviewer is the final quality gate before the proof report is accepted.
- The requirement stage may consult the legacy prompt bundle only as a fallback when the deterministic parser cannot safely recover classification, IO variables, expressions, math, or format details.
