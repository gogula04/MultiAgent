# Verification Automation Steps

This document explains how to run the multi-agent verification tool against the real `foundations-and-framework` repo inside a VS Code container.

## 1. Open the company repo in VS Code

1. Open `foundations-and-framework` in Visual Studio Code.
2. Use **Reopen in Container**.
3. Wait for the container to finish building and attaching.

## 2. Keep the tool repo separate from the scanned repo

Use two folders in the container:

- `foundations-and-framework` = the repo to scan
- `MultiAgent/verification-automation` = the verification tool

Do not point the tool at its own repo when scanning requirements.

## 3. Get the tool repo into the container

If the tool repo is not already present, clone it next to the company repo:

```bash
cd /workspaces
git clone https://github.com/gogula04/MultiAgent.git
```

Then install the tool:

```bash
cd /workspaces/MultiAgent/verification-automation
python3 -m pip install -e .
```

## 4. Optional: configure Poolside on the company machine

Set these environment variables only on the company laptop or in an authorized company environment:

```bash
export POOLSIDE_BASE_URL="https://poolside-col-web.xeta.rtx.com/openai/v1"
export POOLSIDE_API_KEY="ps-<your-key>"
export POOLSIDE_MODEL="edx-malibu-model-2-1"
```

## 5. Launch the web UI against the real repo

Run the UI from the tool repo, but point it at the company repo root:

```bash
verification-automation-web \
  --repo-root /workspaces/foundations-and-framework \
  --output-dir /workspaces/foundations-and-framework/.verification-automation
```

The UI listens on:

```text
http://127.0.0.1:8787/
```

## 6. Use the UI

1. Enter a requirement ID or name, for example `FAF-LLR-1323`.
2. Confirm the repo root is the real `foundations-and-framework` folder.
3. Choose a mode:
   - `Auto`
   - `Direct`
   - `Hybrid`
   - `Manual`
4. Click **Run Verification**.

The tool should then:

- resolve the requirement from the repo
- extract bolded requirement terms
- map requirement terms to source and verification artifacts
- generate drafts
- wait for review if review mode is enabled
- execute tests
- collect coverage
- generate proof and traceability output

## 7. CLI usage

If you prefer the command line instead of the UI:

```bash
verification-automation "FAF-LLR-1323" \
  --repo-root /workspaces/foundations-and-framework \
  --text "The Push Element operation utility shall use Mutex Lock..." \
  --mode Auto
```

## 8. What the tool should do when the repo is correct

For a valid requirement in the real repo, the pipeline should:

1. Intake the requirement
2. Discover repository evidence
3. Parse the requirement text
4. Map bolded terms to source and dictionaries
5. Select Direct, Hybrid, or Manual mode
6. Generate draft artifacts
7. Wait for review if requested
8. Run execution
9. Collect coverage results
10. Produce a proof and traceability package

## 9. What the tool should do when the requirement is missing

If the requirement ID cannot be resolved from the repo, the pipeline should stop and show a blocked result:

- no artifact generation
- no fake success
- no proof report
- no coverage evidence

## 10. Quick sanity check

Before trusting the output, verify:

- the repo root is `foundations-and-framework`
- the requirement exists in `requirements/HLR` or `requirements/LLR`
- the mode shown in the UI is the one you want
- the output folder is inside the company repo or another approved location

