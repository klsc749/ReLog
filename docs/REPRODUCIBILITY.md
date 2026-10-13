# Reproducibility notes

## Included artifacts

The repository provides the ReLog framework, the direct and indirect benchmark files, a containerized Defects4J backend, and model-assisted debugging evaluators. The benchmark files retain the finalized data used by the original artifact:

| File | Instances | SHA-256 |
| --- | ---: | --- |
| `datasets/direct_debugging.json` | 311 | `792c7a12a87b51fff0b437c1d931a5135b835745c8bf1877b7a98608a5334a38` |
| `datasets/indirect_debugging.json` | 225 | `053c16b98b7413c628de8210bc4558fd3b4a72cf7f6579325f3d3c51a140dca4` |

The vendored Defects4J tree includes the required repository download script, test runner, and project libraries. Its local modifications support container builds, isolated Git workspaces, and corrected download arguments. The dependency lock retains the original resolved Python package versions.

## Changes made for the public release

- Failed triggering tests are extracted by their exact test name. Assertion failures after a target method returns are retained even when the target class is absent from the stack.
- Model/API failures preserve their causes rather than returning old code or being treated as successful generation.
- Logging insertion preserves the original target line and the order of statements inserted before and after it.
- Repetitive log compression retains short runs and trailing repetitions. Long excerpts use nonoverlapping character ranges.
- Temporary DSPy model contexts are restored on normal, nested, and exceptional exits. OpenRouter routing and omitted-temperature settings are passed correctly.
- Checkpoint corruption and write failures raise errors. Direct-pipeline recovery retries failed entries, and final compilation repair records retain the code actually executed.
- Interrupted or abnormally exited test processes are reported as failures. Test process groups are terminated together, and old output artifacts are cleared before each execution.
- Cache waiters can acquire a lock released after failed preparation.
- Evaluation accounting separates generation failures, compilation failures, absent logs, and missing verification results. Errors from completed futures retain their actual cause.
- Module names, dataset paths, and CLI commands use the standalone project layout.

These changes can affect the feedback seen by the models, the number of model calls, regenerated outputs, and automatic statistics. They have not been validated by rerunning the full paper experiments. The paper's final evaluation includes manual verification.

## Validation scope

Validation includes the regression suite, syntax checks, CLI entry points, dependency-lock consistency, and benchmark hashes. Real container runs cover a failing triggering test, a passing fixed method, invalid Java code, runtime log-limit termination, and an indirect invocation with explicit method/test metadata. Output paths containing spaces are also exercised.

Model API error handling is tested through failure injection without calling external providers. Live model credentials and provider availability are not validated by these tests. The execution tests use an existing dependency image with the current execution code rebuilt into it; a clean-machine rebuild of the entire base environment has not been completed.

The indirect pipeline saves only after the batch finishes. The repository does not include the full historical experiment workspace, every baseline implementation, or all original experiment outputs. The Java capture agent is included as the original JAR; its source and build instructions were not present in the supplied artifact.

## Third-party fixtures

Project-owned prose is English. Original multilingual literals in Defects4J encoding tests are preserved as benchmark inputs, since translating them would change the tests or invalidate patches.
