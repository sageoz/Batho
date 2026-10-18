"""T4: deterministic community labeling — 5-tier fallback chain + dedup."""

from __future__ import annotations

from batho.modules.graph.community import Community
from batho.modules.graph.community_labels import _clean_name, label_communities


class _Ent:
    def __init__(self, eid: str, name: str, file: str = ""):
        self.id = eid
        self.name = name
        self.file = file


def _comm(cid: int, eids: list[str], files: list[str]) -> Community:
    return Community(
        id=cid,
        name="",
        entity_count=len(eids),
        file_count=len(files),
        file_paths=files,
        member_entity_ids=eids,
    )


def _label(comms, entities, degrees=None, blocklist=None):
    label_communities(
        comms,
        entities,
        degrees or (lambda eid: 0),
        blocklist if blocklist is not None else {"src", "lib", "app", "core", "utils", "common", "shared", "helpers", "test", "tests"},
    )
    return [c.heuristic_label for c in comms]


def test_tier1_dominant_directory_skips_generic_segments():
    entities = {e: _Ent(e, e) for e in ["a", "b", "c"]}
    comms = [
        _comm(
            0,
            ["a", "b", "c"],
            [
                "backend/app/services/auth.py",
                "backend/app/services/graph.py",
                "backend/app/services/api.py",
            ],
        )
    ]
    labels = _label(comms, entities)
    # `app` is blocklisted; backend + services survive → "Backend Services"
    assert labels == ["Backend Services"]


def test_tier1_all_generic_dirs_falls_through():
    entities = {
        "a": _Ent("a", "graph_service"),
        "b": _Ent("b", "graph_client"),
        "c": _Ent("c", "graph_store"),
    }
    comms = [_comm(0, ["a", "b", "c"], ["src/x.py", "src/y.py", "src/z.py"])]
    labels = _label(comms, entities)
    # `src` blocklisted → tier 2 c-TF-IDF picks the dominant token `graph`
    assert "Graph" in labels[0]


def test_tier2_ctfidf_prefers_cluster_specific_tokens():
    entities = {}
    comms = []
    # Cluster 0: all names carry `auth`; cluster 1: all carry `billing`.
    for i, (tag, names) in enumerate(
        [("auth", ["auth_login", "auth_logout", "auth_refresh"]),
         ("billing", ["billing_charge", "billing_refund", "billing_plan"])]
    ):
        eids = [f"{tag}{j}" for j in range(len(names))]
        for eid, name in zip(eids, names):
            entities[eid] = _Ent(eid, name)
        comms.append(_comm(i, eids, [f"{tag}/m.py"]))
    labels = _label(comms, entities)
    assert labels[0] != labels[1]
    assert "Auth" in labels[0] and "Billing" in labels[1]


def test_tier3_longest_common_prefix():
    entities = {
        "a": _Ent("a", "storefront_get"),
        "b": _Ent("b", "storefront_set"),
        "c": _Ent("c", "storefront_del"),
    }
    comms = [_comm(0, ["a", "b", "c"], [])]
    # no files → tier1 None; single cluster → c-TF-IDF df=1 idf=0... falls to
    # tier3 common prefix `storefront` (>=4 chars)
    labels = _label(comms, entities)
    assert "Storefront" in labels[0]


def test_tier4_hub_name_when_no_structure():
    entities = {
        "a": _Ent("a", "x"),
        "b": _Ent("b", "y"),
    }
    comms = [_comm(0, ["a", "b"], [])]
    # single-char names yield no >=4 affix and weak c-TF-IDF; hub naming wins.
    labels = _label(comms, entities, degrees=lambda eid: {"a": 5, "b": 1}[eid])
    assert labels[0] == "x"


def test_tier5_fallback_for_empty_community():
    comms = [_comm(0, [], [])]
    labels = _label(comms, {})
    assert labels[0] == "Community_0"


def test_label_dedup_suffix():
    entities = {
        "a": _Ent("a", "worker_a"),
        "b": _Ent("b", "worker_b"),
    }
    comms = [
        _comm(0, ["a"], ["root/jobs/a.py"]),
        _comm(1, ["b"], ["root/jobs/b.py"]),
    ]
    labels = _label(comms, entities)
    assert labels[0] != labels[1]
    assert labels[1].endswith("(2)")


def test_hash_suffix_stripped_from_labels():
    entities = {
        "a": _Ent("a", "get_entity_[800748]"),
        "b": _Ent("b", "set_entity_[ab12cd]"),
    }
    comms = [_comm(0, ["a", "b"], [])]
    labels = _label(comms, entities)
    assert "[" not in labels[0] and "]" not in labels[0]


def test_clean_name_matches_emitter_hash_pattern():
    """d7eeb16f561c: the suffix regex must match the emitter's
    `_[a-fA-F0-9]+` (scope_manager._PARAM_HASH_PATTERN) — any length,
    mixed case — not just >=4 lowercase hex."""
    assert _clean_name("get_entity_[80AB]") == "get_entity"
    assert _clean_name("get_entity_[12345]") == "get_entity"
    assert _clean_name("get_entity_[800748]") == "get_entity"
    assert _clean_name("fn_[a]") == "fn"
    assert _clean_name("fn_<Ab12Cd>") == "fn"
    # Non-hex bracket suffixes are not param hashes and must survive.
    assert _clean_name("name_[xyz]") == "name_[xyz]"
    assert _clean_name("plain_name") == "plain_name"


def test_hash_suffix_stripped_short_and_mixed_case_labels():
    """Short/uppercase suffixes (`_[80AB]`, `_[12345]`) must not leak into
    labels — they previously survived the >=4-lowercase-only pattern."""
    entities = {
        "a": _Ent("a", "get_entity_[80AB]"),
        "b": _Ent("b", "set_entity_[12345]"),
    }
    comms = [_comm(0, ["a", "b"], [])]
    labels = _label(comms, entities)
    assert "[" not in labels[0] and "]" not in labels[0]
    assert "80AB" not in labels[0] and "12345" not in labels[0]


def test_labels_deterministic_snapshot():
    entities = {e: _Ent(e, f"svc_{e}") for e in ["a", "b", "c", "d"]}
    files = ["root/services/a.py", "root/services/b.py"]
    c1 = [_comm(0, ["a", "b"], files), _comm(1, ["c", "d"], files)]
    c2 = [_comm(0, ["a", "b"], files), _comm(1, ["c", "d"], files)]
    assert _label(c1, entities) == _label(c2, entities)


def test_degenerate_separator_affix_falls_through():
    """COM-06: a common affix made entirely of separators (e.g. '____')
    strips to '' — must fall through to the next tier rather than return
    an empty label that short-circuits the fallback chain."""
    from batho.modules.graph.community_labels import _common_affix

    # common prefix '____' (4 separators) — strips to "" → must not return ""
    assert _common_affix(["____x", "____y"]) != ""
    # …and a real common affix still labels
    assert _common_affix(["storefront_get", "storefront_set"]) == "Storefront"


def test_degenerate_separator_affix_labels_via_fallback():
    """End-to-end through label_communities: all-separator affix must not
    produce an empty heuristic_label (hub naming tier picks up)."""
    entities = {
        "a": _Ent("a", "____first"),
        "b": _Ent("b", "____second"),
    }
    comms = [_comm(0, ["a", "b"], [])]
    labels = _label(comms, entities, degrees=lambda eid: {"a": 9, "b": 1}[eid])
    assert labels[0] != ""
    # 'first'/'second' share no c-TF-IDF term → hub-name fallback names
    # the community after the highest-degree member.
    assert "first" in labels[0].lower() or labels[0].startswith("Community")
