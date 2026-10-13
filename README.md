# ReLog

**Execution-aware logging with runtime feedback for LLM-oriented debugging.**

ReLog generates logging statements, executes the instrumented code, and iteratively refines the logs using runtime feedback. The project evaluates the resulting logs through downstream defect localization and repair tasks.

[Paper](https://arxiv.org/abs/2603.29122) · [Published paper DOI](https://doi.org/10.1145/3832783.3837463) · [Usage](docs/USAGE.md) · [Datasets](datasets/README.md) · [Execution backend](executor/README.md)

## Project layout

```text
relog/              Logging generation, refinement, and evaluation
  config/           Model configuration template
  roles/            LLM roles used by the framework
  evaluator/        Direct and indirect debugging evaluators
datasets/           Finalized Defects4J-based benchmark files
executor/           Containerized Defects4J execution backend
tests/              Unit and regression tests
docs/               Usage and reproducibility notes
pyproject.toml      Python project configuration
uv.lock             Dependency snapshot
```

Run Python commands from the project root.

## Requirements

- Python 3.12+ and [uv](https://docs.astral.sh/uv/).
- Linux x86_64, Podman, and GNU Make for the execution backend. The base image installs Java 11.
- Model credentials for the providers selected in your configuration.
- At least 300 GB of available disk space is recommended for the full experiments, including container images and cached Defects4J checkouts.

## Quick start

```bash
git clone https://github.com/klsc749/ReLog.git
cd ReLog
uv sync --locked
make -C executor build
make -C executor smoke
```

Create a local model configuration and fill in your credentials:

```bash
cp relog/config/llm_config.json relog/config/llm_config.local.json
export RELOG_LLM_CONFIG_PATH="$PWD/relog/config/llm_config.local.json"
```

The local configuration is ignored by Git. Model names in CLI arguments are aliases defined in this file. The default generation model is `gpt-5-mini`, served through OpenRouter; the default compilation repair model is `deepseek-v3`.

Run either debugging setting:

```bash
uv run --locked python -m relog.direct
uv run --locked python -m relog.indirect
```

These commands process the full dataset and make model API calls. Results are written to `results/`; execution artifacts are kept under `.cache/`. See [Usage](docs/USAGE.md) for evaluation commands and configuration options.

## Tests

```bash
uv run --locked python -m unittest discover -s tests -v
```

The unit tests include failure injection for model API errors and real subprocess checks. They do not call external model services. The separate container smoke test exercises Defects4J execution and log collection.

## Reproducibility

This repository contains the ReLog implementation, two finalized datasets, the execution backend, and automatic evaluators. It does not include the complete historical experiment workspace, all baseline implementations, or the original outputs behind every paper table.

The public version includes fixes to execution feedback, logging insertion, model configuration, checkpoint handling, and evaluation accounting. These fixes can affect subsequent model outputs or statistics. The paper's final evaluation includes manual verification; automatic evaluator outputs alone do not reproduce its final tables. See [Reproducibility notes](docs/REPRODUCIBILITY.md).

## Citation

If you use the code or datasets, please cite:

```bibtex
@article{wang2026relog,
  title={ReLog: Execution-Aware Logging with Runtime Feedback for LLM-Oriented Debugging},
  author={Wang, Xin and Feng, Yang and Jiao, Xiaoqian and Zhang, Yang and Li, Zhenhao and Ding, Zishuo},
  journal={arXiv preprint arXiv:2603.29122},
  year={2026},
  doi={10.48550/arXiv.2603.29122},
  url={https://arxiv.org/abs/2603.29122}
}
```

Machine-readable citation metadata is available in [CITATION.cff](CITATION.cff).

## License

Project-owned code is released under the [MIT License](LICENSE). Defects4J and the benchmark projects retain their original licenses. See [Third-party notices](THIRD_PARTY_NOTICES.md).
