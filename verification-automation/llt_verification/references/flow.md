# End-To-End Flow

## Architecture

```mermaid
flowchart LR
    A["SKILL.md"] --> B["super_bot.py engine"]
    B --> C["Poolside / OpenAI-compatible provider"]
    B --> D["Requirement evaluator"]
    B --> E["Artifact writers"]
    E --> F["RBTCA YAML"]
    E --> G["Python test file"]
    E --> H[".rvstest when Hybrid"]
    B --> I["Pytest / RVS execution"]
    I --> J["Debug loop"]
    J --> E
    I --> K["Proof report"]
```

```mermaid
flowchart TD
    A["User prompt: verify requirement REQID"] --> B["Trigger skill / bot pipeline"]
    B --> C["Locate requirement text and extract requirement details"]
    C --> D["Classify requirement"]
    D --> E["Extract IO variables"]
    E --> F["Extract expressions"]
    F --> G["Extract string / format patterns"]
    G --> H["Save bolded terms and normalized signal names"]
    H --> I["Search requirements/data_dictionary/*.csv, procedure-data/*.csv, and source/header evidence when needed"]
    I --> J{"Method decision"}
    J -->|Direct| K["Direct path: update data_dictionary, uut_dictionary, RBTCA YAML, Python testcase"]
    J -->|Hybrid| L["Hybrid path: update data_dictionary, .rvstest, RBTCA YAML, Python testcase"]
    J -->|Blocked| M["Return blocked with evidence"]
    K --> N["Validate traceability"]
    L --> N
    N --> O["Run relevant pytest or RVS command"]
    O --> P{"Passed?"}
    P -->|No| Q["Debug failure, patch artifacts, rerun"]
    Q --> O
    P -->|Yes| R["Return proof report"]
```

1. Read the user prompt as either a requirement ID or requirement text.
2. Locate the requirement text when an ID is given.
3. Extract the requirement text, inputs, outputs, bolded terms, conditions, calculations, constants, and robustness cases.
4. Save the extracted bolded terms and normalized signal names for reuse during dictionary and source searches.
5. Map the requirement to code:
   - search headers for candidate functions and types
   - search source files only when needed for Hybrid `.rvstest`, debugging, or unresolved mapping failures
   - identify the component, function, signature, inputs, outputs, pointers, structs, globals, constants, and stubs
6. Map the requirement using extracted requirement text, inputs, outputs, bolded terms, headers, and source/data dictionaries:
   - search `requirements/data_dictionaries(ry)/*.csv`
   - search `requirements/data_dictionary/*.csv`
   - search the data dictionary and UUT dictionary files under `verification/test-procedures/procedure-data`
   - search all relevant CSVs in `verification/test-procedures/procedure-data` such as `function.csv`, `enum.csv`, and similar dictionary files
   - identify missing entries that must be created
7. Check existing examples only for style, naming, and structure.
8. Decide the method:
   - Direct when the path is simple and evidence-backed
   - Hybrid when `.rvstest` behavior, dd_ variables, or complex setup is needed
   - Blocked only when evidence or execution cannot be proven
9. Create or update the artifacts that the chosen method needs:
   - If Direct is chosen:
     - `verification/test-procedures/procedure-data/data_dictionary.yaml`
     - `verification/test-procedures/procedure-data/data_dictionary.csv`
     - `verification/test-procedures/procedure-data/uut_dictionary.yaml`
     - `verification/test-procedures/procedure-data/uut_dictionary.csv`
     - `verification/test-procedures/procedure-data/types_struct.csv` only when needed, and only for Direct method
     - `records/rbtca/low_level/FAF-LLR-xxx.yaml`
     - `verification/test-cases/low_level/test_FAF-LLR-xxx.py`
   - If Hybrid is chosen:
     - `verification/test-procedures/procedure-data/data_dictionary.yaml`
     - `verification/test-procedures/procedure-data/data_dictionary.csv`
     - no `uut_dictionary.yaml`
     - no `uut_dictionary.csv`
     - no `types_struct.csv`
     - the `.rvstest` file
     - `records/rbtca/low_level/FAF-LLR-xxx.yaml`
     - `verification/test-cases/low_level/test_FAF-LLR-xxx.py`
     - in the `.rvstest` file, use `dd_` prefixed verification identifiers such as `dd_donkey`
     - in `data_dictionary.yaml` and `data_dictionary.csv`, keep the base name without the `dd_` prefix, such as `donkey`
10. Validate traceability between the requirement, RBTCA, Python tests, and dictionaries.
11. Run the relevant pytest or RVS command and capture the result.
12. Debug failures only when the failure is actionable and evidence-backed.
13. Return a proof report with the requirement mapping, source mapping, data mapping, method decision, files changed, commands run, test results, and final status.
