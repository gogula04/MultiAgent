# Test Selection Guide

## Coverage Goals

- Inputs should cover normal range and robustness cases.
- Logic should cover true/false branches and independence where needed.
- Math should cover the expression plus boundary or overflow/underflow behavior when applicable.
- Summary should accurately report covered cases, required cases, and missing cases.

## Value Selection

- Integers and floats: minimum, maximum, boundary, just below, just above, zero, and out-of-range values when meaningful.
- Booleans: true and false.
- Enumerations: all valid values and an out-of-range case when required.
- Strings: minimum length, maximum length, empty/null, invalid characters, and length overflow/underflow when relevant.

## Direct Method Decision Criteria

Use Direct when the UUT is straightforward:

- Single top-level `step` function, with no nested or cascaded execution
- At most one initialization function
- Normal data flow and control flow, with no complex state machine

Use Direct when the test flow is straightforward:

- Test cases execute directly in the RapiTest harnessed environment
- The test should stimulate the UUT, run it, and measure outputs in one flow
- Test files follow the `test_*.py` naming pattern

Do not use Direct when:

- Multiple step functions or complex orchestration are needed
- The UUT requires multiple init routines with complex dependencies
- You need custom harness behavior beyond standard `FW.Run()`

### Direct Decision Process

1. Check the UUT architecture.
2. Ask whether it has one step function and at most one init function.
3. Ask whether it has normal data and control flow, with no complex state.
4. If yes to all, use Direct.

### Direct Method Steps

1. Verify prerequisites.
2. Create test environment data.
3. Create or update the Direct dictionaries:
   - `verification/test-procedures/procedure-data/data_dictionary.yaml`
   - `verification/test-procedures/procedure-data/data_dictionary.csv`
   - `verification/test-procedures/procedure-data/uut_dictionary.yaml`
   - `verification/test-procedures/procedure-data/uut_dictionary.csv`
   - `verification/test-procedures/procedure-data/types_struct.csv` only if needed
4. Check or create the UUT dictionary entries:
   - `uut_dictionary.yaml`
   - `uut_dictionary.csv`
   - `uut_name` must match `FW.SetComponent()`
   - `rate` is the execution rate
   - `init_fcn` is optional
   - `step_fcn` is required
   - `step_fcn_return` is the return type
   - `mock_fcns` lists functions to stub
   - `preconditions` lists default values
   - example shape:
     ```yaml
     - uut_name: my_component
       rate: '0.005'
       init_fcn: my_init
       step_fcn: my_step
       step_fcn_return: void
       mock_fcns: []
       preconditions: []
     ```
   - CSV example shape:
     ```csv
     uut name,rate,initFcn,return,step fcn,return_stepfn,mockFcns,preconditions comma sep
     Knots To Kilometers Per Hour,1.0,,void,UtlSpeedKnotsToKph,UbtKph,,
     ```
5. Check or create the data dictionary entries:
   - `data_dictionary.yaml`
   - `data_dictionary.csv`
   - `req_name` names the requirement-side signal
   - `ver_id` is the verification identifier
   - `uut_name` links to the UUT and argument position
   - `base_data_type_name` and `base_data_type_code` capture the base type
   - example shape:
     ```yaml
     - common:
         argument:
           - req_name: Input Value
             ver_id: input_param
             uut_name: my_component[1]
             base_data_type_name: int
             base_data_type_code: int
     ```
   - CSV example shape:
     ```csv
     RequirementName,VerificationIdentifier,elementType,stubReference,baseDataType,leafDataType
     Knots To Kilometers Per Hour: Speed In Knots,speedKnots,argument,Knots To Kilometers Per Hour[1],UbtKnots,
     Knots To Kilometers Per Hour: Speed In Kilometers Per Hour,,return,,UbtKph,
     ```
6. Generate the requirement RBTCA YAML file.
7. Create the Python test file.
8. Run tests.
9. After tests pass, provide mappings and analysis with proof.

### Direct Dictionary Example

```yaml
- common:
    argument:
      - req_name: Input Value
        ver_id: input_param
        uut_name: Knots To Kilometers Per Hour
        base_data_type_name: int
        base_data_type_code: int
```

```csv
RequirementName,VerificationIdentifier,elementType,stubReference,baseDataType,leafDataType
Knots To Kilometers Per Hour: Speed In Knots,speedKnots,argument,Knots To Kilometers Per Hour[1],UbtKnots,
Knots To Kilometers Per Hour: Speed In Kilometers Per Hour,,return,,UbtKph,
```

### Direct Test Fixture Example

```python
# Item ID: FAF-LLR-1084

import pytest
import pytest_smart as smart


@pytest.fixture(autouse=True)
def setUp(FW: smart.FW):
    FW.Set_Component("Knots To Kilometers Per Hour")  # my_component
    FW.Reset()
```

### Direct Test File Example

```python
# Item ID: FAF-LLR-1084

import pytest
import pytest_smart as smart


@pytest.fixture(autouse=True)
def setUp(FW: smart.FW):
    FW.Set_Component("Knots To Kilometers Per Hour")
    FW.Reset()


# Purpose:
# INPUT : Knots To Kilometers Per Hour: Speed In Knots
# INDEPENDENCE TEST
# DATA RANGE MIN
# BOUNDARY EQUAL TO
def test_TC001(FW: smart.FW):
    FW.Id(1)
    FW.Set("Knots To Kilometers Per Hour: Speed In Knots", 0.0)
    FW.Run()
    FW.Verify("Knots To Kilometers Per Hour: Speed In Kilometers Per Hour", 0.0, tolerance=0.01)

    FW.Id(2)
    FW.Set("Knots To Kilometers Per Hour: Speed In Knots", -9999.0)
    FW.Run()
    FW.Verify("Knots To Kilometers Per Hour: Speed In Kilometers Per Hour", -18518.148, tolerance=0.01)
```

- This same testcase shape is used for Hybrid as well.
- A single Python test function may contain multiple `FW.Id()` blocks when one generated testcase intentionally covers multiple scenarios.

## Hybrid Method Decision Criteria

Use Hybrid when the test needs more than Direct can safely provide:

- Complex data types or structures
- Intricate initialization or setup
- A specific sequence of test steps
- Non-linear control flow in the test
- Multiple setup or teardown phases
- A reusable procedure-definition vector
- Inputs or outputs exposed as `dd_` variables
- Test-local variables for all I/O

### Hybrid Decision Matrix

Use Hybrid if any of these apply:

- Complex data handling is required
- A specific execution sequence is required
- The same procedure must be reused across multiple test cases
- Intricate initialization is needed
- More flexibility than Direct provides is required

Do not use Hybrid if all of these are true:

- The test is simple and straightforward
- Direct satisfies the requirement
- No complex data types or control flow are needed
- No reuse of the same procedure is planned

### Hybrid Method Steps

1. Verify prerequisites.
2. Create test environment data.
3. Create or update the Hybrid dictionaries:
   - `verification/test-procedures/procedure-data/data_dictionary.yaml`
   - `verification/test-procedures/procedure-data/data_dictionary.csv`
   - no `uut_dictionary.yaml`
   - no `uut_dictionary.csv`
   - no `types_struct.csv`
4. Create the `.rvstest` procedure vector.
5. Create the RBTCA YAML file and the Python test file.
6. Run tests.
7. After tests pass, provide full analysis and mappings with proof.

### Hybrid Dictionary Example

```yaml
- common:
    argument:
      - req_name: Course Change Precision: Course In
        ver_id: courseIn
        uut_name: my_component[1]
        base_data_type_name: int
        base_data_type_code: int
```

```csv
RequirementName,VerificationIdentifier,elementType,stubReference,baseDataType,leafDataType
Course Change Precision: Course In,courseIn,argument,Course Change Precision[1],UbtPrecisionRadians,Precision Radians
Course Change Precision: Course Out,courseOut,argument,Course Change Precision[2],UbtPrecisionRadians,Precision Radians
Course Change Precision: Turn Direction,turnDirection,argument,Course Change Precision[3],UbtTurnDirection,Turn Direction
Course Change Precision: Return Value,,return,Course Change Precision,UbtPrecisionRadians,Precision Radians
Course Change At Poles Precision Return,courseChangeAtPolesPrecisionReturn,local,,UbtPrecisionRadians,Precision Radians
```

### Hybrid `.rvstest` Pattern

- Define `dd_` locals such as `dd_courseIn`, `dd_courseOut`, `dd_turnDirection`
- Initialize all locals
- Stub supporting functions first
- Run the UUT after stubs are ready
- Store the return value into a `dd_` local
- Keep the procedure-vector style similar to `Utilities/Base_Utils`

Example intent:

```text
# RVS locals:
dd_courseIn                            UbtPrecisionRadians
dd_courseOut                           UbtPrecisionRadians
dd_turnDirection                       UbtTurnDirection
dd_courseChangePrecisionReturn         UbtPrecisionRadians
dd_courseChangeAtPolesPrecisionReturn  UbtPrecisionRadians

# RVS action order:
Initialize all locals

Stub UtlBrgDistCourseChangeAtPolesPrecision
    return dd_courseChangeAtPolesPrecisionReturn

Run UtlBrgDistCourseChangePrecision
    courseIn      = dd_courseIn
    courseOut     = dd_courseOut
    turnDirection  = dd_turnDirection
    return        = dd_courseChangePrecisionReturn
```

### Hybrid Test Fixture Example

```python
# Item ID: FAF-LLR-1084

import pytest
import pytest_smart as smart


@pytest.fixture(autouse=True)
def setUp(FW: smart.FW):
    FW.Set_Component(
        "Utilities/FMS_Utils/Util_Bearing_Distance/UtlBrgDistParallelCourseIn.rvstest"
    )
    FW.Reset()
```

### Hybrid Test File Example

```python
# Item ID: FAF-LLR-9002

import pytest
import pytest_smart as smart


@pytest.fixture(autouse=True)
def setUp(FW: smart.FW):
    FW.Set_Component("Utilities/Example/ExampleFlow.rvstest")
    FW.Reset()


# Purpose:
# INPUT : Example Flow: Input Value
# BOUNDARY TEST
def test_TC001(FW: smart.FW):
    FW.Id(1)
    FW.Set("Example Flow: Input Value", 10)
    FW.Run()
    FW.Verify("Example Flow: Output Value", 20)

    FW.Id(2)
    FW.Set("Example Flow: Input Value", 0)
    FW.Run()
    FW.Verify("Example Flow: Output Value", 0)
```

### Hybrid Naming Rules

- In the `.rvstest` file, use `dd_` prefixed verification identifiers, such as `dd_donkey`
- In `data_dictionary.yaml` and `data_dictionary.csv`, keep the base name without the `dd_` prefix, such as `donkey`
- Use the `test_[name].py` pattern for Python tests
- Use `[function_name].rvstest` for the procedure vector name

## Blocked Method Decision Criteria

Choose Blocked when:

- the requirement text cannot be located
- the source mapping cannot be proven
- the data mapping cannot be created from evidence
- the expected behavior cannot be determined safely
- no executable verification path exists

## Test Case Formatting

- Put the requirement ID in the item header.
- Add a `Purpose:` comment above each test function.
- Use `FW.Set()`, `FW.Run()`, and `FW.Verify()` in the test body.
- Use `pytest.mark.skip` for coverage-only cases that cannot execute by design.
- Keep one Python test function per RBTCA testcase unless a single function intentionally covers multiple scenarios.
- Direct and Hybrid both use the same Python testcase shape; the difference is the component setup and supporting artifacts, not the test function layout.

## Exact Reporting Expectations

- After tests pass, return the mappings, analysis, and proof.
- Include files created and files updated.
- Include why the method was chosen.
- Include the command run and the result.
- Include the final pass, fail, or blocked status.

## Quick Decision Checklist

| Criteria | Yes/No | Notes |
|---|---|---|
| Single step function? | ☐ | Check function signature |
| `≤1` init function? | ☐ | Usually `void init(void)` |
| Normal data flow? | ☐ | Not a complex state machine |
| Test file named `test_*`? | ☐ | Python test files |
| Component in UUT dictionary? | ☐ | `FW.SetComponent()` match |
| All ✓? | ☐ | Use Direct Method |

## Debug and Validation

- Run the generated test target after writing artifacts.
- If the test fails, inspect the implementation and fix the mapping or expected behavior.
- Keep reruns focused on the failing requirement until the output is stable.
