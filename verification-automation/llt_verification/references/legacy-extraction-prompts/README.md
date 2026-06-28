# Legacy Extraction Prompts

These prompts are fallback-only helpers for requirement parsing.

The active LLT verification path stays deterministic and code-driven first.
If the requirement extractor cannot safely recover classification, IO
variables, expressions, math details, or format details, the requirement
agent can load one of these prompts and ask Poolside to fill the gaps.

Files in this folder:

- `classify_req.txt`
- `io_vars_prompt_with_example.txt`
- `expression_prompt.txt`
- `math_extraction_prompt.txt`
- `format_extration.txt`
- `formatted_output_exytraction_prompt.txt`
- `export-data.json`
