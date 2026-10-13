# Datasets

This directory contains the finalized benchmark files consumed by ReLog and its execution backend.

| Dataset | Instances | Defects4J projects | Setting |
| --- | ---: | ---: | --- |
| `direct_debugging.json` | 311 | 16 | Target-method source is available |
| `indirect_debugging.json` | 225 | 15 | Debugging relies on caller code and runtime logs |

## Direct debugging

Each sample identifies a faulty method and its triggering tests in a Defects4J bug. The data includes the buggy and fixed method bodies, method location and signature, bug description, project/bug identifiers, and links to the corresponding commit or issue.

Important fields include `jira_id`, `commit_hash`, `defects4j_project`, `defects4j_bug_num`, `main_method_path`, `main_method_signature`, `test_methods`, `buggy_code`, `fixed_code`, and `bug_description`.

When an execution job omits explicit method or test metadata, the backend resolves it from the direct-debugging dataset. It uses the first entry in `test_methods` as the triggering test.

## Indirect debugging

Each retained sample has at least one caller method resolved from the runtime invocation path leading to a Defects4J failure. The debugging agent receives the caller context rather than the implementation of the faulty method.

Entries include `buggy_method`, `caller_methods`, and `trigger_test_methods`. Caller records provide `signature`, `class_name`, `file_path`, `code`, `code_with_logging`, and `runtime_logs`. The generation pipeline uses the caller's method metadata and the first triggering test for execution.

## Provenance and release scope

The datasets were constructed from buggy and fixed Defects4J checkouts. The direct dataset extracts faulty-method source and tests; the indirect dataset additionally records the executed calling context and retains samples with resolved project-source callers.

Rebuilding the historical dataset construction workspace is not required to run the released experiments. These files preserve the finalized benchmark contents; checksums are recorded in [Reproducibility notes](../docs/REPRODUCIBILITY.md).

Third-party code retains the original projects' licenses. See [Third-party notices](../THIRD_PARTY_NOTICES.md).
