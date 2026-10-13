# Third-party notices

## Defects4J

- Upstream: https://github.com/rjust/defects4j
- Local directory: `executor/defects4j/`
- License: MIT, retained in [executor/defects4j/license.txt](executor/defects4j/license.txt).

The vendored tree preserves the version supplied with the original artifact and its local modifications for container builds, isolated Git workspaces (`git clone --no-hardlinks`), and corrected download arguments. Required repository download scripts, test-runner components, and project libraries are included. Additional tools and project repositories are installed by `init.sh`.

## Benchmark project code

The files in `datasets/` are derived from Defects4J projects and contain method source, test metadata, and runtime records. Project names, commit identifiers, and upstream links provide provenance. Code from these projects remains subject to each project's original license; the top-level MIT license does not relicense third-party code.

Original multilingual test strings in the vendored tree are retained as functional benchmark data.

## Java log capture agent

`executor/agent/SystemOutHookAgent.jar` is the agent supplied with the original artifact for capturing runtime logs. The supplied artifact did not include its source or build instructions.

## Project-owned code

Project-owned code is distributed under [LICENSE](LICENSE), using the MIT License. Academic citation and permission to use code are separate matters.
