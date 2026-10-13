# Usage

Run the commands below from the project root after `uv sync --locked`. Configure the execution backend using [executor/README.md](../executor/README.md), then set `RELOG_LLM_CONFIG_PATH` to your local model configuration.

## Direct debugging

```bash
uv run --locked python -m relog.direct \
  --data-path datasets/direct_debugging.json \
  --output-path results/direct_debugging_results.json \
  --model-name gpt-5-mini \
  --compilation-fix-model-name deepseek-v3
```

The direct pipeline keeps checkpoints. On a subsequent invocation with the same output path, completed entries are retained and failed entries are retried. A malformed checkpoint raises an error rather than restarting or overwriting the file.

## Indirect debugging

```bash
uv run --locked python -m relog.indirect \
  --data-path datasets/indirect_debugging.json \
  --output-path results/indirect_debugging_results.json \
  --model-name gpt-5-mini \
  --compilation-fix-model-name deepseek-v3
```

Each caller method is instrumented and executed using its explicit method location, signature, and triggering test. This pipeline saves at the end of the batch and does not provide intermediate checkpoint recovery.

## Direct evaluation

```bash
uv run --locked python -m relog.evaluator.direct \
  --input-path results/direct_debugging_results.json \
  --ground-truth-path datasets/direct_debugging.json \
  --result-path results/direct_debugging_evaluation.json \
  --statistics-path results/direct_debugging_statistics.json \
  --model-name deepseek-v3 \
  --verifier-model-name deepseek-v3 \
  --max-workers 32
```

## Indirect evaluation

```bash
uv run --locked python -m relog.evaluator.indirect \
  --input-path results/indirect_debugging_results.json \
  --ground-truth-path datasets/indirect_debugging.json \
  --result-path results/indirect_debugging_evaluation.json \
  --statistics-path results/indirect_debugging_statistics.json \
  --detect-model-name deepseek-v3 \
  --verify-model-name deepseek-v3 \
  --max-workers 32
```

The evaluators use model-assisted judgments. Generation failures and compilation failures are counted separately. A lack of runtime logs does not, by itself, indicate compilation failure. Missing verification results are tracked separately from incorrect detections.

## Configuration and CLI help

Model aliases must match entries in the configuration file. The distributed `relog/config/llm_config.json` contains placeholder credentials; use an ignored local copy for real credentials. The OpenRouter alias uses the routing name `openrouter/openai/gpt-5-mini`.

```bash
uv run --locked python -m relog.direct --help
uv run --locked python -m relog.indirect --help
uv run --locked python -m relog.evaluator.direct --help
uv run --locked python -m relog.evaluator.indirect --help
```

The generation pipelines expose worker counts, temperature, caching, iteration counts, compilation repair attempts, and execution path overrides. The default model/provider-specific settings are implemented in `relog/base_dspy.py`.

Generated results and execution artifacts are excluded from Git. Errors are recorded with their causes instead of substituting successful results or silently continuing with old code.
