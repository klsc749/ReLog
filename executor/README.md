# Execution backend

This directory runs instrumented Java methods in isolated Defects4J containers, executes a triggering test, and captures runtime logs.

## Contents

- `d4j_executor/`: Python runner, method patching, and metadata resolution.
- `scripts/run_job.sh`: Public entry point for a single execution job.
- `scripts/smoke_test.py`: Minimal container smoke test.
- `scripts/comprehensive_test_container.py`: Direct and indirect execution checks.
- `agent/SystemOutHookAgent.jar`: Runtime log capture agent.
- `defects4j/`: Vendored Defects4J tree and base-image build configuration.

## Build and validate

From the project root:

```bash
make -C executor build
make -C executor smoke
```

The build creates `localhost/d4j-base:latest` and `localhost/d4j-runner:latest`. The default build uses an isolated network configuration and disables implicit proxy inheritance. To use the host network environment:

```bash
make -C executor build-host
```

The Makefile supports an explicit `PROXY` and `BUILD_NETWORK` for the isolated build. Configure these for your environment when necessary.

Run the full execution checks after the smoke test:

```bash
make -C executor comprehensive
make -C executor comprehensive-indirect
```

These checks launch parallel jobs. Full experiments require substantial storage for images, cached workspaces, and outputs; the project recommends at least 300 GB of free space.

Unit and regression tests are located at the project root:

```bash
uv run --locked python -m unittest discover -s tests -v
```

## Run a direct-debugging job

Prepare a JSON input, then run:

```bash
bash executor/scripts/run_job.sh \
  --dataset datasets \
  --out .cache/jobs/example \
  --input .cache/tmp/input.json
```

Required fields:

- `defects4j_project`
- `defects4j_bug_num`
- `buggy_code_with_logging_code`

Optional metadata fields:

- `method_path`
- `method_signature`
- `test_method`

The runner also accepts `main_method_path` and `main_method_signature` as aliases. Missing metadata is resolved from `/dataset/direct_debugging.json`, mounted from the host's `datasets/` directory. The first triggering test in the dataset is used.

## Run a self-contained job

```bash
bash executor/scripts/run_job.sh \
  --no-dataset \
  --out .cache/jobs/example \
  --input .cache/tmp/input.json
```

A self-contained job must explicitly provide `method_path`, `method_signature`, and `test_method`. The backend does not read the indirect-debugging dataset; the indirect pipeline passes the caller method and test metadata in each job input.

## Artifacts and execution status

The output directory contains `input.json`, `output.json`, `run_meta.json`, and `defects4j_stdout.txt`. It may also contain `auto_capture.log` and `failing_tests`. Old output artifacts are cleared before a new job starts.

`output.json` contains `buggy_code_runtime_logs`, `status`, `defects4j_logs`, `message`, `compilation_err_info`, and `exception_stack_trace`.

| Status | Meaning |
| --- | --- |
| `success` | Execution completed and logs were collected; the triggering test may still have failed |
| `compile_failed` | Java compilation failed |
| `test_timeout` | The configured test execution timeout was reached |
| `fatal_error` | Infrastructure failure, abnormal process exit, or termination after the runtime log limit |

Triggering-test failures are returned in `exception_stack_trace`. A failed assertion after the target method returns remains relevant even if the target class is absent from the stack. The ReLog consumer interprets a nonempty failure trace as `runtime_error`.

The runner retains the original configurable limits: `D4J_MAX_LOG_LINES` defaults to 100 and `D4J_TEST_TIMEOUT_SECONDS` defaults to 300. These variables configure the runner container. Interrupted tests terminate the entire test process group. The host wrapper has no separate timeout covering checkout and container preparation.

## Export and import an image

```bash
make -C executor export-runner
make -C executor import-runner
```

The default archive is `executor/.cache/export/d4j-runner_latest.tar`. Cached checkouts and backend-generated artifacts are stored under `executor/.cache/` and excluded from Git.
