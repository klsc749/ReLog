#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
DEFAULT_DATASET_DIR = (ROOT_DIR.parent / "datasets").resolve()
DEFAULT_CACHE_DIR = (ROOT_DIR / ".cache" / "cache").resolve()
DEFAULT_OUT_DIR = (ROOT_DIR / ".cache" / "smoke" / "out").resolve()
DEFAULT_METADATA_FILE = Path("direct_debugging.json")
ALLOWED_STATUS = {"success", "compile_failed", "test_timeout", "fatal_error"}


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser()
	parser.add_argument("--image", default=os.environ.get("IMAGE", "localhost/d4j-runner:latest"))
	parser.add_argument("--runtime", default=os.environ.get("CONTAINER_RUNTIME", "podman"))
	parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET_DIR)
	parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
	parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
	parser.add_argument("--network", default=os.environ.get("RUN_NETWORK", ""))
	parser.add_argument(
		"--proxy",
		default=os.environ.get("PROXY") or os.environ.get("http_proxy") or os.environ.get("HTTP_PROXY", ""),
	)
	parser.add_argument(
		"--no-proxy",
		default=os.environ.get("NO_PROXY") or os.environ.get("no_proxy", "localhost,127.0.0.1"),
	)
	return parser.parse_args()


def build_input_payload() -> dict[str, object]:
	return {
		"defects4j_bug_num": 3,
		"defects4j_project": "Cli",
		"buggy_code_with_logging_code": (
			'public static Number createNumber(String str)\n'
			'    {\n'
			'System.out.println("Hello World!!!");       try\n'
			'        {\n'
			'            return org.apache.commons.lang.math.NumberUtils.createNumber(str);\n'
			'        }\n'
			'        catch (NumberFormatException nfe)\n'
			'        {\n'
			'            System.err.println(nfe.getMessage());\n'
			'        }\n'
			'\n'
			'        return null;\n'
			'    }'
		),
	}


def ensure_layout(dataset_dir: Path, cache_dir: Path, out_dir: Path) -> None:
	if not dataset_dir.is_dir():
		raise FileNotFoundError(f"Dataset directory not found: {dataset_dir}")
	if not (dataset_dir / DEFAULT_METADATA_FILE).is_file():
		raise FileNotFoundError(f"Metadata file not found: {dataset_dir / DEFAULT_METADATA_FILE}")
	cache_dir.mkdir(parents=True, exist_ok=True)
	out_dir.mkdir(parents=True, exist_ok=True)


def write_input_file(out_dir: Path) -> Path:
	input_path = out_dir / "input.json"
	input_path.write_text(
		json.dumps(build_input_payload(), indent=2, ensure_ascii=False),
		encoding="utf-8",
	)
	return input_path


def build_run_command(args: argparse.Namespace) -> list[str]:
	cmd = [
		"bash",
		str(ROOT_DIR / "scripts" / "run_job.sh"),
		"--runtime",
		args.runtime,
		"--image",
		args.image,
		"--cache",
		str(args.cache_dir),
		"--dataset",
		str(args.dataset_dir),
		"--out",
		str(args.out_dir),
		"--input",
		str(args.out_dir / "input.json"),
	]
	if args.network:
		cmd += ["--network", args.network]
	if args.proxy:
		cmd += [
			"--proxy",
			args.proxy,
			"--no-proxy",
			args.no_proxy,
		]
	return cmd


def validate_output(out_dir: Path) -> dict[str, object]:
	output_path = out_dir / "output.json"
	if not output_path.is_file():
		raise FileNotFoundError(f"missing {output_path}")
	data = json.loads(output_path.read_text(encoding="utf-8"))
	required = ["buggy_code_runtime_logs", "status", "defects4j_logs", "message"]
	missing = [key for key in required if key not in data]
	if missing:
		raise KeyError(f"output.json missing keys: {missing}")
	status = data.get("status")
	if status not in ALLOWED_STATUS:
		raise ValueError(f"unexpected status: {status}")
	if status == "fatal_error":
		raise RuntimeError(f"fatal_error: {data.get('message', '')}")
	if not (out_dir / "defects4j_stdout.txt").is_file():
		raise FileNotFoundError("missing defects4j_stdout.txt")
	if not (out_dir / "run_meta.json").is_file():
		raise FileNotFoundError("missing run_meta.json")
	return data


def main() -> int:
	args = parse_args()
	args.dataset_dir = args.dataset_dir.resolve()
	args.cache_dir = args.cache_dir.resolve()
	args.out_dir = args.out_dir.resolve()
	try:
		ensure_layout(args.dataset_dir, args.cache_dir, args.out_dir)
		write_input_file(args.out_dir)
		proc = subprocess.run(build_run_command(args), check=False)
		if proc.returncode != 0:
			return proc.returncode
		data = validate_output(args.out_dir)
	except FileNotFoundError as exc:
		print(str(exc), file=sys.stderr)
		return 2
	except Exception as exc:
		print(str(exc), file=sys.stderr)
		return 1
	print("smoke ok")
	print(f"status={data['status']}")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
