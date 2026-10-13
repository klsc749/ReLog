from __future__ import annotations

import ast
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXECUTOR_ROOT = PROJECT_ROOT / "executor"


class ExecutorLayoutTest(unittest.TestCase):
	def test_makefile_exposes_test_targets(self) -> None:
		content = (EXECUTOR_ROOT / "Makefile").read_text(encoding="utf-8")
		self.assertIn("build-host:", content)
		self.assertIn("check-runner-image:", content)
		self.assertIn("smoke:", content)
		self.assertIn("comprehensive:", content)
		self.assertIn("comprehensive-indirect:", content)
		self.assertIn("export-runner:", content)
		self.assertIn("import-runner:", content)

	def test_hidden_cache_directory_is_used(self) -> None:
		makefile = (EXECUTOR_ROOT / "Makefile").read_text(encoding="utf-8")
		run_job = (EXECUTOR_ROOT / "scripts" / "run_job.sh").read_text(encoding="utf-8")
		smoke = (EXECUTOR_ROOT / "scripts" / "smoke_test.py").read_text(encoding="utf-8")
		gitignore = (EXECUTOR_ROOT / ".gitignore").read_text(encoding="utf-8")
		self.assertIn(".cache/export", makefile)
		self.assertIn('.cache', run_job)
		self.assertIn('.cache', smoke)
		self.assertIn(".cache/", gitignore)
		self.assertIn('DEFAULT_METADATA_FILE="direct_debugging.json"', run_job)
		self.assertIn('DEFAULT_METADATA_FILE = Path("direct_debugging.json")', smoke)

	def test_comprehensive_script_exists(self) -> None:
		path = EXECUTOR_ROOT / "scripts" / "comprehensive_test_container.py"
		self.assertTrue(path.exists())
		content = path.read_text(encoding="utf-8")
		self.assertIn('DEFAULT_DIRECT_META_FILE = DEFAULT_DATASET_DIR / "direct_debugging.json"', content)
		self.assertIn('DEFAULT_INDIRECT_META_FILE = DEFAULT_DATASET_DIR / "indirect_debugging.json"', content)

	def test_smoke_script_is_python_entrypoint(self) -> None:
		makefile = (EXECUTOR_ROOT / "Makefile").read_text(encoding="utf-8")
		readme = (EXECUTOR_ROOT / "README.md").read_text(encoding="utf-8")
		root_readme = (EXECUTOR_ROOT.parent / "README.md").read_text(encoding="utf-8")
		smoke = (EXECUTOR_ROOT / "scripts" / "smoke_test.py").read_text(encoding="utf-8")
		self.assertTrue((EXECUTOR_ROOT / "scripts" / "smoke_test.py").exists())
		self.assertFalse((EXECUTOR_ROOT / "scripts" / "smoke_test.sh").exists())
		self.assertIn("python3 ./scripts/smoke_test.py", makefile)
		self.assertNotIn("smoke_test.sh", makefile)
		self.assertIn("def main() -> int:", smoke)
		self.assertIn('str(ROOT_DIR / "scripts" / "run_job.sh")', smoke)
		self.assertIn("scripts/smoke_test.py", readme)
		self.assertNotIn("smoke_test.sh", readme)
		self.assertNotIn("smoke_test.sh", root_readme)
		self.assertIn("/dataset/direct_debugging.json", readme)

	def test_timeout_guard_is_a_top_level_check_in_poll_loop(self) -> None:
		source = (EXECUTOR_ROOT / "d4j_executor" / "run.py").read_text(encoding="utf-8")
		self.assertIn('/dataset/direct_debugging.json', source)
		module = ast.parse(source)
		target = None
		for node in module.body:
			if isinstance(node, ast.FunctionDef) and node.name == "_run_test_and_collect":
				target = node
				break
		self.assertIsNotNone(target)
		while_nodes = [node for node in ast.walk(target) if isinstance(node, ast.While)]
		self.assertTrue(while_nodes)
		top_level_ifs = [stmt for stmt in while_nodes[0].body if isinstance(stmt, ast.If)]
		self.assertGreaterEqual(len(top_level_ifs), 2)
		tests = [ast.get_source_segment(source, stmt.test) or "" for stmt in top_level_ifs]
		self.assertIn("return_code is not None", tests)
		self.assertIn("time.time() - start_time >= config.test_timeout_seconds", tests)

	def test_blind_artifact_files_do_not_reference_old_mirrors(self) -> None:
		targets = [
			EXECUTOR_ROOT / "Makefile",
			EXECUTOR_ROOT / "Dockerfile",
			EXECUTOR_ROOT / "README.md",
			EXECUTOR_ROOT.parent / "README.md",
		]
		banned = ["1ms", "aliyun", "tsinghua", "tuna.tsinghua", "source2", "source3"]
		for path in targets:
			content = path.read_text(encoding="utf-8").lower()
			for token in banned:
				self.assertNotIn(token, content, f"{path} still contains {token!r}")

	def test_project_docs_and_makefile_do_not_reference_cpan_mirror_overrides(self) -> None:
		targets = [
			EXECUTOR_ROOT / "Makefile",
			EXECUTOR_ROOT / "README.md",
			EXECUTOR_ROOT.parent / "README.md",
		]
		banned = ["CPAN_MIRROR", "CPAN mirror", "cpan.metacpan.org"]
		for path in targets:
			content = path.read_text(encoding="utf-8")
			for token in banned:
				self.assertNotIn(token, content, f"{path} still contains {token!r}")

	def test_vendored_defects4j_does_not_ship_repo_metadata_or_unused_helpers(self) -> None:
		defects4j_root = EXECUTOR_ROOT / "defects4j"
		self.assertFalse((defects4j_root / ".git").exists())
		self.assertFalse((defects4j_root / "docker-compose.yml").exists())
		self.assertFalse((defects4j_root / "proxy.sh").exists())
		self.assertFalse((defects4j_root / "developer" / "README_DEVELOPER.md").exists())
		self.assertFalse((EXECUTOR_ROOT / "scripts" / "find_comments.py").exists())
		self.assertFalse((EXECUTOR_ROOT / "tests" / "test_find_comments.py").exists())

	def test_defects4j_base_image_builds_from_local_vendored_tree(self) -> None:
		dockerfile = (EXECUTOR_ROOT / "defects4j" / "Dockerfile").read_text(encoding="utf-8")
		git_pm = (EXECUTOR_ROOT / "defects4j" / "framework" / "core" / "Vcs" / "Git.pm").read_text(encoding="utf-8")
		self.assertIn("ARG BASE_IMAGE=ubuntu:24.04", dockerfile)
		self.assertIn("FROM ${BASE_IMAGE}", dockerfile)
		self.assertIn("COPY defects4j /defects4j", dockerfile)
		self.assertIn("cpanm --from https://cpan.metacpan.org --installdeps .", dockerfile)
		self.assertNotIn("sed -i 's/return \\\"git clone /return \\\"git clone --no-hardlinks /'", dockerfile)
		self.assertIn('return "git clone --no-hardlinks $self->{repo} ${work_dir} 2>&1 && cd $work_dir && git checkout $revision_id 2>&1";', git_pm)
		self.assertNotIn("git clone https://github.com/rjust/defects4j.git", dockerfile)

	def test_defects4j_init_download_url_uses_valid_curl_arguments(self) -> None:
		init_sh = (EXECUTOR_ROOT / "defects4j" / "init.sh").read_text(encoding="utf-8")
		self.assertNotIn('ZBASENAME="-z $BASENAME"', init_sh)
		self.assertNotIn('curl -s -S -R -L -O "$ZBASENAME" "$URL"', init_sh)
		self.assertIn('CURL_ARGS=(-s -S -R -L -O -z "$BASENAME" "$URL")', init_sh)
		self.assertIn('curl "${CURL_ARGS[@]}"', init_sh)
		self.assertIn('curl -s -S -R -L -O "$URL"', init_sh)

	def test_build_targets_disable_implicit_proxy_inheritance(self) -> None:
		makefile = (EXECUTOR_ROOT / "Makefile").read_text(encoding="utf-8")
		self.assertIn("D4J_BASE_IMAGE ?= localhost/d4j-base:latest", makefile)
		self.assertIn("D4J_RUNNER_IMAGE ?= localhost/d4j-runner:latest", makefile)
		self.assertIn("build $(BUILD_COMMON_ARGS) -f defects4j/Dockerfile -t $(D4J_BASE_IMAGE)", makefile)
		self.assertIn("build $(BUILD_COMMON_ARGS) -f Dockerfile -t $(D4J_RUNNER_IMAGE)", makefile)
		self.assertIn("BUILD_COMMON_ARGS := --http-proxy=false", makefile)
		self.assertIn("BUILD_HOST_ARGS := --network=host", makefile)
		self.assertIn("build $(BUILD_HOST_ARGS) -f defects4j/Dockerfile -t $(D4J_BASE_IMAGE)", makefile)
		self.assertIn("build $(BUILD_HOST_ARGS) -f Dockerfile -t $(D4J_RUNNER_IMAGE)", makefile)
		self.assertIn("build-host: build-base-host build-runner-host", makefile)
		self.assertIn("$(CONTAINER_RUNTIME) image exists $(D4J_RUNNER_IMAGE)", makefile)
		self.assertIn("smoke: check-runner-image", makefile)
		self.assertIn("comprehensive: check-runner-image", makefile)
		self.assertIn("comprehensive-indirect: check-runner-image", makefile)

	def test_run_job_never_pulls_remote_images(self) -> None:
		run_job = (EXECUTOR_ROOT / "scripts" / "run_job.sh").read_text(encoding="utf-8")
		self.assertIn('"$RUNTIME" run --pull=never --rm', run_job)

	def test_readme_optional_checks_do_not_reference_internal_comment_scanner(self) -> None:
		readme = (EXECUTOR_ROOT / "README.md").read_text(encoding="utf-8")
		self.assertNotIn("test_find_comments.py", readme)


if __name__ == "__main__":
	unittest.main()
