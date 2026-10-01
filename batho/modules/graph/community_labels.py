"""Deterministic community labeling (T4).

Assigns each Community a `heuristic_label` via an ordered fallback chain —
first hit wins:

1. Dominant parent directory of member files, skipping generic names
   (`community.generic_dir_blocklist`) → title-cased.
2. c-TF-IDF over identifier tokens (snake_case/camelCase/PascalCase/kebab-case
   → token multiset); tokens frequent in-cluster but rare across other
   communities win; label = top 2–3 terms.
3. Longest common identifier prefix or suffix (>=4 chars) across member names.
4. Highest-degree member name (hub naming).
5. `Community_<id>`.

Deterministic rules only — no LLM. Classless languages (go, c, lua) rely on
tiers 1/2/4 rather than class names.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from batho.core.schemas import Entity
    from batho.modules.graph.community import Community

# Name hash suffixes like `get_entity_[800748]` / `foo_<ab12cd>` must not leak
# into labels. Matches the emitter's form — `_[a-fA-F0-9]+` of ANY length and
# mixed case (e.g. `name_[80AB]`, `name_[abc123]`; see
# scope_manager._PARAM_HASH_PATTERN) — plus the `<...>` variant.
_HASH_SUFFIX = re.compile(r"_[\[<][a-fA-F0-9]+[\]>]$")
_TOKEN_SPLIT = re.compile(r"[^A-Za-z0-9]+")

# bsg.* keys whose values are run-scoped nonces — excluded from card
# dominant_metadata so card_input_hash stays stable across rebuilds.
_CARD_VOLATILE_META_KEYS = frozenset({"bsg.index_id"})
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def _clean_name(name: str) -> str:
    """Strip collision-hash suffixes and `Class::member` path decoration."""
    base = _HASH_SUFFIX.sub("", name)
    if "::" in base:
        base = base.rsplit("::", 1)[-1]
    return base


def _tokenize(name: str) -> list[str]:
    """Split an identifier into lowercase tokens across naming conventions."""
    tokens: list[str] = []
    for piece in _TOKEN_SPLIT.split(name):
        if not piece:
            continue
        for sub in _CAMEL_BOUNDARY.split(piece):
            if sub:
                tokens.append(sub.lower())
    return tokens


def _title_case(text: str) -> str:
    return " ".join(w.capitalize() for w in text.split() if w)


def _dir_label(file_paths: list[str], blocklist: set[str]) -> str | None:
    """Tier 1: plurality parent directory of member files, generic segments
    dropped, remaining segments title-cased (`backend/app/services` →
    "Backend Services")."""
    dir_counts: Counter[str] = Counter()
    for path in file_paths:
        parent = path.rsplit("/", 1)[0] if "/" in path else ""
        if parent:
            dir_counts[parent] += 1
    if not dir_counts:
        return None
    # Deterministic plurality: count desc, then path asc.
    dominant = min(
        dir_counts.items(), key=lambda kv: (-kv[1], kv[0])
    )[0]
    segments = [
        seg
        for seg in dominant.split("/")
        if seg and seg.lower() not in blocklist
    ]
    if not segments:
        return None
    # Entity.file may be absolute — take the deepest non-generic segments so
    # machine-specific prefixes never leak into labels.
    return _title_case(" ".join(segments[-2:]).replace("-", "_").replace("_", " "))


def _ctfidf_label(
    member_names: list[str], all_name_tokens: list[set[str]]
) -> str | None:
    """Tier 2: c-TF-IDF — tokens frequent in-cluster but rare across other
    communities. Label = top 2–3 terms, title-cased."""
    tf: Counter[str] = Counter()
    for name in member_names:
        tf.update(_tokenize(name))
    n_comms = len(all_name_tokens)
    if not tf or n_comms < 2:
        # Single-community corpus: nothing is "rare across other communities".
        return None
    cluster_tokens = set(tf)
    df: Counter[str] = Counter()
    for toks in all_name_tokens:
        for tok in toks & cluster_tokens:
            df[tok] += 1
    scored = sorted(
        tf,
        key=lambda t: (-(tf[t] * math.log((n_comms + 1) / (1 + df[t]))), t),
    )
    top = [
        t
        for t in scored
        if len(t) >= 2 and tf[t] * math.log((n_comms + 1) / (1 + df[t])) > 0
    ][:3]
    if not top:
        return None
    return _title_case(" ".join(top))


def _common_affix(member_names: list[str]) -> str | None:
    """Tier 3: longest common prefix or suffix (>=4 chars) across cleaned
    member names."""
    cleaned = [n for n in (_clean_name(n) for n in member_names) if n]
    if len(cleaned) < 2:
        return None
    prefix = cleaned[0]
    for name in cleaned[1:]:
        while prefix and not name.startswith(prefix):
            prefix = prefix[:-1]
    if len(prefix) >= 4:
        label = _title_case(re.sub(r"[_\-.]+$", "", prefix))
        # degenerate affix (all separators, e.g. "____") strips to "" — fall
        # through to the next tier rather than emit an empty label.
        if label:
            return label
    suffix = cleaned[0]
    for name in cleaned[1:]:
        while suffix and not name.endswith(suffix):
            suffix = suffix[1:]
    if len(suffix) >= 4:
        label = _title_case(re.sub(r"^[_\-.]+", "", suffix))
        if label:
            return label
    return None


def label_communities(
    communities: list["Community"],
    entities: dict[str, "Entity"],
    degree_of: Callable[[str], int],
    generic_dir_blocklist: set[str],
) -> None:
    """Assign `heuristic_label` on each community in place; dedup with (n)."""
    all_name_tokens = [
        {
            tok
            for eid in c.member_entity_ids
            if eid in entities
            for tok in _tokenize(_clean_name(entities[eid].name))
        }
        for c in communities
    ]

    labels: list[str] = []
    for i, comm in enumerate(communities):
        member_names = [
            entities[eid].name
            for eid in comm.member_entity_ids
            if eid in entities
        ]
        label = _dir_label(comm.file_paths, generic_dir_blocklist)
        if label is None:
            label = _ctfidf_label(member_names, all_name_tokens)
        if label is None:
            label = _common_affix(member_names)
        if label is None:
            best = max(
                comm.member_entity_ids,
                key=lambda e: (degree_of(e), e),
                default=None,
            )
            if best is not None and best in entities:
                label = _clean_name(entities[best].name)
        if not label:
            label = f"Community_{comm.id}"
        labels.append(label)

    # Dedup identical labels with a suffix ("Root (2)").
    seen: dict[str, int] = {}
    for i, label in enumerate(labels):
        count = seen.get(label, 0) + 1
        seen[label] = count
        communities[i].heuristic_label = (
            label if count == 1 else f"{label} ({count})"
        )


# ======================================================================
# T16: `batho communities label` — post-build LLM labeling
# ======================================================================

_LABEL_STOPWORDS = frozenset({
    "the", "and", "of", "for", "a", "an", "to", "in", "on", "with", "by",
    "or", "at", "as", "is", "it",
})


def community_edge_profiles(
    graph: Any, rows: list[dict[str, Any]]
) -> dict[Any, dict[str, float]]:
    """One pass over graph.relationships → {community_id: {intra, inter}}.

    Per-row `member_entity_ids` may overlap across hierarchy levels (a parent
    row contains its descendants' members), so each entity maps to every row
    it belongs to — preserving per-row intra/inter semantics exactly.
    """
    member_to_comms: dict[str, list[Any]] = {}
    for row in rows:
        cid = row.get("community_id")
        for eid in row.get("member_entity_ids") or []:
            member_to_comms.setdefault(eid, []).append(cid)
    profiles: dict[Any, dict[str, float]] = {}
    for rel in getattr(graph, "relationships", []):
        s_set = set(member_to_comms.get(rel.source_id, ()))
        t_set = set(member_to_comms.get(rel.target_id, ()))
        if not s_set and not t_set:
            continue
        for cid in s_set & t_set:
            profiles.setdefault(cid, {"intra": 0.0, "inter": 0.0})["intra"] += 1.0
        for cid in s_set - t_set:
            profiles.setdefault(cid, {"intra": 0.0, "inter": 0.0})["inter"] += 1.0
        for cid in t_set - s_set:
            profiles.setdefault(cid, {"intra": 0.0, "inter": 0.0})["inter"] += 1.0
    return profiles


def build_community_card(
    row: dict[str, Any],
    graph: Any,
    parent_label: str | None = None,
    max_card_tokens: int = 200,
    edge_profile: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Deterministic community card — the only content the model sees.

    Pure function of (row, graph): identical inputs → identical card, which is
    what makes `label_input_hash` meaningful across runs. Card content is a
    bounded dict (~200 tokens target) — communities are named from summaries,
    not full dumps.
    """
    member_ids = row.get("member_entity_ids") or []
    member_set = set(member_ids)

    # top-10 members by degree (graph degree; adjacency fallback)
    def _deg(eid: str) -> int:
        try:
            return graph.degree_by_endpoint(eid)
        except Exception:
            return 0

    top_members = sorted(member_ids, key=lambda e: (-_deg(e), e))[:10]
    entities = getattr(graph, "entities", {})
    top_entries = []
    for eid in top_members:
        ent = entities.get(eid)
        if ent is None:
            continue
        top_entries.append({
            "name": getattr(ent, "name", ""),
            "type": str(getattr(ent, "type", "")),
            "signature": getattr(ent, "signature", None),
        })

    # dominant dirs / file names
    file_paths = row.get("file_paths") or []
    dir_counts: dict[str, int] = {}
    file_names: list[str] = []
    for fp in file_paths:
        if "/" in fp:
            d = fp.rsplit("/", 1)[0]
            dir_counts[d] = dir_counts.get(d, 0) + 1
        file_names.append(fp.rsplit("/", 1)[-1])
    dominant_dirs = sorted(dir_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:5]

    # dominant bsg.* metadata across members — run-scoped keys like
    # bsg.index_id carry per-run nonces: including them makes the card (and
    # therefore label_input_hash) differ on every rebuild, silently breaking
    # label carry-forward and the incremental re-label gate.
    tag_counts: dict[str, dict[str, int]] = {}
    for eid in member_ids:
        ent = entities.get(eid)
        md = getattr(ent, "metadata", None) or {}
        for key, val in md.items():
            if not str(key).startswith("bsg."):
                continue
            if str(key) in _CARD_VOLATILE_META_KEYS:
                continue
            vals = val if isinstance(val, (list, tuple)) else [val]
            for v in vals:
                bucket = tag_counts.setdefault(str(key), {})
                sv = str(v)
                bucket[sv] = bucket.get(sv, 0) + 1
    dominant_meta = {
        k: sorted(v.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
        for k, v in sorted(tag_counts.items())
    }

    # intra- vs inter-community edge weight
    if edge_profile is None:
        intra = inter = 0.0
        for rel in getattr(graph, "relationships", []):
            s_in = rel.source_id in member_set
            t_in = rel.target_id in member_set
            if s_in and t_in:
                intra += 1.0
            elif s_in or t_in:
                inter += 1.0
    else:
        intra = edge_profile.get("intra", 0.0)
        inter = edge_profile.get("inter", 0.0)

    card = {
        "community_id": row.get("community_id"),
        "level": row.get("level") or 0,
        "parent_label": parent_label,
        "entity_count": row.get("entity_count", len(member_ids)),
        "file_count": row.get("file_count", len(file_paths)),
        "top_entities": top_entries,
        "dominant_dirs": [d for d, _ in dominant_dirs],
        "file_names": sorted(file_names)[:10],
        "dominant_metadata": dominant_meta,
        "edge_profile": {"intra": intra, "inter": inter},
        "heuristic_label": row.get("heuristic_label") or row.get("name") or "",
    }
    # Enforce the token budget by shrinking the biggest lists first.
    import json as _json
    while len(_json.dumps(card, default=str)) > max_card_tokens * 4:
        if card["top_entities"]:
            card["top_entities"].pop()
        elif len(card["file_names"]) > 5:
            card["file_names"].pop()
        else:
            break
    return card


def _card_terms(card: dict[str, Any]) -> set[str]:
    """Normalized token set the label is allowed to draw from."""
    import json as _json
    text = _json.dumps(card, default=str).lower()
    return {
        tok for tok in re.split(r"[^a-z0-9]+", text)
        if len(tok) >= 3 and tok not in _LABEL_STOPWORDS
    }


def label_terms_in_card(
    label: str,
    card: dict[str, Any],
    key_terms: list[str] | None = None,
) -> bool:
    """Anti-hallucination check (T16): every meaningful label token must be
    present in the card, or appear in the model's declared key_terms that are
    themselves grounded in the card."""
    card_terms = _card_terms(card)
    kt_terms = set()
    for kt in key_terms or []:
        kt_norm = re.sub(r"[^a-z0-9]+", " ", str(kt).lower()).split()
        # a declared key_term is trusted only if it appears in the card
        if all(t in card_terms for t in kt_norm if t not in _LABEL_STOPWORDS):
            kt_terms.update(kt_norm)
    allowed = card_terms | kt_terms
    label_toks = [
        t for t in re.split(r"[^a-z0-9]+", str(label).lower())
        if t and t not in _LABEL_STOPWORDS
    ]
    if not label_toks:
        return False
    return all(t in allowed for t in label_toks)


def card_input_hash(card: dict[str, Any]) -> str:
    """Stable hash of card content — incremental labeling gate.

    ``community_id`` stays in the card for the model's benefit but is
    excluded from the hash: ids are detection-order dependent, so hashing
    them would break ``carry_forward_labels`` on exactly the rebuilds it
    exists for.
    """
    import hashlib
    import json as _json
    return hashlib.sha256(
        _json.dumps(
            {k: v for k, v in card.items() if k != "community_id"},
            sort_keys=True, default=str,
        ).encode()
    ).hexdigest()[:16]


def _default_llm_labeler(
    provider: str, model: str, api_key: str | None
):
    """Thin provider call — {label, description, key_terms} JSON out.

    Anthropic + OpenAI-compatible shapes via stdlib urllib. Timeout raises —
    callers fall back to heuristic. Injected `labeler` fakes bypass this in
    tests, so the surface stays pluggable for local providers later.
    """
    import json as _json
    import urllib.request

    def _label_card(card: dict[str, Any]) -> dict[str, Any]:
        prompt = (
            "Name this code community. Respond ONLY with JSON: "
            '{"label": "<2-5 word name>", "description": "<one line>", '
            '"key_terms": ["<terms from the card that justify the name>"]}.\n'
            "Card:\n" + _json.dumps(card, default=str)
        )
        if provider == "anthropic":
            req = urllib.request.Request(
                "https://api.anthropic.com/v1/messages",
                data=_json.dumps({
                    "model": model,
                    "max_tokens": 256,
                    "messages": [{"role": "user", "content": prompt}],
                }).encode(),
                headers={
                    "content-type": "application/json",
                    "x-api-key": api_key or "",
                    "anthropic-version": "2023-06-01",
                },
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = _json.loads(resp.read())
            text = body["content"][0]["text"]
        else:  # openai-compatible
            req = urllib.request.Request(
                "https://api.openai.com/v1/chat/completions",
                data=_json.dumps({
                    "model": model,
                    "response_format": {"type": "json_object"},
                    "messages": [{"role": "user", "content": prompt}],
                }).encode(),
                headers={
                    "content-type": "application/json",
                    "authorization": f"Bearer {api_key or ''}",
                },
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = _json.loads(resp.read())
            text = body["choices"][0]["message"]["content"]
        parsed = _json.loads(text)
        return {
            "label": str(parsed.get("label", "")),
            "description": str(parsed.get("description", "")),
            "key_terms": list(parsed.get("key_terms") or []),
        }

    return _label_card


def llm_label_communities(
    rows: list[dict[str, Any]],
    graph: Any,
    llm_cfg: dict[str, Any],
    labeler=None,
    logger=None,
) -> dict[str, Any]:
    """Label community rows in place; returns stats.

    Incremental: `label_input_hash` unchanged → skip (no labeler call).
    Per-community failure → heuristic fallback (label_source='heuristic');
    never raises — labeling is best-effort, exit-0 semantics live in the CLI.
    """
    import os

    stats = {"labeled": 0, "skipped_unchanged": 0, "fallback": 0}
    if not llm_cfg.get("enabled"):
        stats["disabled"] = True
        return stats
    api_key = os.getenv("BATHO_LLM_API_KEY")
    if not api_key:
        stats["disabled"] = True
        stats["reason"] = "BATHO_LLM_API_KEY not set"
        return stats
    if labeler is None:
        labeler = _default_llm_labeler(
            llm_cfg.get("provider", "anthropic"),
            llm_cfg.get("model", "claude-haiku-4-5-20251001"),
            api_key,
        )
    provider_model = f"{llm_cfg.get('provider', 'anthropic')}:{llm_cfg.get('model', '')}"
    max_tokens = int(llm_cfg.get("max_card_tokens", 200))

    by_id = {r.get("community_id"): r for r in rows}
    # One edge scan for all cards instead of O(#communities × #relationships).
    edge_profiles = community_edge_profiles(graph, rows)
    for row in sorted(rows, key=lambda r: r.get("community_id", 0)):
        parent = by_id.get(row.get("parent_id"))
        parent_label = (
            (parent or {}).get("llm_label")
            or (parent or {}).get("heuristic_label")
        )
        card = build_community_card(
            row, graph, parent_label, max_tokens,
            edge_profile=edge_profiles.get(row.get("community_id")),
        )
        digest = card_input_hash(card)
        if row.get("label_input_hash") == digest and row.get("label_source"):
            stats["skipped_unchanged"] += 1
            continue
        try:
            result = labeler(card)
            label = str(result.get("label", "")).strip()
            key_terms = list(result.get("key_terms") or [])
            if label and label_terms_in_card(label, card, key_terms):
                row["llm_label"] = label
                row["label_source"] = "llm"
                row["label_model"] = provider_model
                stats["labeled"] += 1
            else:
                row["label_source"] = "heuristic"
                stats["fallback"] += 1
            # deterministic outcomes stamp the hash; exceptions don't (retry
            # next run even with unchanged input)
            row["label_input_hash"] = digest
        except Exception as exc:
            row["label_source"] = "heuristic"
            stats["fallback"] += 1
            if logger:
                logger.warning(
                    "community_label_llm_failed",
                    community_id=row.get("community_id"),
                    error=str(exc),
                )
    return stats


def carry_forward_labels(
    rows: list[dict[str, Any]],
    prev_rows: list[dict[str, Any]] | None,
    graph: Any,
    max_card_tokens: int = 200,
) -> int:
    """Re-stamp ``llm_label``/``label_source``/``label_input_hash``/``label_model``
    onto freshly-rebuilt community rows whose label input is unchanged.

    Build/patch community rebuilds serialize new ``Community`` objects whose
    ``llm_*`` columns are empty — without this pass every rebuild erases all
    LLM labels AND the ``label_input_hash`` values the incremental skip in
    ``llm_label_communities`` needs. Carry-forward keys on the recomputed
    ``card_input_hash`` (card content), never ``community_id`` — ids are
    detection-order dependent and shift when membership changes.

    Rows are processed parents-before-children (``level`` then
    ``community_id``) so a parent's carried ``llm_label`` is available as
    ``parent_label`` when the child's digest is computed — matching the
    input the labeler saw.

    Returns the number of rows re-stamped.
    """
    by_hash = {
        r.get("label_input_hash"): r
        for r in (prev_rows or [])
        if r.get("label_input_hash") and r.get("label_source")
    }
    if not by_hash:
        return 0
    by_id = {r.get("community_id"): r for r in rows}
    carried = 0
    ordered = sorted(
        rows, key=lambda r: (r.get("level") or 0, r.get("community_id", 0))
    )
    edge_profiles = community_edge_profiles(graph, rows)
    for row in ordered:
        parent = by_id.get(row.get("parent_id"))
        parent_label = (
            (parent or {}).get("llm_label")
            or (parent or {}).get("heuristic_label")
        )
        card = build_community_card(
            row, graph, parent_label, max_card_tokens,
            edge_profile=edge_profiles.get(row.get("community_id")),
        )
        digest = card_input_hash(card)
        prev = by_hash.get(digest)
        if prev is None:
            continue
        row["llm_label"] = prev.get("llm_label", "")
        row["label_source"] = prev.get("label_source", "")
        row["label_model"] = prev.get("label_model", "")
        row["label_input_hash"] = digest
        carried += 1
    return carried
