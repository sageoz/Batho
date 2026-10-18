"""Tests for T16 `batho communities label` — deterministic cards, term-check, incremental."""

import os
from pathlib import Path
from unittest.mock import MagicMock

from batho.modules.graph.community_labels import (
    build_community_card,
    card_input_hash,
    label_terms_in_card,
    llm_label_communities,
)


class _E:
    def __init__(self, eid, file, name, metadata=None):
        self.id = eid; self.file = file; self.name = name
        self.type = "FUNCTION"; self.signature = f"def {name}():"
        self.metadata = metadata or {}


class _R:
    def __init__(self, s, t):
        self.source_id = s; self.target_id = t


def _graph():
    g = MagicMock()
    g.entities = {
        f"e{i}": _E(f"e{i}", f"auth/f{i}.py", f"auth_handler_{i}")
        for i in range(5)
    }
    g.entities["e0"].metadata = {"bsg.domain": "auth"}
    g.relationships = [_R("e0", "e1"), _R("e1", "e2"), _R("e2", "x_out")]
    g.degree_by_endpoint = lambda eid: 2 if eid == "e1" else 1
    return g


def _row(**over):
    r = {
        "community_id": 1, "name": "e1", "entity_count": 5, "file_count": 3,
        "top_entities": ["auth_handler_1"], "description": "d",
        "file_paths": ["auth/f0.py", "auth/f1.py", "auth/f2.py"],
        "member_entity_ids": ["e0", "e1", "e2", "e3", "e4"],
        "is_singleton": False, "heuristic_label": "Auth",
        "parent_id": None, "level": 0,
        "llm_label": None, "label_source": None,
        "label_input_hash": None, "label_model": None,
    }
    r.update(over)
    return r


class TestCard:
    def test_card_deterministic(self):
        g = _graph(); row = _row()
        c1 = build_community_card(row, g)
        c2 = build_community_card(row, g)
        assert c1 == c2
        assert card_input_hash(c1) == card_input_hash(c2)

    def test_card_changes_with_membership(self):
        g = _graph()
        c1 = build_community_card(_row(), g)
        c2 = build_community_card(_row(member_entity_ids=["e0", "e1"]), g)
        assert card_input_hash(c1) != card_input_hash(c2)

    def test_parent_label_in_card(self):
        g = _graph()
        card = build_community_card(_row(), g, parent_label="Auth Domain")
        assert card["parent_label"] == "Auth Domain"


class TestTermConstraint:
    def test_grounded_label_passes(self):
        g = _graph(); card = build_community_card(_row(), g)
        assert label_terms_in_card("auth handler", card)
        assert label_terms_in_card("auth domain", card)

    def test_invented_label_rejected(self):
        g = _graph(); card = build_community_card(_row(), g)
        assert not label_terms_in_card("payment processing gateway", card)

    def test_key_terms_grounded(self):
        g = _graph(); card = build_community_card(_row(), g)
        # key_term present in card extends vocabulary
        assert label_terms_in_card("auth handler", card, key_terms=["handler"])
        # key_term NOT in card can't rescue an ungrounded label token
        assert not label_terms_in_card(
            "auth nonexistent", card, key_terms=["nonexistent"]
        )

    def test_empty_label_rejected(self):
        assert not label_terms_in_card("", {"a": 1})


class TestLabeling:
    LLM_CFG = {"enabled": True, "provider": "mock", "model": "m1",
               "max_card_tokens": 200}

    def test_mocked_llm_writes_label(self, monkeypatch):
        monkeypatch.setenv("BATHO_LLM_API_KEY", "k")
        g = _graph()
        row = _row()
        calls = []
        def fake_labeler(card):
            calls.append(card)
            return {"label": "auth handler", "description": "d",
                    "key_terms": ["auth"]}
        stats = llm_label_communities([row], g, self.LLM_CFG, labeler=fake_labeler)
        assert stats["labeled"] == 1
        assert row["llm_label"] == "auth handler"
        assert row["label_source"] == "llm"
        assert row["label_model"] == "mock:m1"
        assert row["label_input_hash"]
        assert len(calls) == 1

    def test_unchanged_hash_skips(self, monkeypatch):
        monkeypatch.setenv("BATHO_LLM_API_KEY", "k")
        g = _graph()
        row = _row()
        def fake_labeler(card):
            return {"label": "auth handler", "description": "d", "key_terms": []}
        llm_label_communities([row], g, self.LLM_CFG, labeler=fake_labeler)
        calls = []
        stats = llm_label_communities(
            [row], g, self.LLM_CFG,
            labeler=lambda c: calls.append(c) or {"label": "x", "description": "", "key_terms": []},
        )
        assert stats["skipped_unchanged"] == 1
        assert not calls  # no labeler call at all

    def test_membership_change_relabels(self, monkeypatch):
        monkeypatch.setenv("BATHO_LLM_API_KEY", "k")
        g = _graph()
        row = _row()
        llm_label_communities(
            [row], g, self.LLM_CFG,
            labeler=lambda c: {"label": "auth handler", "description": "", "key_terms": []},
        )
        row["member_entity_ids"] = ["e0", "e1"]  # membership changed post-patch
        row["entity_count"] = 2
        calls = []
        stats = llm_label_communities(
            [row], g, self.LLM_CFG,
            labeler=lambda c: calls.append(c) or
            {"label": "auth handler", "description": "", "key_terms": []},
        )
        assert stats["labeled"] == 1 and len(calls) == 1

    def test_llm_failure_heuristic_fallback(self, monkeypatch):
        monkeypatch.setenv("BATHO_LLM_API_KEY", "k")
        g = _graph(); row = _row()
        def boom(card):
            raise TimeoutError("model timeout")
        stats = llm_label_communities([row], g, self.LLM_CFG, labeler=boom)
        assert stats["fallback"] == 1
        assert row["label_source"] == "heuristic"
        assert row["llm_label"] is None

    def test_invented_label_falls_back(self, monkeypatch):
        monkeypatch.setenv("BATHO_LLM_API_KEY", "k")
        g = _graph(); row = _row()
        stats = llm_label_communities(
            [row], g, self.LLM_CFG,
            labeler=lambda c: {"label": "zzz hallucinated", "description": "", "key_terms": []},
        )
        assert stats["fallback"] == 1
        assert row["label_source"] == "heuristic"

    def test_disabled_noop(self):
        row = _row()
        stats = llm_label_communities(
            [row], _graph(), {"enabled": False},
        )
        assert stats.get("disabled") is True
        assert row["label_source"] is None

    def test_no_api_key_noop(self, monkeypatch):
        monkeypatch.delenv("BATHO_LLM_API_KEY", raising=False)
        row = _row()
        stats = llm_label_communities([row], _graph(), self.LLM_CFG)
        assert stats.get("disabled") is True
        assert stats.get("reason")


class TestCarryForward:
    def test_label_carried_when_card_unchanged(self):
        """ORC-02: rebuilds serialize fresh Community rows with empty llm_*
        columns; carry_forward re-stamps them keyed on card_input_hash —
        never community_id, which shifts with detection order."""
        from batho.modules.graph.community_labels import carry_forward_labels

        g = _graph()
        prev = _row(
            llm_label="Auth Handlers", label_source="llm", label_model="m1"
        )
        prev["label_input_hash"] = card_input_hash(
            build_community_card(prev, g)
        )
        # same membership/files, DIFFERENT community_id — detection order moved
        rows = [_row(community_id=7)]
        assert carry_forward_labels(rows, [prev], g) == 1
        assert rows[0]["llm_label"] == "Auth Handlers"
        assert rows[0]["label_source"] == "llm"
        assert rows[0]["label_model"] == "m1"
        assert rows[0]["label_input_hash"] == prev["label_input_hash"]

    def test_label_dropped_when_membership_changes(self):
        """Changed membership → different card digest → no carry-forward."""
        from batho.modules.graph.community_labels import carry_forward_labels

        g = _graph()
        prev = _row(llm_label="Auth", label_source="llm", label_model="m")
        prev["label_input_hash"] = card_input_hash(
            build_community_card(prev, g)
        )
        rows = [_row(member_entity_ids=["e0", "e1"], entity_count=2)]
        assert carry_forward_labels(rows, [prev], g) == 0
        assert rows[0]["llm_label"] is None

    def test_no_prev_rows_noop(self):
        from batho.modules.graph.community_labels import carry_forward_labels

        rows = [_row()]
        assert carry_forward_labels(rows, None, _graph()) == 0
        assert carry_forward_labels(rows, [], _graph()) == 0


# ---------------------------------------------------------------------------
# COM-05: CLI-layer coverage — cmd_communities label/list round-trip,
# --dry-run preview, --tree rendering (previously only the label helpers were
# exercised; the IPC write-back and CLI plumbing were untested).
# ---------------------------------------------------------------------------


def _write_communities_ipc(repo_root: Path, rows: list[dict]) -> Path:
    from batho.modules.storage.arrow_bundle.bundle import BathoBundle
    from batho.modules.storage.arrow_bundle.schemas import COMMUNITIES_SCHEMA
    from batho.modules.storage.arrow_bundle.writer import write_simple_ipc

    db = BathoBundle(repo_root)
    write_simple_ipc(rows, COMMUNITIES_SCHEMA, db.artifact_dir / "communities.ipc")
    return db.artifact_dir


def _ns(**kw):
    import argparse

    base = dict(
        root=None, communities_command=None, dry_run=False, json_output=False,
        tree=False, top=20,
    )
    base.update(kw)
    return argparse.Namespace(**base)


class _FakeHttpResp:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        import json as _json

        return _json.dumps(
            {
                "content": [
                    {
                        "text": _json.dumps(
                            {
                                # grounded in the card: "auth" comes from
                                # dominant_dirs + heuristic_label of _row()
                                "label": "Auth",
                                "description": "auth handlers",
                                "key_terms": ["auth"],
                            }
                        )
                    }
                ]
            }
        ).encode()


class TestCommunitiesCli:
    def test_label_persists_and_lists(
        self, tmp_path, monkeypatch, capsys
    ):
        """cmd_communities label → communities.ipc gains llm_label rows;
        `list` then renders the persisted label — full IPC round-trip."""
        import urllib.request

        from batho.cli.communities import cmd_communities
        from batho.mcp.community_summaries import load_communities

        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "batho.yaml").write_text(
            "community_detection:\n  llm:\n    enabled: true\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("BATHO_LLM_API_KEY", "test-key")
        monkeypatch.setattr(
            urllib.request, "urlopen", lambda *a, **k: _FakeHttpResp()
        )
        artifact_dir = _write_communities_ipc(repo, [_row()])

        code = cmd_communities(_ns(root=str(repo), communities_command="label"))
        assert code == 0

        rows = load_communities(artifact_dir)
        assert rows[0]["llm_label"] == "Auth"
        assert rows[0]["label_source"] == "llm"
        assert rows[0]["label_input_hash"]

        capsys.readouterr()
        code = cmd_communities(_ns(root=str(repo), communities_command="list"))
        assert code == 0
        assert "Auth" in capsys.readouterr().out

    def test_label_disabled_no_graph_load(self, tmp_path, capsys):
        """COM-03 regression: llm disabled → early return before any graph
        load (the old path loaded the full artifact incl. storage blobs)."""
        from batho.cli.communities import cmd_communities

        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "batho.yaml").write_text("", encoding="utf-8")
        artifact_dir = _write_communities_ipc(repo, [_row()])

        code = cmd_communities(
            _ns(root=str(repo), communities_command="label", json_output=True)
        )
        assert code == 0
        out = capsys.readouterr().out
        assert '"disabled": true' in out
        # nothing written back — the row is untouched
        from batho.mcp.community_summaries import load_communities

        rows = load_communities(artifact_dir)
        assert rows[0]["llm_label"] is None

    def test_dry_run_previews_without_writes(
        self, tmp_path, monkeypatch, capsys
    ):
        """--dry-run prints card previews and never touches communities.ipc
        even when llm is enabled."""
        from batho.cli.communities import cmd_communities
        from batho.mcp.community_summaries import load_communities

        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "batho.yaml").write_text(
            "community_detection:\n  llm:\n    enabled: true\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("BATHO_LLM_API_KEY", "test-key")
        artifact_dir = _write_communities_ipc(repo, [_row()])

        code = cmd_communities(
            _ns(
                root=str(repo), communities_command="label",
                dry_run=True, json_output=True,
            )
        )
        assert code == 0
        out = capsys.readouterr().out
        assert '"dry_run": true' in out
        assert '"would_relabel": 1' in out
        rows = load_communities(artifact_dir)
        assert rows[0]["llm_label"] is None

    def test_list_tree_renders_hierarchy(self, tmp_path, capsys):
        """--tree renders parent/child indentation via parent_id links."""
        from batho.cli.communities import cmd_communities

        repo = tmp_path / "repo"
        repo.mkdir()
        rows = [
            _row(community_id=1, heuristic_label="Parent"),
            _row(
                community_id=2, heuristic_label="ChildA", parent_id=1,
                level=1, entity_count=3, member_entity_ids=["e0", "e1", "e2"],
            ),
            _row(
                community_id=3, heuristic_label="ChildB", parent_id=1,
                level=1, entity_count=2, member_entity_ids=["e3", "e4"],
            ),
        ]
        _write_communities_ipc(repo, rows)
        capsys.readouterr()
        code = cmd_communities(
            _ns(root=str(repo), communities_command="list", tree=True)
        )
        assert code == 0
        out = capsys.readouterr().out.splitlines()
        assert out[0].startswith("#1")
        # children render indented under the parent
        assert any(line.startswith("  #2") for line in out)
        assert any(line.startswith("  #3") for line in out)


class TestOverviewLeafPartition:
    """COM-12: format_communities_for_overview must not double-count parent +
    child rows — leaf rows form the partition."""

    def test_interior_rows_excluded_from_overview(self):
        from batho.mcp.community_summaries import format_communities_for_overview

        rows = [
            _row(community_id=1, entity_count=5),  # parent of 2+3
            _row(community_id=2, entity_count=3, parent_id=1, level=1),
            _row(community_id=3, entity_count=2, parent_id=1, level=1),
            _row(community_id=4, entity_count=4),  # independent leaf
        ]
        out = format_communities_for_overview(rows)
        ids = {c["id"] for c in out}
        assert 1 not in ids  # interior row hidden
        assert ids == {2, 3, 4}
        # partition: counts sum to covered entities, not parent+children
        assert sum(c["entity_count"] for c in out) == 9

    def test_aggregate_sums_leaf_counts_only(self):
        from batho.mcp.community_summaries import format_communities_for_overview

        # 15 leaf rows under one interior parent → top_n=2 shows 2 leaves,
        # aggregate tail sums only remaining leaves (not the parent again).
        rows = [_row(community_id=99, entity_count=45)]
        rows += [
            _row(community_id=i, entity_count=3, parent_id=99, level=1)
            for i in range(1, 16)
        ]
        out = format_communities_for_overview(rows, top_n=2)
        aggregate = [c for c in out if c.get("is_aggregate")]
        assert len(aggregate) == 1
        assert aggregate[0]["entity_count"] == 13 * 3
