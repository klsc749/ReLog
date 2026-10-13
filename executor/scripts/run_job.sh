#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  ./scripts/run_job.sh --out <dir> --input <file> [options]

Required:
  --out <dir>
  --input <file>

Options:
  --cache <dir>
  --dataset <dir>
  --no-dataset
  --image <name>
  --runtime <bin>
  --network <mode>
  --proxy <url>
  --no-proxy <value>
EOF
}

abs_path() {
  python3 - <<'PY' "$1"
import os
import sys
print(os.path.realpath(sys.argv[1]))
PY
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

DEFAULT_CACHE_DIR="$(abs_path "$ROOT_DIR/.cache/cache")"
DEFAULT_DATASET_DIR="$(abs_path "$ROOT_DIR/../datasets")"
DEFAULT_METADATA_FILE="direct_debugging.json"

IMAGE="${IMAGE:-localhost/d4j-runner:latest}"
RUNTIME="${CONTAINER_RUNTIME:-podman}"
NETWORK="${RUN_NETWORK:-}"
PROXY="${PROXY:-}"
NO_PROXY_VAL="${NO_PROXY:-localhost,127.0.0.1}"

CACHE_DIR="$DEFAULT_CACHE_DIR"
DATASET_DIR="$DEFAULT_DATASET_DIR"
USE_DATASET=1
OUT_DIR=""
INPUT_JSON=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --image) IMAGE="$2"; shift 2 ;;
    --runtime) RUNTIME="$2"; shift 2 ;;
    --network) NETWORK="$2"; shift 2 ;;
    --proxy) PROXY="$2"; shift 2 ;;
    --no-proxy) NO_PROXY_VAL="$2"; shift 2 ;;
    --cache) CACHE_DIR="$2"; shift 2 ;;
    --dataset) DATASET_DIR="$2"; shift 2 ;;
    --no-dataset) USE_DATASET=0; DATASET_DIR=""; shift 1 ;;
    --out) OUT_DIR="$2"; shift 2 ;;
    --input) INPUT_JSON="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage; exit 2 ;;
  esac
done

if [[ -z "$OUT_DIR" || -z "$INPUT_JSON" ]]; then
  echo "Missing required arguments." >&2
  usage
  exit 2
fi

CACHE_DIR="$(abs_path "$CACHE_DIR")"
if [[ "$USE_DATASET" -eq 1 ]]; then
  DATASET_DIR="$(abs_path "$DATASET_DIR")"
fi
OUT_DIR="$(abs_path "$OUT_DIR")"
INPUT_JSON="$(abs_path "$INPUT_JSON")"

if [[ "$USE_DATASET" -eq 1 ]]; then
  if [[ ! -d "$DATASET_DIR" ]]; then
    echo "Dataset directory not found: $DATASET_DIR" >&2
    exit 2
  fi
  if [[ ! -f "$DATASET_DIR/$DEFAULT_METADATA_FILE" ]]; then
    echo "Metadata file not found: $DATASET_DIR/$DEFAULT_METADATA_FILE" >&2
    exit 2
  fi
fi

if [[ ! -f "$INPUT_JSON" ]]; then
  echo "Input file not found: $INPUT_JSON" >&2
  exit 2
fi

mkdir -p "$CACHE_DIR" "$OUT_DIR"
DEST_INPUT="$OUT_DIR/input.json"
if [[ "$INPUT_JSON" != "$DEST_INPUT" ]]; then
  cp -f "$INPUT_JSON" "$DEST_INPUT"
fi

# Each run must produce fresh artifacts when reusing an output directory.
rm -f "$OUT_DIR/output.json" "$OUT_DIR/run_meta.json" "$OUT_DIR/failing_tests"   "$OUT_DIR/auto_capture.log" "$OUT_DIR/defects4j_stdout.txt"

RUN_ENVS=()
if [[ -n "$PROXY" ]]; then
  RUN_ENVS+=(-e "http_proxy=$PROXY" -e "https_proxy=$PROXY" -e "HTTP_PROXY=$PROXY" -e "HTTPS_PROXY=$PROXY")
  RUN_ENVS+=(-e "no_proxy=$NO_PROXY_VAL" -e "NO_PROXY=$NO_PROXY_VAL")
fi

RUN_NET=()
if [[ -n "$NETWORK" ]]; then
  RUN_NET+=(--network="$NETWORK")
fi

DATASET_MOUNT=()
if [[ "$USE_DATASET" -eq 1 ]]; then
  DATASET_MOUNT=(-v "$DATASET_DIR:/dataset:ro")
fi

"$RUNTIME" run --pull=never --rm \
  -v "$CACHE_DIR:/cache" \
  "${DATASET_MOUNT[@]}" \
  -v "$OUT_DIR:/out" \
  "${RUN_NET[@]}" \
  "${RUN_ENVS[@]}" \
  "$IMAGE"

if [[ ! -f "$OUT_DIR/output.json" ]]; then
  echo "Missing output.json: $OUT_DIR/output.json" >&2
  exit 1
fi
