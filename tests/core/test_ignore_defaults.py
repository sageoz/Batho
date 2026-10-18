"""Tests for default ignore patterns + ignore_defaults opt-out (T3, graph-accuracy-overhaul)."""

import tempfile
from pathlib import Path

import pytest

from batho.utils.ignore import (
    is_ignored,
    load_ignore_spec,
    load_default_patterns_from_yaml,
)


@pytest.fixture
def tmp_root(tmp_path):
    return tmp_path


class TestDefaultPatternsCoverage:
    """Default patterns must cover lockfiles, generated metadata, and tool outputs."""

    def _spec(self, tmp_path):
        return load_ignore_spec(tmp_path)

    @pytest.mark.parametrize("rel", [
        "pnpm-lock.yaml",
        "package-lock.json",
        "uv.lock",
        "yarn.lock",
        "bun.lockb",
        "bun.lock",
        "deno.lock",
        "flake.lock",
        "poetry.lock",
        "pdm.lock",
        "Cargo.lock",
        "Gemfile.lock",
        "composer.lock",
        "packages.lock.json",
        "Pipfile.lock",
        "conda-lock.yml",
    ])
    def test_lockfiles_ignored(self, tmp_path, rel):
        spec = self._spec(tmp_path)
        assert is_ignored(tmp_path / rel, tmp_path, spec), f"{rel} should be ignored"

    @pytest.mark.parametrize("rel", [
        "tsconfig.tsbuildinfo",
        "tsconfig.node.tsbuildinfo",
        "graphify-out/graph.json",
        "graphify-out/cache/stat-index.json",
        ".graphify/state.bin",
        "app/bundle.js.map",
        "dist/main.min.js",
        "assets/site.min.css",
        ".cursor/settings.json",
        ".claude/commands/review.md",
        ".codeium/state",
        ".specs/graph-accuracy-overhaul/SPEC_INDEX.md",
    ])
    def test_generated_and_tool_outputs_ignored(self, tmp_path, rel):
        spec = self._spec(tmp_path)
        assert is_ignored(tmp_path / rel, tmp_path, spec), f"{rel} should be ignored"

    @pytest.mark.parametrize("rel", [
        "src/main.py",
        "backend/app/routers/graph.py",
        "src/components/Button.tsx",
        "README.md",
        "docs/guide.md",
        "package.json",
        "data.json",
    ])
    def test_source_files_not_ignored(self, tmp_path, rel):
        spec = self._spec(tmp_path)
        assert not is_ignored(tmp_path / rel, tmp_path, spec), f"{rel} should NOT be ignored"


class TestIgnoreDefaultsOptOut:
    def test_use_defaults_false_skips_builtin_patterns(self, tmp_path):
        spec = load_ignore_spec(tmp_path, use_defaults=False)
        # pnpm-lock.yaml is default-only: with defaults off it should NOT be ignored
        assert not is_ignored(tmp_path / "pnpm-lock.yaml", tmp_path, spec)

    def test_use_defaults_false_still_applies_user_patterns(self, tmp_path):
        spec = load_ignore_spec(tmp_path, extra_patterns=["pnpm-lock.yaml"], use_defaults=False)
        assert is_ignored(tmp_path / "pnpm-lock.yaml", tmp_path, spec)
        # but defaults no longer apply
        assert not is_ignored(tmp_path / "node_modules/x/index.js", tmp_path, spec)

    def test_use_defaults_false_still_applies_gitignore(self, tmp_path):
        (tmp_path / ".gitignore").write_text("dist/\n")
        spec = load_ignore_spec(tmp_path, use_defaults=False)
        assert is_ignored(tmp_path / "dist" / "bundle.js", tmp_path, spec)

    def test_defaults_yaml_loads(self):
        patterns = load_default_patterns_from_yaml()
        assert "pnpm-lock.yaml" in patterns
        assert "*.tsbuildinfo" in patterns
        assert "graphify-out/" in patterns
        assert "Pipfile.lock" in patterns
        assert "conda-lock.yml" in patterns
        assert "*.map" in patterns
        assert "*.min.js" in patterns
        assert "*.min.css" in patterns
        assert ".cursor/" in patterns
        assert ".claude/" in patterns
        assert ".codeium/" in patterns

    def test_explicit_user_patterns_win_over_defaults(self, tmp_path):
        """Pattern collision: a repo file named like a lockfile is only ignored
        because of defaults; user patterns remain additive and authoritative."""
        spec = load_ignore_spec(tmp_path, extra_patterns=["!docs/composer.lock"])
        # Explicit negation by the user re-includes a default-ignored lockfile.
        assert is_ignored(tmp_path / "composer.lock", tmp_path, spec)
        assert not is_ignored(tmp_path / "docs" / "composer.lock", tmp_path, spec)


class TestConfigModel:
    def test_indexer_ignore_defaults_field(self):
        from batho.core.config.models import IndexerConfig
        cfg = IndexerConfig()
        assert cfg.ignore_defaults is True
        cfg2 = IndexerConfig(ignore_defaults=False)
        assert cfg2.ignore_defaults is False


class TestPatchDiscoveryHonorsIgnoreSpec:
    """Patch change detection must see the same files the build indexes (P1 fix)."""

    def test_collect_candidates_exclude_defaults(self, tmp_path):
        from batho.modules.graph.incremental import _collect_candidate_files

        (tmp_path / "pnpm-lock.yaml").write_text("lockfile", encoding="utf-8")
        (tmp_path / "main.py").write_text("x = 1", encoding="utf-8")

        spec = load_ignore_spec(tmp_path)
        candidates = {p.name for p in _collect_candidate_files(tmp_path, ignore_spec=spec)}
        assert "main.py" in candidates
        assert "pnpm-lock.yaml" not in candidates

    def test_collect_candidates_include_when_defaults_off(self, tmp_path):
        from batho.modules.graph.incremental import _collect_candidate_files

        (tmp_path / "pnpm-lock.yaml").write_text("lockfile", encoding="utf-8")
        (tmp_path / "main.py").write_text("x = 1", encoding="utf-8")

        spec = load_ignore_spec(tmp_path, use_defaults=False)
        candidates = {p.name for p in _collect_candidate_files(tmp_path, ignore_spec=spec)}
        assert "pnpm-lock.yaml" in candidates
        assert "main.py" in candidates

    def test_collect_candidates_default_spec_still_ignores_defaults(self, tmp_path):
        from batho.modules.graph.incremental import _collect_candidate_files

        (tmp_path / "pnpm-lock.yaml").write_text("lockfile", encoding="utf-8")
        (tmp_path / "main.py").write_text("x = 1", encoding="utf-8")

        candidates = {p.name for p in _collect_candidate_files(tmp_path)}
        assert "pnpm-lock.yaml" not in candidates
        assert "main.py" in candidates

    def test_watcher_spec_honors_ignore_defaults(self, tmp_path):
        from batho.mcp.watcher import _repo_ignore_spec
        from batho.utils.ignore import is_ignored

        (tmp_path / "batho.yaml").write_text(
            "indexer:\n  ignore_defaults: false\n", encoding="utf-8"
        )
        spec = _repo_ignore_spec(tmp_path)
        assert not is_ignored(tmp_path / "pnpm-lock.yaml", tmp_path, spec)

    def test_watcher_spec_defaults_on(self, tmp_path):
        from batho.mcp.watcher import _repo_ignore_spec

        spec = _repo_ignore_spec(tmp_path)
        assert is_ignored(tmp_path / "pnpm-lock.yaml", tmp_path, spec)


class TestSkipBreakdown:
    def test_breakdown_counts_user_skips_when_defaults_off(self, tmp_path, monkeypatch):
        """b629b0fdc4f6: ignore_defaults=false ⇒ skips attributed to
        user/gitignore patterns, not the (disabled) built-in defaults."""
        import copy
        import structlog.testing

        import batho.modules.graph.builder.codegraph as codegraph_mod
        from batho.core.config import get_config_cached
        from batho.modules.graph.builder.codegraph import CodeGraphIndexer

        (tmp_path / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
        (tmp_path / "ignored.txt").write_text("x", encoding="utf-8")
        (tmp_path / "main.py").write_text("x = 1\n", encoding="utf-8")

        cfg = copy.deepcopy(get_config_cached())
        cfg.setdefault("indexer", {})["ignore_defaults"] = False
        monkeypatch.setattr(codegraph_mod, "get_config_cached", lambda: cfg)

        indexer = CodeGraphIndexer(
            cache_path=str(tmp_path / ".cache_test"), root=str(tmp_path)
        )
        try:
            with structlog.testing.capture_logs() as logs:
                indexer.build_graph(
                    root=str(tmp_path),
                    max_workers=1,
                    verbose=False,
                    ast_cache_enabled=False,
                )
        finally:
            indexer.close()

        events = [e for e in logs if e.get("event") == "ignore_skip_breakdown"]
        assert events, "ignore_skip_breakdown log not emitted"
        ev = events[0]
        # ignored.txt matched .gitignore — a user-pattern skip. The buggy code
        # reported skipped_by_user_patterns == 0 here.
        assert ev["skipped_by_user_patterns"] >= 1
        assert ev["skipped_by_user_patterns"] + ev["skipped_by_default_patterns"] == ev["total_skipped"]
