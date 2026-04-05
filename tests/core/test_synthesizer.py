"""Tests for deterministic failure synthesizer and evolution ledger persistence."""

from __future__ import annotations

from pathlib import Path

from batho.synthesizer import (
    load_evolution_ledger,
    record_failure_rule,
    synthesize_failure_rule,
)


class TestSynthesizer:
    def test_record_failure_rule_creates_evolution_ledger(self, tmp_path: Path):
        ctn_dir = tmp_path / ".ctn"
        entry = record_failure_rule(
            ctn_dir=ctn_dir,
            source="cli.patch.snapshot",
            error_message="generated file edit blocked",
            changed_files=["build/generated/api.pb.go"],
            context={"operation_id": "op-1"},
        )

        ledger = load_evolution_ledger(ctn_dir)
        ledger_file = ctn_dir / "evolution_ledger.json"

        assert ledger_file.exists()
        assert entry.get("entry_id")
        assert "generated artifacts" in str(entry.get("dont_rule", "")).lower()
        assert len(ledger.get("entries", [])) == 1

    def test_record_failure_rule_deduplicates_consecutive_entries(self, tmp_path: Path):
        ctn_dir = tmp_path / ".ctn"

        first = record_failure_rule(
            ctn_dir=ctn_dir,
            source="webhook.processor",
            error_message="Base snapshot not found",
            changed_files=["src/main.py"],
        )
        second = record_failure_rule(
            ctn_dir=ctn_dir,
            source="webhook.processor",
            error_message="Base snapshot not found",
            changed_files=["src/main.py"],
        )

        ledger = load_evolution_ledger(ctn_dir)
        assert len(ledger.get("entries", [])) == 1
        assert second.get("entry_id") == first.get("entry_id")

    def test_synthesize_failure_rule_snapshot_missing(self):
        synthesis = synthesize_failure_rule(
            error_message="Base snapshot not found while applying patch",
            changed_files=["src/handler.py"],
        )

        assert synthesis["category"] == "snapshot"
        assert "snapshot" in synthesis["dont_rule"].lower()
