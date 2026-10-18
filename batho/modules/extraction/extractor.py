"""
backend/context/extractor.py — Production ASTExtractor base class.

Hardened from the prototype with:
- Per-file exception isolation (one bad file won't abort the whole scan)
- Max file size guard (default 500KB) for generated/minified files
- Encoding detection fallback: UTF-8 → latin-1 → replace
- Consistent import path (no cross-package hacks)

Design principles:
- No raw dicts escape this layer — all outputs are frozen Pydantic models.
- Deterministic: same source always produces same entities.
- Uses QueryCursor(Query(...)).captures() — tree-sitter 0.25+ compliant API.
"""

from __future__ import annotations

import abc
import bisect
import hashlib
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tree_sitter import Language, Node, Query, QueryCursor
from tree_sitter_language_pack import get_language, get_parser

_TS_THREAD_LOCAL = threading.local()


def get_pooled_parser(language: str) -> Any:
    """Retrieve or initialize a thread-local tree-sitter Parser instance for a language."""
    if not hasattr(_TS_THREAD_LOCAL, "parsers"):
        _TS_THREAD_LOCAL.parsers = {}
    if language not in _TS_THREAD_LOCAL.parsers:
        _TS_THREAD_LOCAL.parsers[language] = get_parser(language)  # type: ignore[arg-type]
    return _TS_THREAD_LOCAL.parsers[language]


from batho.utils.hash import compute_bytes_hash
from batho.utils.logging import get_logger

from batho.core.schemas import (
    Entity,
    EntityMetadata,
    EntityType,
    Relationship,
    RelationshipType,
    PackageMetadata,
    DescriptorSuffix,
    generate_hierarchical_id,
    SymbolRole,
)


def _sanitize_identifier(name: str) -> str:
    # Replace invalid characters with underscore
    sanitized = re.sub(r'[^\w]', '_', name)
    if not sanitized:
        return "_"
    if sanitized[0].isdigit():
        return f"_{sanitized}"
    return sanitized


def _file_to_descriptors(filepath: str) -> list[tuple[str, DescriptorSuffix]]:
    from pathlib import Path
    from batho.core.config import get_active_root
    path_obj = Path(filepath)
    try:
        path_obj = path_obj.relative_to(get_active_root())
    except ValueError:
        pass
    posix_path = path_obj.with_suffix("").as_posix()
    parts = [p for p in posix_path.split("/") if p]
    return [(_sanitize_identifier(part), DescriptorSuffix.NAMESPACE) for part in parts]


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

# Capture name suffixes that supply auxiliary metadata about a definition node.
_META_SUFFIXES: frozenset[str] = frozenset(
    {
        "params",
        "return_type",
        "visibility",
        "docstring",
        "invocation",
        "bases",
        "implements",
        "extends",
        "trait",
        "receiver",
        "type",
        "accessor",  # T03 fix (c3f5a7b9): TS get/set keyword for PROPERTY access_type
    }
)

# Map from base capture key (e.g. "def.function") → EntityType
_CAPTURE_ENTITY_MAP: dict[str, EntityType] = {
    "def.function": EntityType.FUNCTION,
    "def.method": EntityType.METHOD,
    "def.class": EntityType.CLASS,
    "def.module": EntityType.MODULE,
    "def.struct": EntityType.STRUCT,
    "def.interface": EntityType.INTERFACE,
    "def.protocol": EntityType.INTERFACE,
    "def.field": EntityType.FIELD,
    "def.enum": EntityType.ENUM,
    "def.trait": EntityType.TRAIT,
    "def.type_alias": EntityType.TYPE_ALIAS,
    "def.constant": EntityType.CONSTANT,
    "def.namespace": EntityType.NAMESPACE,
    "def.entry_point": EntityType.ENTRY_POINT,
    "def.object": EntityType.CLASS,  # Kotlin singleton objects are classes
    "def.property": EntityType.PROPERTY,
    "def.constructor": EntityType.CONSTRUCTOR,
    "def.enum_member": EntityType.ENUM_MEMBER,
    "def.parameter": EntityType.PARAMETER,
    "def.type_parameter": EntityType.TYPE_PARAMETER,
}

# Map from reference capture key → RelationshipType
_CAPTURE_REL_MAP: dict[str, RelationshipType] = {
    "ref.call": RelationshipType.CALLS,
    "ref.import": RelationshipType.IMPORTS,
    "ref.inherit": RelationshipType.INHERITS,
    "ref.implement": RelationshipType.IMPLEMENTS,
    "ref.use": RelationshipType.USES,
    "ref.read": RelationshipType.READS,   # T09: was REFERENCES
    "ref.write": RelationshipType.WRITES,  # T09: was REFERENCES
    # T10/T11/T12: New capture types reuse existing relationship types
    "ref.indirect_call": RelationshipType.CALLS,    # T10: indirect call detection
    "ref.dynamic_import": RelationshipType.IMPORTS,  # T11: dynamic import() detection
    "ref.re_export": RelationshipType.IMPORTS,       # T12: re-export detection
}

# Captures that provide type linkage for CONTAINS relationship synthesis.
# These are not standard references — they link methods to their enclosing
# struct/enum/trait types across disjoint AST nodes (e.g. Rust impl blocks,
# Go receiver methods).
_CONTAINS_HINT_CAPTURES: frozenset[str] = frozenset({
    "ref.impl_type",
    "ref.receiver_type",
})

# ---------------------------------------------------------------------------
# T5 rationale layer — comment syntax per language
# ---------------------------------------------------------------------------
# Marker comments (`# WHY:`, `// NOTE:`, `/* WHY: */`, ...) are promoted to
# COMMENT_BLOCK entities carrying a RATIONALE_FOR edge to the symbol they
# explain. Delimiters are comment-syntax-aware per language — a `#`-only
# default would miss lua `--` and the whole `/* */` C-family. The marker list
# and case sensitivity come from `extraction.rationale_markers` /
# `extraction.rationale_markers_case_sensitive` (parsing_config passthrough).
_DEFAULT_RATIONALE_MARKERS: tuple[str, ...] = ("WHY:", "NOTE:")

_LINE_COMMENT_PREFIXES: dict[str, tuple[str, ...]] = {
    "python": ("#",),
    "ruby": ("#",),
    "perl": ("#",),
    "bash": ("#",),
    "yaml": ("#",),
    "toml": ("#",),
    "r": ("#",),
    "julia": ("#",),
    "php": ("//", "#"),
    "typescript": ("//",),
    "javascript": ("//",),
    "rust": ("//",),
    "go": ("//",),
    "java": ("//",),
    "kotlin": ("//",),
    "scala": ("//",),
    "csharp": ("//",),
    "swift": ("//",),
    "dart": ("//",),
    "cpp": ("//",),
    "c": ("//",),
    "zig": ("//",),
    "verilog": ("//",),
    "lua": ("--",),
    "haskell": ("--",),
    "agda": ("--",),
    "hcl": ("#", "//"),
    "hack": ("//",),
    "objectivec": ("//",),
    "erlang": ("%",),
}

_BLOCK_COMMENT_PAIRS: dict[str, tuple[tuple[str, str], ...]] = {
    "typescript": (("/*", "*/"),),
    "javascript": (("/*", "*/"),),
    "rust": (("/*", "*/"),),
    "go": (("/*", "*/"),),
    "java": (("/*", "*/"),),
    "kotlin": (("/*", "*/"),),
    "scala": (("/*", "*/"),),
    "csharp": (("/*", "*/"),),
    "swift": (("/*", "*/"),),
    "dart": (("/*", "*/"),),
    "cpp": (("/*", "*/"),),
    "c": (("/*", "*/"),),
    "php": (("/*", "*/"),),
    "css": (("/*", "*/"),),
    "zig": (("/*", "*/"),),
    "verilog": (("/*", "*/"),),
    "ocaml": (("(*", "*)"),),
    "haskell": (("{-", "-}"),),
    "agda": (("{-", "-}"),),
    "hcl": (("/*", "*/"),),
    "hack": (("/*", "*/"),),
    "objectivec": (("/*", "*/"),),
    "html": (("<!--", "-->"),),
}

# RATIONALE_FOR edges only point at the symbol kinds a comment can explain.
_RATIONALE_TARGET_TYPES: frozenset[EntityType] = frozenset({
    EntityType.FUNCTION,
    EntityType.METHOD,
    EntityType.CLASS,
})


_BUILTINS_BY_LANG: dict[str, set[str]] = {
    "python": {"int", "str", "float", "bool", "dict", "list", "set", "tuple", "len", "range", "print", "self", "cls", "None", "True", "False", "object", "type", "open", "Exception", "ValueError", "TypeError", "KeyError", "IndexError", "any", "all", "sum", "min", "max", "zip", "enumerate", "map", "filter", "isinstance", "id", "hash", "super", "getattr", "setattr", "hasattr", "iter", "next"},
    "javascript": {"console", "log", "Object", "Array", "String", "Number", "Boolean", "null", "undefined", "true", "false", "window", "document", "process", "require", "module", "exports", "Error", "Promise", "JSON", "Math", "setTimeout", "clearTimeout", "setInterval", "clearInterval"},
    "typescript": {"console", "log", "Object", "Array", "String", "Number", "Boolean", "null", "undefined", "true", "false", "window", "document", "process", "require", "module", "exports", "Error", "Promise", "JSON", "Math", "setTimeout", "clearTimeout", "setInterval", "clearInterval", "any", "string", "number", "boolean", "void", "never", "unknown"},
    "go": {"int", "int32", "int64", "uint", "uint32", "uint64", "float32", "float64", "string", "bool", "byte", "rune", "error", "nil", "true", "false", "len", "cap", "make", "new", "append", "copy", "close", "delete", "panic", "recover", "print", "println"},
    "rust": {"int", "u8", "u16", "u32", "u64", "u128", "usize", "i8", "i16", "i32", "i64", "i128", "isize", "f32", "f64", "str", "String", "bool", "char", "Option", "Some", "None", "Result", "Ok", "Err", "Vec", "Box", "Rc", "Arc", "self", "Self", "true", "false", "println", "print", "format", "panic"}
}


def _prune_unresolved(
    ref_text: str,
    rel_type: RelationshipType,
    file_imports: list,
    language: str,
    filepath: str,
    prune_enabled: bool = True,
    imported_names: "set[str] | None" = None,
) -> bool:
    """T14: prune decision via the plugin hook when a host is active.

    Byte-identical to :func:`_should_prune_unresolved` (parity-proven in
    tests): the hook's pure decision function receives the pack-derived
    builtin/noise sets; without an active host the engine implementation is
    the fallback (--no-plugins path).
    """
    try:
        from batho_plugin.runtime import get_active_plugin_host

        host = get_active_plugin_host()
    except Exception:
        host = None
    if host is None:
        return _should_prune_unresolved(
            ref_text, rel_type, file_imports, language, filepath,
            prune_enabled, imported_names,
        )
    # Pack sets are process-stable: cache per language (the delegate runs
    # ~100K+ times per build — C4 forbids per-call set merges).
    cached = _PRUNE_PACK_SETS_CACHE.get(language)
    if cached is None:
        builtins = host.get_set("builtins", language=language)
        noise = host.get_set("noise_symbols", language=language)
        cached = (builtins or None, noise or None)
        _PRUNE_PACK_SETS_CACHE[language] = cached
    hook_builtins, hook_noise = cached
    from batho_plugin.hooks.prune_stub import should_prune as _hook_should_prune

    decision = _hook_should_prune(
        ref_text,
        rel_type.name,
        language,
        filepath,
        prune_enabled,
        frozenset(imported_names) if imported_names is not None else None,
        builtins=hook_builtins,
        noise_symbols=hook_noise,
    )
    return decision.prune


_PRUNE_PACK_SETS_CACHE: dict[str, tuple[frozenset[str], frozenset[str]] | None] = {}


def _stamp_fallback_language(entities: list, language_name: str | None) -> None:
    """F8: stamp the engine-owned ``language`` key on fallback-parser entities.

    The fallback parser is language-agnostic (regex heuristics only), so its
    entities carry empty metadata — AST entities get the stamp in
    ``_collect_metadata_with_source``. Storage-view rendering reads
    ``metadata["language"]`` and the per-extension derivation was deleted, so
    the stamp must come from the engine, never from plugin dispatch (it would
    be absent under ``--no-plugins``).
    """
    if language_name is None:
        return
    for entity in entities:
        meta = getattr(entity, "metadata", None)
        if isinstance(meta, dict):
            meta.setdefault("language", language_name)


def _should_prune_unresolved(ref_text: str, rel_type: RelationshipType, file_imports: list, language: str, filepath: str, prune_enabled: bool = True, imported_names: "set[str] | None" = None) -> bool:
    """Check if an unresolved reference should be pruned.

    Args:
        ref_text: The reference text to check
        rel_type: The relationship type
        file_imports: List of imports in the file
        language: The programming language
        filepath: The file path
        prune_enabled: Whether pruning is enabled (cached from config to avoid repeated lookups)
        imported_names: Optional pre-built set of all module paths and from-import
            symbols for O(1) rule-4 membership check (FIX 10). Falls back to
            the O(I) file_imports scan when None.
    """
    if "/" not in filepath and "\\" not in filepath:
        return False

    if not prune_enabled:
        return False

    name = ref_text.strip()
    if not name:
        return True

    # 1. Prune builtins
    builtins = _BUILTINS_BY_LANG.get(language, set())
    if name in builtins or name.lower() in builtins:
        return True

    # 2. Prune common noise stubs
    if name in {"self", "cls", "this", "err", "error", "nil", "null", "undefined", "true", "false", "args", "kwargs", "ctx", "context"}:
        return True

    # 3. If it has dot, slash, or colon, it's likely a qualified name or path -> keep
    if "." in name or "/" in name or ":" in name:
        return False

    # 4. If it is imported in this file -> keep
    # FIX 10: use O(1) set lookup when pre-built imported_names is available.
    if imported_names is not None:
        if name in imported_names:
            return False
    else:
        for module_path, symbols, _ in file_imports:
            if name == module_path or name in symbols:
                return False

    # 5. If it's a CALLS or IMPORTS or INHERITS or IMPLEMENTS, keep (could be cross-file function/class)
    if rel_type in (RelationshipType.CALLS, RelationshipType.IMPORTS, RelationshipType.INHERITS, RelationshipType.IMPLEMENTS):
        return False

    # 6. Otherwise, if it's USES or REFERENCES or READS/WRITES, and not imported, and has no dots -> prune!
    return True



# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _node_text(node: Node, source: bytes) -> str:
    """Slice raw bytes and decode to a clean UTF-8 string."""
    return (
        source[node.start_byte : node.end_byte]
        .decode("utf-8", errors="replace")
        .strip()
    )


def _clean_docstring(text: str) -> str:
    """Strip surrounding quote characters from docstrings."""
    t = text.strip()

    # Handle Python-prefixed literals captured as docstrings (e.g. b"""...""").
    prefix_match = re.match(r"(?i)^(?:br|rb|fr|rf|b|r|f|u)(?=[\"'])", t)
    if prefix_match:
        t = t[prefix_match.end() :].lstrip()

    for q in ('"""', "'''", '"', "'"):
        if t.startswith(q) and t.endswith(q) and len(t) >= 2 * len(q):
            return t[len(q) : -len(q)].strip()
    return t


def _relationship_capture_info(
    cap_name: str,
) -> tuple[RelationshipType | None, str | None]:
    """Map a capture name to relationship type and optional capture variant."""
    parts = cap_name.split(".")
    if len(parts) < 2 or parts[0] != "ref":
        return None, None

    base_key = f"{parts[0]}.{parts[1]}"
    rel_type = _CAPTURE_REL_MAP.get(base_key)
    if rel_type is None:
        return None, None

    suffix = ".".join(parts[2:]).strip() if len(parts) > 2 else ""
    return rel_type, suffix or None


def _normalize_import_target(raw: str) -> str:
    """Normalize a raw import string to improve cross-file matching."""
    text = raw.strip().strip(",;")
    if not text:
        return ""

    text = re.sub(r"\s+as\s+\w+$", "", text).strip()

    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'", "`"}:
        text = text[1:-1].strip()
    elif text.startswith("<") and text.endswith(">"):
        text = text[1:-1].strip()

    # Normalize Node.js builtin prefix: node:fs -> fs
    # Both forms are valid per Node.js spec; resolution is prefix-insensitive.
    if text.startswith("node:"):
        text = text[5:]

    text = text.replace("::", ".")
    return text.strip()


def _stub_ref_key(ref_text: str) -> str:
    """Dot-normalized ref key for a contextual stub ID.

    The stub ID format is ``unresolved:{caller_scope}::{ref_key}`` and the
    ``::`` separator must be unambiguous. Ref text can itself contain ``::``
    (Rust paths like ``std::io::Write``, Ruby constant paths like ``Foo::Bar``),
    so the ref key is rewritten to the resolver's dotted-FQN convention — the
    same convention ``_normalize_import_target`` uses for import targets.
    Display name and metadata keep the caller-written spelling.
    """
    return ref_text.replace("::", ".")


# Attribute/member node types whose object field names the receiver of a
# call like ``svc.get_entity()`` — keyed by node type to the object-side
# field names used across tree-sitter grammars.
_RECEIVER_PARENT_FIELDS: dict[str, tuple[str, ...]] = {
    "attribute": ("object",),                    # Python, Ruby
    "member_expression": ("object",),            # JS/TS
    "selector_expression": ("operand",),         # Go
    "field_expression": ("value",),              # Rust, C++
    "method_invocation": ("object",),            # Java
    "member_access_expression": ("expression", "object"),  # C#
    "navigation_expression": ("expression",),    # Kotlin/Swift-ish
    "field_access": ("object", "value"),         # fallback shapes
    "call_expression": ("object", "value"),      # safety net
}

# Ancestor node types where a call expression is bound to a name on the
# left-hand side (``var = f()``, ``param: T = Depends(f)``, ``let x = f()``).
_BINDING_ANCESTOR_FIELDS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    # node_type: (name-ish fields, value-ish fields)
    "assignment": (("left",), ("right",)),                    # Python, Go, JS
    "augmented_assignment": (("left",), ("right",)),
    "typed_default_parameter": (("name",), ("value",)),       # Python
    "typed_parameter": (("name",), ("value",)),
    "default_parameter": (("name", "pattern"), ("value",)),
    "required_parameter": (("pattern", "name"), ("value",)),  # TS
    "optional_parameter": (("pattern", "name"), ("value",)),  # TS
    "variable_declarator": (("name",), ("value",)),           # JS/TS/Java
    "short_var_declaration": (("left",), ("right",)),         # Go
    "let_declaration": (("pattern",), ("value",)),            # Rust
    "let_mut_declaration": (("pattern",), ("value",)),
    "field_declaration": (("declarator", "name"), ("value",)),
    "public_field_definition": (("name",), ("value",)),       # TS class fields
    "pair": (("key",), ("value",)),                           # object literals
}

_IDENT_RE = re.compile(r"[A-Za-z_]\w*\Z")

# Call-like node types across grammars — ``call`` is Python's shape; most
# other tree-sitter grammars spell it differently, so binding walks and
# inner-call scans must recognize the whole set.
_CALL_NODE_TYPES = frozenset({
    "call",                      # Python
    "call_expression",           # JS/TS, Go, Rust, C/C++
    "method_invocation",         # Java
    "function_call_expression",  # PHP
    "method_call_expression",    # PHP
})

# Known DI-wrapper callee names whose single argument is the *meaningful*
# callee — ``Depends(f)``, ``Provide(f)``, ``inject(f)``. ``assigned_inner``
# is only recorded for these wrappers; a generic single-argument call like
# ``list(User)`` or ``sorted(users)`` must not record it, or the inner name
# gets treated as a type producer downstream (``x = list(User)`` would type
# ``x`` as ``User`` and fabricate ``x.foo()`` edges).
_DI_WRAPPER_NAMES: frozenset[str] = frozenset({
    "Depends",
    "Provide",
    "provide",
    "Inject",
    "inject",
})


def _receiver_object_text(node: Node, source: bytes) -> str | None:
    """Receiver object text for a call-site capture, e.g. ``svc`` in
    ``svc.get_entity()`` or ``self.db`` in ``self.db.execute()``.

    The call ref capture lands on the *attribute* identifier; its parent is
    the attribute/member node whose ``object`` (or grammar equivalent) field
    is the receiver expression. Returns None for bare calls (``f()``).
    """
    parent = node.parent
    if parent is None:
        return None
    field_names = _RECEIVER_PARENT_FIELDS.get(parent.type)
    if not field_names:
        return None
    obj = None
    for fname in field_names:
        obj = parent.child_by_field_name(fname)
        if obj is not None:
            break
    if obj is None or obj == node:
        return None
    txt = _node_text(obj, source)
    # Only simple receiver expressions qualify (identifier / dotted chain);
    # complex receivers like ``get_svc().m()`` carry no usable var name.
    if txt and len(txt) <= 128 and re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", txt):
        return txt
    return None


def _assigned_binding(node: Node, source: bytes) -> tuple[str | None, str | None]:
    """Name bound to this call's result, if the call is an assignment RHS.

    ``svc = get_graph_service()``      → ("svc", None)
    ``x: T = Depends(get_service)``    → ("x", "get_service")  # inner call
    ``const db = makeDb()``            → ("db", None)

    Returns (var_name, inner_callee). ``inner_callee`` is set only when the
    outer callee is a known DI wrapper (``_DI_WRAPPER_NAMES``: ``Depends(f)``/
    ``Provide(f)``/``inject(f)``-style patterns) whose sole argument is itself
    a call or bare identifier — the meaningful callee is the inner one.
    ``var_name`` is returned for any bound RHS; ``inner_callee`` stays None
    for ordinary calls like ``x = sorted(users)`` or ``x = list(User)``.
    """
    # The captured node is the callee identifier; climb to its call node
    # (grammar-specific type: `call` in Python, `call_expression` in JS/TS/Go/…).
    cur: Node | None = node
    while cur is not None and cur.type not in _CALL_NODE_TYPES:
        if cur.parent is None:
            return None, None
        # Stop at statement/block boundaries — capture isn't inside a call.
        if cur.parent.type in (
            "block", "program", "module", "function_definition",
            "class_definition", "source_file", "declaration_list",
        ):
            return None, None
        cur = cur.parent
    if cur is None:
        return None, None

    parent = cur.parent
    if parent is None:
        return None, None
    spec = _BINDING_ANCESTOR_FIELDS.get(parent.type)
    if spec is None:
        return None, None
    name_fields, value_fields = spec
    name_node = None
    for f in name_fields:
        name_node = parent.child_by_field_name(f)
        if name_node is not None:
            break
    value_node = None
    for f in value_fields:
        value_node = parent.child_by_field_name(f)
        if value_node is not None:
            break
    if name_node is None or value_node is None or value_node != cur:
        return None, None
    var_txt = _node_text(name_node, source)
    if not _IDENT_RE.fullmatch(var_txt or ""):
        return None, None

    # Wrapper-call inner callee: value is a call whose argument list holds
    # exactly one argument which is itself a call or a bare identifier —
    # DI helpers like ``Depends(get_service)``/``Provide[f]`` patterns where
    # the meaningful callee is the inner reference. Restricted to known DI
    # wrappers: any single-arg call (``sorted(users)``, ``list(User)``)
    # matches the shape structurally, so gating on the outer callee name
    # keeps ``assigned_inner`` from mislabeling ordinary calls.
    inner_callee = None
    fn_node = cur.child_by_field_name("function")
    outer_txt = _node_text(fn_node, source) if fn_node is not None else ""
    if not outer_txt:
        outer_txt = _node_text(node, source)
    if outer_txt.rsplit(".", 1)[-1] not in _DI_WRAPPER_NAMES:
        return var_txt, None
    args = cur.child_by_field_name("arguments")
    if args is not None:
        inner_calls = [c for c in args.children if c.type in _CALL_NODE_TYPES]
        non_punct = [c for c in args.children if c.type not in ("(", ")", ",", "comment")]
        if len(inner_calls) == 1 and len(non_punct) == 1:
            fn = inner_calls[0].child_by_field_name("function")
            if fn is not None:
                inner_txt = _node_text(fn, source)
                if re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", inner_txt or ""):
                    inner_callee = inner_txt
        elif len(non_punct) == 1 and non_punct[0].type in ("identifier", "attribute", "member_expression"):
            inner_txt = _node_text(non_punct[0], source)
            if re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", inner_txt or ""):
                inner_callee = inner_txt
    return var_txt, inner_callee


def _comment_node_at(root_node: Node, byte_offset: int) -> "Node | None":
    """Return the innermost ancestor covering *byte_offset* whose type is a
    comment node, or None.

    Comment node types differ across grammars (``comment``, ``line_comment``,
    ``block_comment``, ``multiline_comment``), so membership is checked by
    name substring on the deepest node covering the offset and each of its
    ancestors — a marker inside a string literal bottoms out in
    ``string``/``string_content`` nodes instead and returns None.
    """
    node: Node | None = root_node.descendant_for_byte_range(
        byte_offset, byte_offset
    )
    while node is not None:
        if "comment" in node.type:
            return node
        node = node.parent
    return None


def _byte_in_comment_node(root_node: Node, byte_offset: int) -> bool:
    """True when *byte_offset* lies inside a tree-sitter comment node."""
    return _comment_node_at(root_node, byte_offset) is not None


def _expand_import_targets(raw: str) -> list[str]:
    """Expand grouped import forms into resolvable target candidates."""
    normalized = _normalize_import_target(raw)
    if not normalized:
        return []

    candidates: list[str] = []
    seen: set[str] = set()
    stopwords = {
        ".",
        "as",
        "from",
        "import",
        "include",
        "library",
        "load",
        "loadnamespace",
        "require",
        "require_relative",
        "requirenamespace",
        "source",
        "using",
    }

    def _push(candidate: str) -> None:
        token = _normalize_import_target(candidate)
        if token.lower() in stopwords:
            return
        # Brace-group text is never itself a resolvable target — expansion
        # below emits the qualified member refs instead.
        if not token or "{" in token or "}" in token:
            return
        if token in seen:
            return
        seen.add(token)
        candidates.append(token)

    _push(normalized)

    # Rust-like grouped imports: foo::{bar, baz as qux, self, *}
    if "{" in normalized and "}" in normalized:
        prefix, remainder = normalized.split("{", 1)
        prefix = prefix.rstrip(":.").strip()
        members = remainder.rsplit("}", 1)[0]
        for member in members.split(","):
            token = member.strip()
            if not token:
                continue
            token = re.sub(r"\s+as\s+\w+$", "", token)
            if token in {"*", "self"}:
                _push(prefix)
                continue
            if prefix:
                _push(f"{prefix}.{token}")
            else:
                _push(token)

    # Leaf fallback helps `pkg.mod.sym` / `dir/file` forms where the leaf is a
    # first-party symbol — but a scoped npm leaf (@scope/pkg → "pkg") is a
    # package name, never a local symbol; pushing it only adds noise stubs.
    if "/" in normalized and not normalized.startswith("@"):
        _push(normalized.rsplit("/", 1)[-1])

    if "." in normalized:
        _push(normalized.rsplit(".", 1)[-1])

    return candidates


# ---------------------------------------------------------------------------
# ASTExtractor — base class for tree-sitter extractors
# ---------------------------------------------------------------------------


class ASTExtractor(abc.ABC):
    """
    Abstract base class for language-specific AST extractors.

    Subclasses implement :py:meth:`_query_source` to supply a tree-sitter
    SCM query string for their language.  The base class handles:

    - Parsing raw bytes via tree-sitter.
    - Grouping captures into definition / auxiliary buckets.
    - Instantiating frozen Pydantic Entity and Relationship models.
    - Emitting structured debug logs with parse timing metrics.

    Capture naming convention (SCM query side)::

        @def.function.name        — identifier node of a function definition
        @def.function.params      — parameter list node
        @def.function.return_type — return type annotation node
        @def.function.visibility  — visibility modifier (pub/public/private)
        @def.function.docstring   — docstring node
        @def.class.bases          — base class list (Python)
        @def.class.implements     — interface list (Java/TS)
        @def.class.extends        — superclass (Java)
        @ref.call                 — function call reference
        @ref.import               — import reference
    """

    def __init__(
        self, language: str, parsing_config: dict[str, Any] | None = None
    ) -> None:
        """
        Initialise the extractor for *language*.

        Args:
            language: Language identifier accepted by tree-sitter-language-pack
                      (e.g. "python", "typescript", "rust").
            parsing_config: Optional parsing configuration dict with keys:
                - error_recovery: bool (default True)
                - partial_parsing: bool (default False)
                - skip_comments: bool (default False)
        """
        self._language_name: str = language
        self._ts_parser = get_pooled_parser(language)
        self._ts_language: Language = get_language(language)  # type: ignore[arg-type]
        self._compiled_query: Query | None = None
        self._compile_failed: bool = False
        self._query_lock = threading.Lock()
        self._parsing_config: dict[str, Any] = parsing_config or {}
        self.logger = get_logger(__name__, operation="ast_extract").bind(
            language=language
        )

    def set_parsing_config(self, config: dict[str, Any]) -> None:
        """Update the parsing configuration for this extractor instance.

        Called by the registry when ``set_parsing_config()`` is invoked globally.
        This ensures the extractor picks up config changes (e.g.
        ``extract_parameters``, ``extract_type_parameters``) even if the
        instance was cached before the config was set.
        """
        self._parsing_config = config or {}

    def _get_compiled_query(self) -> Query | None:
        """Compile and cache the tree-sitter query once per extractor instance.

        Returns ``None`` when compilation has failed or the query is unavailable.
        Uses a flag to ensure a failed compilation is never retried.
        """
        # Fast path: already compiled (success) or already known to have failed.
        if self._compile_failed:
            return None
        if self._compiled_query is not None:
            return self._compiled_query

        with self._query_lock:
            # Re-check under the lock (another thread may have compiled).
            if self._compile_failed:
                return None
            if self._compiled_query is not None:
                return self._compiled_query

            try:
                self._compiled_query = Query(self._ts_language, self._query_source())
            except (TypeError, ValueError) as exc:
                self.logger.debug(
                    "query_compilation_failed",
                    error=str(exc),
                    language=getattr(self, '_language_name', 'unknown'),
                )
                # Set the flag so future calls skip the lock entirely.
                self._compile_failed = True
                return None
            return self._compiled_query

    # ------------------------------------------------------------------
    # Subclass contract
    # ------------------------------------------------------------------

    @abc.abstractmethod
    def _query_source(self) -> str:
        """
        Return the tree-sitter SCM query string for this language.

        The query must use the capture naming convention documented on the
        class docstring. At minimum it should capture ``@def.<type>.name``
        nodes for each symbol type of interest.
        """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def parse_file(
        self,
        filepath: str,
        content: bytes,
        index_id: str | None = None,
        include_gaps: bool = False,
        package: PackageMetadata | None = None,
    ) -> tuple[list[Entity], list[Relationship]]:
        """
        Parse *content* and return extracted entities and relationships.

        This method is fully exception-isolated: any internal error is caught,
        logged, and an empty result is returned so the caller can continue
        processing other files.
        """
        # Hook-provenance marks recorded by the per-file AST-alive stage
        # dispatch inside _build_relationships (T11/T16/T17). Reset per file —
        # id() keys are only valid for this parse's entity objects, and a
        # cache-hit path never calls parse_file, so a stale map must never
        # survive from the previous file this extractor instance saw.
        self._last_hook_marks: dict[int, set[str]] = {}

        t0 = time.perf_counter()

        # Check if error recovery is enabled
        error_recovery = self._parsing_config.get("error_recovery", True)

        # T34: ON_PRE_PARSE / ON_POST_PARSE stage dispatch — hooks observe the
        # file before parsing and the live tree after parsing (spec §4.1).
        # No-op unless a plugin registers for these stages; the shipped core
        # hooks do not.
        _plugin_host = None
        _parse_ctx = None
        try:
            from batho_plugin.runtime import get_active_plugin_host

            _plugin_host = get_active_plugin_host()
        except Exception:
            _plugin_host = None
        if _plugin_host is not None:
            try:
                from batho_plugin import PluginContext, Stage

                try:
                    from batho.core.config.loader import get_active_root

                    _root = get_active_root()
                except Exception:
                    _root = Path(filepath).parent
                _parse_ctx = PluginContext(
                    file_path=filepath,
                    root_path=_root,
                    language=self._language_name,
                    source_bytes=content,
                )
                _plugin_host.dispatch(Stage.ON_PRE_PARSE, _parse_ctx)
            except Exception as exc:
                self.logger.debug(
                    "plugin_pre_parse_failed", filepath=filepath, error=str(exc)
                )
                _parse_ctx = None

        try:
            tree = self._ts_parser.parse(content)
        except (TypeError, ValueError, RuntimeError) as exc:
            self.logger.warning(
                "parse_failed_triggering_fallback",
                filepath=filepath,
                error=str(exc),
            )
            
            from batho.modules.extraction.fallback_parser import FallbackParser
            fallback_parser = FallbackParser()
            fallback_result = fallback_parser.parse_file(Path(filepath), content)
            _stamp_fallback_language(fallback_result.entities, self._language_name)
            return fallback_result.entities, fallback_result.relationships

        # T34: the tree is alive — AST-stage plugins may inspect it now
        # (frozen ctx + live tree_root; process-local, never serialized).
        if _plugin_host is not None and _parse_ctx is not None:
            try:
                from dataclasses import replace as _dc_replace

                _plugin_host.dispatch(
                    Stage.ON_POST_PARSE,
                    _dc_replace(_parse_ctx, tree_root=tree.root_node),
                )
            except Exception as exc:
                self.logger.debug(
                    "plugin_post_parse_failed", filepath=filepath, error=str(exc)
                )

        # Check if we should skip comment nodes
        skip_comments = self._parsing_config.get("skip_comments", False)

        query = self._get_compiled_query()
        if query is None:
            self.logger.debug(
                "query_unavailable",
                filepath=filepath,
            )
            return [], []

        try:
            cursor = QueryCursor(query)
            raw_captures: dict[str, list[Node]] = cursor.captures(tree.root_node)

            if skip_comments:
                raw_captures = self._filter_comment_captures(raw_captures)

            entities, relationships = self._process_captures(
                raw_captures, content, filepath, index_id=index_id,
                package=package, root_node=tree.root_node,
            )
            entities = self._enrich_bidirectional_attributes(entities, content)
        except Exception as exc:
            self.logger.warning(
                "capture_processing_failed_triggering_fallback",
                filepath=filepath,
                error=str(exc),
            )
            from batho.modules.extraction.fallback_parser import FallbackParser
            fallback_parser = FallbackParser()
            fallback_result = fallback_parser.parse_file(Path(filepath), content)
            _stamp_fallback_language(fallback_result.entities, self._language_name)
            return fallback_result.entities, fallback_result.relationships

        if include_gaps:
            gap_entities = self._extract_gaps(content, filepath, entities)
            entities.extend(gap_entities)
            entities.sort(key=lambda e: e.start_byte)
        else:
            gap_entities = []

        parse_ms = round((time.perf_counter() - t0) * 1000, 2)
        self.logger.debug(
            "parse_file_complete",
            filepath=filepath,
            parse_ms=parse_ms,
            entity_count=len(entities),
            relationship_count=len(relationships),
            error_recovery=error_recovery,
            skip_comments=skip_comments,
            include_gaps=include_gaps,
            gap_count=len(gap_entities) if include_gaps else 0,
        )
        return entities, relationships

    def _filter_comment_captures(
        self, captures: dict[str, list[Node]]
    ) -> dict[str, list[Node]]:
        """
        Filter out comment-related captures when skip_comments is enabled.
        """
        filtered: dict[str, list[Node]] = {}
        for key, nodes in captures.items():
            filtered_nodes = [
                node
                for node in nodes
                if node.type
                not in {
                    "comment",
                    "line_comment",
                    "block_comment",
                    "doc_comment",
                    "docstring",
                }
            ]
            if filtered_nodes:
                filtered[key] = filtered_nodes
        return filtered

    # ------------------------------------------------------------------
    # Internal — capture processing
    # ------------------------------------------------------------------

    def _process_captures(
        self,
        captures: dict[str, list[Node]],
        source: bytes,
        filepath: str,
        index_id: str | None = None,
        package: PackageMetadata | None = None,
        root_node: Node | None = None,
    ) -> tuple[list[Entity], list[Relationship]]:
        """
        Group raw captures into entity definitions + auxiliary metadata,
        then build frozen Pydantic models.
        """
        definition_nodes: dict[str, list[Node]] = {}
        auxiliary_nodes: dict[tuple[str, str], list[Node]] = {}

        for cap_name, nodes in captures.items():
            parts = cap_name.split(".")
            if len(parts) == 3 and parts[0] == "def":
                base_key = f"{parts[0]}.{parts[1]}"
                suffix = parts[2]
                if suffix == "name":
                    definition_nodes.setdefault(base_key, []).extend(nodes)
                elif suffix in _META_SUFFIXES:
                    auxiliary_nodes.setdefault((base_key, suffix), []).extend(nodes)
            elif len(parts) == 2 and parts[0] in ("def", "ref"):
                definition_nodes.setdefault(cap_name, []).extend(nodes)

        entities, def_name_bytes = self._build_entities(
            definition_nodes, auxiliary_nodes, source, filepath, index_id=index_id, package=package
        )
        unresolved_entities, relationships = self._build_relationships(
            captures, entities, source, filepath, def_name_bytes,
            package=package, root_node=root_node,
        )
        entities.extend(unresolved_entities)
        return entities, relationships

    def _find_import_parent(self, node: Node) -> Node:
        curr = node.parent
        while curr:
            if "import" in curr.type or "include" in curr.type or curr.type in (
                "use_declaration", "namespace_use_clause", "import_spec",
                "preproc_include", "preproc_include_expression"
            ):
                return curr
            if curr.parent is None:
                return curr
            if curr.type in ("block", "source_file"):
                break
            curr = curr.parent
        return node.parent or node

    def _build_entities(
        self,
        definition_nodes: dict[str, list[Node]],
        auxiliary_nodes: dict[tuple[str, str], list[Node]],
        source: bytes,
        filepath: str,
        index_id: str | None = None,
        package: PackageMetadata | None = None,
    ) -> tuple[list[Entity], set[int]]:
        """Instantiate Entity models from grouped capture nodes.

        Returns:
            Tuple of (entities, def_name_bytes) where def_name_bytes is a set of
            byte offsets for definition name nodes (used to filter self-references).
        """
        entities: list[Entity] = []

        # LAZY source line decoding: Only decode when actually needed for docstring extraction.
        # This avoids O(n) memory allocation for large files (500KB+) when 99% of entities
        # already have docstrings from tree-sitter captures. (OPT-2A)
        _source_lines: list[str] | None = None

        def _get_source_lines() -> list[str]:
            nonlocal _source_lines
            if _source_lines is None:
                try:
                    _source_lines = source.decode("utf-8", errors="replace").splitlines()
                except Exception:
                    _source_lines = []
            return _source_lines

        # Local variable instead of instance attribute to prevent state leakage
        # between files when extractor is reused or when exceptions occur
        _def_name_bytes: set[int] = set()

        # 1. Collect flat list of all captured definitions with their node bounds
        # T02: Filter opt-in entity types based on config flags
        extract_parameters = self._parsing_config.get("extract_parameters", False)
        extract_type_parameters = self._parsing_config.get("extract_type_parameters", False)

        # T02/T03: Track name-node byte offsets for higher-priority captures to
        # deduplicate with method captures. Python __init__ is captured as both
        # def.method and def.constructor; @property methods as both def.method
        # and def.property. We prefer the more specific capture.
        higher_priority_name_bytes: set[int] = set()
        for dedup_key in ("def.constructor", "def.property"):
            if dedup_key in definition_nodes:
                for node in definition_nodes[dedup_key]:
                    higher_priority_name_bytes.add(node.start_byte)
        # Methods also match the block-anchored def.function catch-all (a class
        # body is a block); suppress the def.function duplicate when the same
        # name node was captured by any class-scoped def.* capture.
        method_scoped_name_bytes: set[int] = set(higher_priority_name_bytes)
        for dedup_key in ("def.method",):
            if dedup_key in definition_nodes:
                for node in definition_nodes[dedup_key]:
                    method_scoped_name_bytes.add(node.start_byte)

        flat_definitions = []
        # Same definition node captured by two query patterns (overlap
        # between anchored shapes) would mint duplicate entities; dedupe
        # per (base_key, name-node offset). Cross-key overlaps are handled
        # by the higher-priority filter above.
        seen_def_captures: set[tuple[str, int]] = set()
        for base_key, name_nodes in definition_nodes.items():
            entity_type = _CAPTURE_ENTITY_MAP.get(base_key)
            if entity_type is None:
                continue
            # T02: Skip opt-in types when disabled
            if entity_type == EntityType.PARAMETER and not extract_parameters:
                continue
            if entity_type == EntityType.TYPE_PARAMETER and not extract_type_parameters:
                continue
            for name_node in name_nodes:
                name = _node_text(name_node, source)
                if not name:
                    continue
                # T02/T03: Skip method captures that are also captured as
                # constructor or property (prefer the more specific type)
                if (
                    base_key == "def.method"
                    and name_node.start_byte in higher_priority_name_bytes
                ):
                    continue
                # Skip def.function captures of class members — the
                # class-scoped def.method/def.constructor/def.property
                # capture already claims this node.
                if (
                    base_key == "def.function"
                    and name_node.start_byte in method_scoped_name_bytes
                ):
                    continue
                if (base_key, name_node.start_byte) in seen_def_captures:
                    continue
                seen_def_captures.add((base_key, name_node.start_byte))
                _def_name_bytes.add(name_node.start_byte)
                decl_node = name_node.parent if name_node.parent is not None else name_node
                # T-fix (5c2e9b74): Kotlin classes, interfaces, and enum classes
                # all parse as class_declaration; the leading anonymous token
                # distinguishes them. Reclassify `interface X` to INTERFACE so
                # entity types are correct (the extractor's INTERFACE support —
                # scope-stack push, ENTITY_CATEGORIES — already exists).
                captured_type = entity_type
                if (
                    base_key == "def.class"
                    and entity_type == EntityType.CLASS
                    and self._language_name == "kotlin"
                ):
                    for child in decl_node.children:
                        if child.type == "modifiers":
                            continue
                        if child.type == "interface":
                            captured_type = EntityType.INTERFACE
                        break
                flat_definitions.append((
                    decl_node.start_byte,
                    -decl_node.end_byte,
                    base_key,
                    captured_type,
                    name,
                    name_node,
                    decl_node
                ))

        # 2. Sort definitions by start_byte ascending, end_byte descending to process outer scopes first
        flat_definitions.sort(key=lambda x: (x[0], x[1]))

        # 3. Process definitions using a monotonic stack to resolve nested scoping (FQN dot-notation)
        root_descriptors = _file_to_descriptors(filepath)

        scope_stack: list[tuple[int, str, list[tuple[str, DescriptorSuffix]]]] = []  # Stack of (end_byte, parent_fqn, parent_descriptors)
        for start_byte, neg_end_byte, base_key, entity_type, raw_name, name_node, decl_node in flat_definitions:
            end_byte = -neg_end_byte

            # Pop scopes that do not enclose the current definition node
            while scope_stack and scope_stack[-1][0] < start_byte:
                scope_stack.pop()

            # Append parent prefix if nested, else keep raw name
            if scope_stack:
                parent_fqn = scope_stack[-1][1]
                parent_descriptors = scope_stack[-1][2]
                fqn_name = f"{parent_fqn}.{raw_name}"
            else:
                parent_fqn = ""
                parent_descriptors = root_descriptors
                fqn_name = raw_name

            # Map entity_type to DescriptorSuffix
            if entity_type in (EntityType.CLASS, EntityType.STRUCT, EntityType.INTERFACE):
                current_suffix = DescriptorSuffix.TYPE
            elif entity_type in (EntityType.FUNCTION, EntityType.METHOD, EntityType.CONSTRUCTOR):
                current_suffix = DescriptorSuffix.METHOD
            elif entity_type in (EntityType.MODULE, EntityType.NAMESPACE):
                current_suffix = DescriptorSuffix.NAMESPACE
            elif entity_type in (EntityType.VARIABLE, EntityType.CONSTANT):
                current_suffix = DescriptorSuffix.TERM
            else:
                # T02: ENUM_MEMBER, PARAMETER, TYPE_PARAMETER, etc.
                current_suffix = DescriptorSuffix.TERM

            # For overloading or same-name scopes, optionally append short hash of params signature
            current_name = raw_name
            params_nodes = auxiliary_nodes.get((base_key, "params"), [])
            params_node = self._nearest_ancestor(params_nodes, decl_node)
            params_text = _node_text(params_node, source) if params_node else ""
            if params_text and params_text != "()":
                param_hash = hashlib.sha256(params_text.encode("utf-8")).hexdigest()[:6]
                fqn_name = f"{fqn_name}_[{param_hash}]"
                current_name = f"{raw_name}_[{param_hash}]"

            descriptors = parent_descriptors + [(current_name, current_suffix)]

            # Push current definition to scope stack if it can contain children
            # (e.g. Class, Module, Namespace, Struct, Enum, Interface, Trait).
            # T02 fix (b2e4d8f1): ENUM/INTERFACE/TRAIT must be pushed so members
            # get qualified FQNs (e.g. Color.Red) and unique entity IDs.
            # Functions/methods are pushed too: nested defs (closures like
            # `register_tools`' MCP tool closures) get parent-qualified FQNs,
            # which keeps same-named closures in one file from colliding on
            # one entity id.
            if entity_type in (
                EntityType.CLASS, EntityType.MODULE, EntityType.NAMESPACE,
                EntityType.STRUCT, EntityType.ENUM, EntityType.INTERFACE,
                EntityType.TRAIT, EntityType.FUNCTION, EntityType.METHOD,
                EntityType.CONSTRUCTOR,
            ):
                scope_stack.append((end_byte, fqn_name, descriptors))

            metadata = self._collect_metadata_with_source(
                base_key, decl_node, auxiliary_nodes, source, source_lines=_get_source_lines()
            )
            signature = self._build_signature(
                raw_name, base_key, decl_node, auxiliary_nodes, source
            )

            # T03: Detect property setter (decorator with .setter attribute)
            # and mark with access_type="write". Default for @property is "read".
            if entity_type == EntityType.PROPERTY:
                # T17: access_type via the plugin hook when a host is active
                # (byte-identical to the inline fallback below — parity in
                # tests/sdk/test_hooks.py, incl. real tree-sitter trees).
                try:
                    from batho_plugin.runtime import get_active_plugin_host

                    _host = get_active_plugin_host()
                except Exception:
                    _host = None
                if _host is not None:
                    from batho_plugin.hooks import infer_access_type

                    _accessor_nodes = auxiliary_nodes.get((base_key, "accessor"), [])
                    _acc_node = self._nearest_ancestor(_accessor_nodes, decl_node)
                    _accessor_text = (
                        _node_text(_acc_node, source).strip()
                        if _acc_node is not None
                        else None
                    )
                    metadata["access_type"] = infer_access_type(
                        decl_node,
                        source,
                        self._language_name,
                        accessor_text=_accessor_text,
                    )
                    # T17: transient hints consumed by the dispatched
                    # ON_PROPERTY_CLASSIFY hook in _build_relationships (writes
                    # the identical value + records the bsg.hooks mark).
                    # Stripped there whether or not dispatch ran.
                    metadata["_decl_node"] = decl_node
                    if _accessor_text is not None:
                        metadata["_accessor_text"] = _accessor_text
                else:
                    parent = decl_node.parent
                    if parent is not None and parent.type == "decorated_definition":
                        for child in parent.children:
                            if child.type == "decorator":
                                decorator_text = _node_text(child, source)
                                if ".setter" in decorator_text:
                                    metadata["access_type"] = "write"
                                    break
                    if "access_type" not in metadata:
                        # T03 fix (c3f5a7b9): TS get/set accessors — the captured
                        # "get"/"set" keyword is in auxiliary_nodes as "accessor".
                        accessor_nodes = auxiliary_nodes.get((base_key, "accessor"), [])
                        accessor_node = self._nearest_ancestor(accessor_nodes, decl_node)
                        if accessor_node is not None:
                            accessor_text = _node_text(accessor_node, source).strip()
                            if accessor_text == "set":
                                metadata["access_type"] = "write"
                    if "access_type" not in metadata:
                        # C# fix (c3f5a7b9): inspect accessor_list for a "set" accessor.
                        if self._language_name == "csharp" and decl_node.parent is not None:
                            for child in decl_node.parent.children:
                                if child.type == "accessor_list":
                                    for acc in child.children:
                                        if acc.type == "accessor_declaration":
                                            acc_text = _node_text(acc, source)
                                            if acc_text.startswith("set"):
                                                metadata["access_type"] = "write"
                                                break
                                    break
                    if "access_type" not in metadata:
                        # T03 (Kotlin): property_declaration's binding_pattern_kind
                        # holds the val/var keyword — var is mutable (write).
                        if self._language_name == "kotlin" and decl_node.parent is not None:
                            for child in decl_node.parent.children:
                                if child.type == "binding_pattern_kind":
                                    if _node_text(child, source).strip() == "var":
                                        metadata["access_type"] = "write"
                                    break
                    if "access_type" not in metadata:
                        metadata["access_type"] = "read"

            metadata["is_exported"] = True
            if index_id:
                metadata["bsg.index_id"] = index_id

            normalized_name = fqn_name
            if entity_type == EntityType.ENTRY_POINT:
                raw_snippet_value = metadata.get("invocation_snippet")
                raw_snippet = (
                    str(raw_snippet_value)
                    if isinstance(raw_snippet_value, str)
                    and raw_snippet_value.strip()
                    else raw_name
                )
                if (
                    "__name__" in raw_snippet and "__main__" in raw_snippet
                ) or raw_name == "__name__":
                    normalized_name = "__main__"
                    metadata["invocation_snippet"] = raw_snippet

            # Decode with strict UTF-8, storing raw_bytes on error
            raw_bytes_slice = source[decl_node.start_byte:decl_node.end_byte]
            decoded_content, stored_raw_bytes = self._safe_decode(
                raw_bytes_slice, filepath, context=f"entity {normalized_name}"
            )

            encl_start, encl_end = self._get_enclosing_range(decl_node, entity_type)
            symbol_id = generate_hierarchical_id(package, descriptors)

            entity = Entity(
                type=entity_type,
                name=normalized_name,
                file=filepath,
                start_line=decl_node.start_point[0] + 1,
                end_line=decl_node.end_point[0] + 1,
                start_byte=decl_node.start_byte,
                end_byte=decl_node.end_byte,
                enclosing_start_byte=encl_start,
                enclosing_end_byte=encl_end,
                signature=signature,
                metadata=metadata,
                raw_content=decoded_content,
                content_hash=compute_bytes_hash(raw_bytes_slice),
                raw_bytes=stored_raw_bytes,
                ast_node_type=decl_node.type,
                id_override=symbol_id,
            )
            entities.append(entity)

            # Extract docstring as a first-class COMMENT_BLOCK entity
            doc_nodes = auxiliary_nodes.get((base_key, "docstring"), [])
            doc_node = self._nearest_ancestor(doc_nodes, decl_node)
            if doc_node is not None:
                doc_bytes_slice = source[doc_node.start_byte:doc_node.end_byte]
                decoded_doc, stored_doc_bytes = self._safe_decode(
                    doc_bytes_slice, filepath, context=f"docstring of {normalized_name}"
                )
                doc_entity = Entity(
                    type=EntityType.COMMENT_BLOCK,
                    name=f"{normalized_name}::docstring",
                    file=filepath,
                    start_line=doc_node.start_point[0] + 1,
                    end_line=doc_node.end_point[0] + 1,
                    start_byte=doc_node.start_byte,
                    end_byte=doc_node.end_byte,
                    enclosing_start_byte=doc_node.start_byte,
                    enclosing_end_byte=doc_node.end_byte,
                    signature=None,
                    metadata={
                        "is_docstring": True,
                        "rationale_kind": "docstring",
                        "language": self._language_name,
                    },
                    raw_content=decoded_doc,
                    content_hash=compute_bytes_hash(doc_bytes_slice),
                    raw_bytes=stored_doc_bytes,
                    ast_node_type=doc_node.type,
                    is_documentation=True,
                    parent_id=entity.id,
                )
                entities.append(doc_entity)

        entities.sort(key=lambda e: e.start_byte)
        return entities, _def_name_bytes

    def _get_enclosing_range(
        self, decl_node: Node, entity_type: EntityType
    ) -> tuple[int, int]:
        """Compute the enclosing range for a declaration node."""
        start = decl_node.start_byte
        end = decl_node.end_byte

        # For functions and classes, check if there is a decorator / decorated_definition parent
        if entity_type in (EntityType.FUNCTION, EntityType.METHOD, EntityType.CLASS):
            curr = decl_node.parent
            if curr and curr.type == "decorated_definition":
                start = curr.start_byte
                end = curr.end_byte

        # For variables, find the nearest enclosing block or statement list
        elif entity_type == EntityType.VARIABLE:
            curr = decl_node.parent
            while curr:
                if curr.type in (
                    "block",
                    "statement_block",
                    "compound_statement",
                    "function_definition",
                    "class_definition",
                ):
                    start = curr.start_byte
                    end = curr.end_byte
                    break
                curr = curr.parent

        return start, end

    def _build_relationships(
        self,
        captures: dict[str, list[Node]],
        entities: list[Entity],
        source: bytes,
        filepath: str,
        def_name_bytes: set[int],
        package: PackageMetadata | None = None,
        root_node: Node | None = None,
    ) -> tuple[list[Entity], list[Relationship]]:
        """Build Relationship models from reference captures.

        Args:
            captures: Dictionary of capture names to tree-sitter nodes
            entities: List of entities built from definitions
            source: Raw source bytes
            filepath: Path to the file being processed
            def_name_bytes: Set of byte offsets for definition names (to filter self-refs)
            package: Optional package metadata

        Returns:
            Tuple of (unresolved_entities, relationships)
        """
        relationships: list[Relationship] = []
        unresolved_entities: list[Entity] = []
        emitted: set[tuple[str, str, str, int, int, int]] = set()
        unresolved_emitted: set[str] = set()

        # Compute timestamp once per _build_relationships call rather than per
        # unresolved entity.
        now_ts = datetime.now(timezone.utc).isoformat()

        # Cache config lookup once per file to avoid O(n) config calls in hot loop (OPT-2C)
        from batho.core.config import get_config_cached
        try:
            cfg = get_config_cached()
            prune_enabled = cfg.get("bsg", {}).get("symbol_resolution", {}).get("prune_unresolved", True)
        except Exception:
            prune_enabled = True

        def _make_contextual_stub(
            ref_text: str, line: int, rel_type: RelationshipType, caller_scope: str
        ) -> Entity:
            # The ref key is dot-normalized (_stub_ref_key) so the "::" scope
            # separator stays unambiguous for Rust/Ruby scoped ref text;
            # name/target_name/receiver_var keep the caller-written spelling.
            # The occurrence line sits in the scope half (never in the ref
            # half — rsplit("::",1)[-1] must stay the clean ref key): stub
            # identity is per CALL SITE so position-aware binding sees each
            # occurrence's own start_line instead of the first occurrence's.
            stub_id = f"unresolved:{caller_scope}@{line}::{_stub_ref_key(ref_text)}"
            # Extract the full receiver chain: "self.db.execute" -> "self.db".
            # Storing only the first segment (`self`) types the call by the
            # enclosing class and fabricates `Enclosing.execute`-style edges —
            # the deep-receiver guard needs the real chain (`self.db`).
            receiver_var = ".".join(ref_text.split(".")[:-1]) if "." in ref_text else None
            meta: dict[str, Any] = {
                "reference_type": rel_type.name.lower(),
                "resolution_reason": "contextual_stub",
                "created_at": now_ts,
                "is_visible": False,
                "stub_resolution_state": "pending",
                "caller_scope": caller_scope,
                "target_name": ref_text,
                "receiver_var": receiver_var,
            }
            return Entity(
                # T13: stubs are EXTERNAL_SYMBOL entities (UNRESOLVED is
                # deprecated); the "unresolved:" ID prefix keeps
                # is_contextual_stub working for resolution and pruning.
                type=EntityType.EXTERNAL_SYMBOL,
                name=ref_text,
                file=filepath,
                start_line=line,
                end_line=line,
                metadata=meta,
                id_override=stub_id,
            )

        def _add(
            src_id: str,
            tgt_id: str,
            rel_type: RelationshipType,
            line: int,
            extra_metadata: dict[str, Any] | None = None,
            *,
            reference_start_byte: int | None = None,
            reference_end_byte: int | None = None,
            definition_start_byte: int | None = None,
            definition_end_byte: int | None = None,
            roles: SymbolRole | int | None = None,
            confidence: float = 1.0,
        ) -> None:
            ref_start_key = reference_start_byte if reference_start_byte is not None else -1
            ref_end_key = reference_end_byte if reference_end_byte is not None else -1
            key = (src_id, tgt_id, str(rel_type), ref_start_key, ref_end_key, line)
            if key not in emitted:
                emitted.add(key)
                metadata = {"line_number": line}
                if extra_metadata:
                    metadata.update(extra_metadata)
                relationships.append(
                    Relationship(
                        source_id=src_id,
                        target_id=tgt_id,
                        type=rel_type,
                        roles=SymbolRole(roles) if roles is not None else SymbolRole(0),
                        reference_start_byte=reference_start_byte,
                        reference_end_byte=reference_end_byte,
                        definition_start_byte=definition_start_byte,
                        definition_end_byte=definition_end_byte,
                        metadata=metadata,
                        confidence=confidence,
                    )
                )

        # T5 rationale layer: marker comments (`# WHY:`, `// NOTE:`, `/* */`)
        # become first-class COMMENT_BLOCK entities so they can carry
        # RATIONALE_FOR edges. Merged before the CONTAINS pass so they nest
        # inside their enclosing symbol like docstring entities do.
        # Honors bsg.parsing.skip_comments — markers are comments, so the
        # opt-out suppresses them too.
        marker_entities = (
            []
            if self._parsing_config.get("skip_comments", False)
            else self._extract_marker_comment_entities(
                source, filepath, root_node=root_node
            )
        )
        if marker_entities:
            entities.extend(marker_entities)
            entities.sort(key=lambda e: e.start_byte)

        # T11/T16/T17: per-file AST-alive stage dispatch — ON_COMMENT_CLASSIFY
        # then ON_PROPERTY_CLASSIFY in canonical order. This runs here (not in
        # the worker loop) because the tree is only alive on this stack: the
        # hooks consume transient hints (_marker_text / _decl_node /
        # _accessor_text) that carry live Node objects. The final inline
        # values are already written at the production sites, so a skipped or
        # failed dispatch degrades to correct metadata minus provenance marks;
        # the finally strip guarantees the hints never reach serialization.
        try:
            from batho_plugin import PluginContext, Stage
            from batho_plugin.runtime import get_active_plugin_host

            _stage_host = get_active_plugin_host()
            _stage_needed = _stage_host is not None and (
                _stage_host.has_stage_hooks(Stage.ON_COMMENT_CLASSIFY)
                or _stage_host.has_stage_hooks(Stage.ON_PROPERTY_CLASSIFY)
            )
        except Exception:
            _stage_host = None
            _stage_needed = False
        if _stage_host is not None:
            try:
                if _stage_needed:
                    from batho.core.config.loader import get_active_root

                    _file_ctx = PluginContext(
                        file_path=filepath,
                        root_path=get_active_root(),
                        language=self._language_name,
                        source_bytes=source,
                        tree_root=root_node,
                        entities=entities,
                    )
                    _stage_host.dispatch(Stage.ON_COMMENT_CLASSIFY, _file_ctx)
                    _stage_host.dispatch(Stage.ON_PROPERTY_CLASSIFY, _file_ctx)
                    self._last_hook_marks = _file_ctx.hook_marks
            except Exception as exc:
                self.logger.warning(
                    "plugin_file_classify_failed", filepath=filepath, error=str(exc)
                )
            finally:
                # Runs for ANY active host — the production sites attach hints
                # whenever a host exists, independent of which hooks it holds.
                for _ent in entities:
                    _meta = getattr(_ent, "metadata", None)
                    if isinstance(_meta, dict):
                        for _hint in ("_marker_text", "_decl_node", "_accessor_text"):
                            _meta.pop(_hint, None)

        # Extract file imports for local resolution support
        file_imports = []
        parent_to_nodes = {}
        for cap_name, nodes in captures.items():
            if cap_name.startswith("ref.import"):
                for node in nodes:
                    parent = self._find_import_parent(node)
                    parent_to_nodes.setdefault(parent, []).append((cap_name, node))
        for parent, cap_nodes in parent_to_nodes.items():
            modules = []
            symbols_list = []
            for cap_name, node in cap_nodes:
                text = _node_text(node, source)
                if not text:
                    continue
                if "module" in cap_name or "require" in cap_name or "load" in cap_name:
                    modules.append(text)
                elif "symbol" in cap_name or "static" in cap_name:
                    symbols_list.append(text)
            if not modules:
                module_path = _normalize_import_target(_node_text(parent, source))
            else:
                module_path = _normalize_import_target(modules[0])
            is_from_import = len(symbols_list) > 0 or "from" in _node_text(parent, source).lower()
            file_imports.append((module_path, symbols_list, is_from_import))

        # CONTAINS: parent entity → child entity
        parent_stack: list[Entity] = []
        for child in entities:
            # Pop any entries that cannot contain this child.
            while parent_stack and parent_stack[-1].end_byte < child.start_byte:
                parent_stack.pop()
            if parent_stack and parent_stack[-1].id != child.id:
                parent = parent_stack[-1]
                _add(
                    parent.id,
                    child.id,
                    RelationshipType.CONTAINS,
                    child.start_line,
                    definition_start_byte=child.start_byte,
                    definition_end_byte=child.end_byte,
                )
            # Only push if this entity can contain future entities.
            # Pop until we find an ancestor that properly contains this child.
            while parent_stack and not (
                parent_stack[-1].start_byte <= child.start_byte
                and child.end_byte <= parent_stack[-1].end_byte
            ):
                parent_stack.pop()
            parent_stack.append(child)

        by_name: dict[str, Entity] = {e.name: e for e in entities}
        by_id: dict[str, Entity] = {e.id: e for e in entities}

        # T10 fix (a1f3c9e2): Secondary lookup keyed on the un-suffixed raw name.
        # `by_name` keys are hash-suffixed FQNs (e.g. "func_[ec84ac]"), so a bare
        # identifier like `func` never matches. For indirect_call detection we
        # need to resolve bare identifiers to their defining function/method.
        # T10 fix (e66a376d): same-named callables are stored as a list and
        # disambiguated by caller scope at lookup time — first-wins could
        # resolve an indirect call to the wrong class's method.
        _CALLABLE_TYPES = frozenset({
            EntityType.FUNCTION, EntityType.METHOD,
            EntityType.CONSTRUCTOR, EntityType.PROPERTY,
        })
        by_raw_name: dict[str, list[Entity]] = {}
        for e in entities:
            if e.type in _CALLABLE_TYPES:
                raw = e.name.split("_[")[0].rsplit(".", 1)[-1]
                if raw:
                    by_raw_name.setdefault(raw, []).append(e)
        # Sort entities by start_byte for O(log N) enclosing lookup via bisect.
        sorted_ents = sorted(entities, key=lambda e: e.start_byte)
        sorted_starts = [e.start_byte for e in sorted_ents]

        def _find_enclosing(byte_offset: int) -> Entity | None:
            """Find the smallest entity enclosing the given byte offset using bisect.
            
            Time complexity: O(log N) for bisect + O(k) for walking back,
            where k is small (usually 1-2) since nested scopes are limited.
            """
            # Find the rightmost entity with start_byte <= byte_offset
            idx = bisect.bisect_right(sorted_starts, byte_offset) - 1
            if idx < 0:
                return None
            
            # Walk backwards to find the smallest enclosing entity
            best: Entity | None = None
            while idx >= 0:
                ent = sorted_ents[idx]
                if ent.start_byte <= byte_offset <= ent.end_byte:
                    if best is None or (
                        ent.end_byte - ent.start_byte < best.end_byte - best.start_byte
                    ):
                        best = ent
                        # Keep looking for a smaller (more specific) enclosing entity
                # If this entity starts before our best candidate, stop searching
                if best and ent.start_byte < best.start_byte:
                    break
                idx -= 1
            return best

        # ───────────────────────────────────────────────────────────────────
        # T10: Shadowing soundness guard for indirect calls.
        # `pool.submit(handler)` must NOT emit a CALLS edge when `handler`
        # is a parameter or a local variable of the enclosing function that
        # shadows a module-level function of the same name.
        # ───────────────────────────────────────────────────────────────────
        # 1) Local names: identifiers assigned (ref.write) within a callable's
        #    byte range. Reuses existing ref.write captures + _find_enclosing.
        locals_by_function: dict[str, set[str]] = {}
        for w_node in captures.get("ref.write", []):
            w_name = _node_text(w_node, source)
            if not w_name:
                continue
            w_enc = _find_enclosing(w_node.start_byte)
            if w_enc is not None and w_enc.type in _CALLABLE_TYPES:
                locals_by_function.setdefault(w_enc.id, set()).add(w_name)

        # 2) Parameter names: walk up from the reference node to the enclosing
        #    function-like node and collect identifier descendants of its
        #    parameter list, excluding type-annotation subtrees (so Python
        #    `def f(x: Handler)` and TS `function f(x: FnType)` do not leak
        #    annotation names into the shadow set).
        _FUNCTION_NODE_TYPES = frozenset({
            "function_definition",    # Python
            "function_declaration",   # JS/TS/Kotlin/Go
            "function_item",          # Rust
            "method_definition",      # JS/TS
            "method_declaration",     # Java/C#
            "constructor_declaration",  # Java/C#
            "arrow_function",         # JS/TS
        })
        _TYPE_SUBTREE_TYPES = frozenset({"type", "type_annotation"})

        def _enclosing_function_params(node: Node) -> set[str]:
            cur = node.parent
            while cur is not None and cur.type not in _FUNCTION_NODE_TYPES:
                cur = cur.parent
            if cur is None:
                return set()
            params = cur.child_by_field_name("parameters")
            if params is None:
                return set()
            names: set[str] = set()
            stack: list[Node] = [params]
            while stack:
                n = stack.pop()
                if n.type in _TYPE_SUBTREE_TYPES:
                    continue
                if n.type == "identifier":
                    n_text = _node_text(n, source)
                    if n_text:
                        names.add(n_text)
                stack.extend(n.children)
            return names

        def _resolve_raw_callable(ref_text: str, node: Node) -> Entity | None:
            """Resolve a bare identifier to a callable via the raw-name index.

            Same-named callables (e.g. two classes both defining `validate`)
            are disambiguated by scope: a candidate only matches when its FQN
            scope prefix is a prefix of the caller's FQN, and the most specific
            (longest) matching prefix must be unique. Otherwise the name is
            ambiguous and no edge is emitted — first-wins could produce a
            plausible-but-incorrect CALLS edge (e66a376d).
            """
            candidates = by_raw_name.get(ref_text)
            if not candidates:
                return None
            if len(candidates) == 1:
                return candidates[0]
            caller = _find_enclosing(node.start_byte)
            if caller is None:
                return None
            caller_segs = caller.name.split("_[")[0].split(".")
            scoped: list[tuple[int, Entity]] = []
            for cand in candidates:
                cand_segs = cand.name.split("_[")[0].split(".")
                scope = cand_segs[:-1]
                if len(scope) < len(caller_segs) and caller_segs[: len(scope)] == scope:
                    scoped.append((len(scope), cand))
            if not scoped:
                return None
            best_len = max(s for s, _ in scoped)
            best = [e for s, e in scoped if s == best_len]
            return best[0] if len(best) == 1 else None

        # ───────────────────────────────────────────────────────────────────
        # CONTAINS synthesis: link methods to their struct/enum/trait types
        # via ref.impl_type (Rust) or ref.receiver_type (Go) captures.
        # These types and methods are disjoint AST nodes — the byte-range
        # CONTAINS logic above cannot detect the relationship.
        # ───────────────────────────────────────────────────────────────────
        _CONTAINS_TYPE_ENTITIES = frozenset({
            EntityType.STRUCT, EntityType.ENUM, EntityType.TRAIT,
            EntityType.INTERFACE, EntityType.CLASS,
        })
        for cap_name, nodes in captures.items():
            if cap_name not in _CONTAINS_HINT_CAPTURES:
                continue
            for node in nodes:
                type_name = _node_text(node, source)
                if not type_name:
                    continue
                type_ent = by_name.get(type_name)
                if type_ent is None or type_ent.type not in _CONTAINS_TYPE_ENTITIES:
                    continue

                if cap_name == "ref.impl_type":
                    # Rust: the type_identifier is in the impl_item header,
                    # not inside any method. Find all METHOD entities within
                    # the impl block's byte range (node.parent = impl_item).
                    impl_node = node.parent
                    if impl_node is None:
                        continue
                    impl_start = impl_node.start_byte
                    impl_end = impl_node.end_byte
                    # FIX 9: use bisect_left on the pre-sorted sorted_starts list
                    # to find the first method whose start_byte >= impl_start,
                    # then forward-scan while start_byte <= impl_end.
                    # This reduces the per-impl scan from O(M) to O(log M + k)
                    # where k is the number of methods in the impl block.
                    lo = bisect.bisect_left(sorted_starts, impl_start)
                    for idx in range(lo, len(sorted_ents)):
                        method_ent = sorted_ents[idx]
                        if method_ent.start_byte > impl_end:
                            break
                        if method_ent.type != EntityType.METHOD:
                            continue
                        if method_ent.id == type_ent.id:
                            continue
                        if method_ent.end_byte <= impl_end:
                            _add(
                                type_ent.id,
                                method_ent.id,
                                RelationshipType.CONTAINS,
                                method_ent.start_line,
                                extra_metadata={"synthesized": True, "capture": "ref.impl_type"},
                                definition_start_byte=method_ent.start_byte,
                                definition_end_byte=method_ent.end_byte,
                            )
                else:
                    # Go: the type_identifier is inside the method_declaration's
                    # receiver, so _find_enclosing will locate the method entity.
                    method_ent = _find_enclosing(node.start_byte)
                    if method_ent is None or method_ent.type != EntityType.METHOD:
                        continue
                    if method_ent.id == type_ent.id:
                        continue
                    _add(
                        type_ent.id,
                        method_ent.id,
                        RelationshipType.CONTAINS,
                        method_ent.start_line,
                        extra_metadata={"synthesized": True, "capture": "ref.receiver_type"},
                        definition_start_byte=method_ent.start_byte,
                        definition_end_byte=method_ent.end_byte,
                    )

        # FIX 10: Precompute per-file import lookup structures once instead of
        # scanning file_imports O(I) times per reference node.
        #
        # from_symbol_to_module: symbol -> module_path for from-imports.
        #   setdefault preserves first-match semantics (mirrors original for..break).
        # non_from_modules: list of plain module_paths for prefix matching.
        #   MUST remain a list + startswith check — a set membership test would
        #   miss "os.path" matched against "import os".
        # imported_names: set of all module_paths and from-import symbols for
        #   O(1) membership in _should_prune_unresolved (rule 4).
        from_symbol_to_module: dict[str, str] = {}
        non_from_modules: list[str] = []
        imported_names: set[str] = set()
        for _mp, _syms, _is_from in file_imports:
            imported_names.add(_mp)
            if _is_from:
                for _sym in _syms:
                    from_symbol_to_module.setdefault(_sym, _mp)
                    imported_names.add(_sym)
            else:
                non_from_modules.append(_mp)

        for cap_name, nodes in captures.items():
            rel_type, capture_variant = _relationship_capture_info(cap_name)
            if rel_type is None:
                continue
            if rel_type == RelationshipType.CONTAINS:
                continue

            for node in nodes:
                if node.start_byte in def_name_bytes:
                    continue
                ref_text = _node_text(node, source)
                if not ref_text:
                    continue

                line_no = node.start_point[0] + 1

                rel_meta = {"capture": cap_name}
                if capture_variant:
                    rel_meta["capture_variant"] = capture_variant

                # T10: Indirect call metadata
                if cap_name.startswith("ref.indirect_call"):
                    rel_meta["indirect"] = True
                # T11: Dynamic import metadata
                elif cap_name.startswith("ref.dynamic_import"):
                    rel_meta["dynamic"] = True
                # T12: Re-export metadata. The captured node is the module
                # `string`; its parent export_statement distinguishes the
                # variants: `export * from` (re_export_all), TS
                # `export type {..} from` (re_export_type), and the exported
                # symbol names from the export_clause (re_exported_symbols).
                elif cap_name.startswith("ref.re_export"):
                    rel_meta["re_export"] = True
                    export_stmt = node.parent
                    if export_stmt is not None and export_stmt.type == "export_statement":
                        child_types = [c.type for c in export_stmt.children]
                        if "*" in child_types:
                            rel_meta["re_export_all"] = True
                        if "type" in child_types:
                            rel_meta["re_export_type"] = True
                        clause = next(
                            (c for c in export_stmt.children if c.type == "export_clause"),
                            None,
                        )
                        if clause is not None:
                            symbols = []
                            for spec in clause.children:
                                if spec.type != "export_specifier":
                                    continue
                                name_node = spec.child_by_field_name("name")
                                if name_node is not None:
                                    sym = _node_text(name_node, source)
                                    if sym:
                                        symbols.append(sym)
                            if symbols:
                                rel_meta["re_exported_symbols"] = symbols

                role = self._determine_symbol_role(cap_name, node)
                if role == SymbolRole(0):
                    continue

                # T10: Indirect calls have lower confidence (0.7)
                # T11/T12: Dynamic imports and re-exports have confidence 1.0 (explicit in source)
                edge_confidence = 1.0
                if cap_name.startswith("ref.indirect_call"):
                    edge_confidence = 0.7

                if rel_type in (
                    RelationshipType.CALLS,
                    RelationshipType.USES,
                    RelationshipType.REFERENCES,
                    RelationshipType.READS,
                    RelationshipType.WRITES,
                ):
                    source_ent = _find_enclosing(node.start_byte)
                    if source_ent is None:
                        continue
                    source_id = source_ent.id

                    # T1 receiver capture: for attribute calls like
                    # ``svc.get_entity()`` the ref node is the bare attribute
                    # identifier; the receiver object lives on the parent
                    # attribute node. Qualifying the ref key with the receiver
                    # (``svc.get_entity``) keeps distinct receivers from
                    # collapsing into one stub and seeds receiver-type
                    # resolution downstream.
                    receiver_txt = None
                    if rel_type == RelationshipType.CALLS:
                        receiver_txt = _receiver_object_text(node, source)
                        bound_to, inner_callee = _assigned_binding(node, source)
                        if bound_to:
                            rel_meta["assigned_to"] = bound_to
                        if inner_callee:
                            rel_meta["assigned_inner"] = inner_callee

                    target_id = None
                    target_ent = by_name.get(ref_text) if receiver_txt is None else None
                    if target_ent is not None:
                        target_id = target_ent.id

                    # T10: Soundness guard for indirect calls — only emit if the
                    # target resolves to a known FUNCTION or METHOD (not a variable,
                    # parameter, etc.). `by_name` keys are hash-suffixed FQNs, so a
                    # bare identifier needs the raw-name lookup (a1f3c9e2).
                    if cap_name.startswith("ref.indirect_call"):
                        if target_ent is None:
                            target_ent = _resolve_raw_callable(ref_text, node)
                            if target_ent is not None:
                                target_id = target_ent.id
                        if target_ent is None:
                            continue
                        if target_ent.type not in _CALLABLE_TYPES:
                            continue
                        # T10 soundness: the identifier is shadowed by a
                        # parameter or local variable of the enclosing
                        # function — the runtime call would hit the shadow,
                        # not the module-level function. Do NOT emit.
                        if ref_text in locals_by_function.get(source_id, ()):
                            continue
                        if ref_text in _enclosing_function_params(node):
                            continue

                    ref_to_use = ref_text
                    if target_id is None:
                        if receiver_txt is not None:
                            # T1: receiver-qualified ref key — `svc.get_entity`
                            # keeps receiver context for member resolution.
                            ref_to_use = f"{receiver_txt}.{ref_text}"
                        else:
                            # FIX 10: use precomputed from_symbol_to_module (O(1))
                            # and non_from_modules list (O(I) but only for prefix
                            # matching — cannot replace with set membership).
                            mp = from_symbol_to_module.get(ref_text)
                            if mp is not None:
                                ref_to_use = f"{mp}.{ref_text}"
                            else:
                                for mp in non_from_modules:
                                    if ref_text == mp or ref_text.startswith(mp + ".") or ref_text.startswith(mp + "/"):
                                        ref_to_use = ref_text
                                        break

                    target_ent = by_id.get(target_id) if target_id else None

                    if target_id is not None and source_id != target_id:
                        _add(
                            source_id,
                            target_id,
                            rel_type,
                            line_no,
                            rel_meta,
                            reference_start_byte=node.start_byte,
                            reference_end_byte=node.end_byte,
                            definition_start_byte=target_ent.start_byte,
                            definition_end_byte=target_ent.end_byte,
                            roles=role,
                            confidence=edge_confidence,
                        )
                    elif target_id is None:
                        if not _prune_unresolved(ref_to_use, rel_type, file_imports, self._language_name, filepath, prune_enabled, imported_names):
                            unres = _make_contextual_stub(ref_to_use, line_no, rel_type, caller_scope=source_id)
                            if unres.id not in unresolved_emitted:
                                unresolved_emitted.add(unres.id)
                                unresolved_entities.append(unres)
                            _add(
                                source_id,
                                unres.id,
                                rel_type,
                                line_no,
                                rel_meta,
                                reference_start_byte=node.start_byte,
                                reference_end_byte=node.end_byte,
                                roles=role,
                            )

                elif rel_type == RelationshipType.IMPORTS:
                    source_ent = _find_enclosing(node.start_byte)
                    if source_ent is None:
                        # T11/T12 (b8c0d2e4): For top-level dynamic imports and
                        # re-exports, prefer a MODULE/NAMESPACE entity as the
                        # source; fall back to the first entity only if none exists.
                        if cap_name.startswith("ref.dynamic_import") or cap_name.startswith("ref.re_export"):
                            source_ent = next(
                                (e for e in sorted_ents if e.type in (EntityType.MODULE, EntityType.NAMESPACE)),
                                sorted_ents[0] if sorted_ents else None,
                            )
                            if source_ent is None:
                                continue
                        else:
                            continue
                    source_id = source_ent.id
                    targets = _expand_import_targets(ref_text)
                    if not targets:
                        continue

                    # T11/T12: Add import_path to metadata for dynamic imports and re-exports
                    if cap_name.startswith("ref.dynamic_import") or cap_name.startswith("ref.re_export"):
                        rel_meta["import_path"] = _normalize_import_target(ref_text)

                    for target_ref in targets:
                        target_id = None
                        target_ent = by_name.get(target_ref)
                        if target_ent is not None:
                            target_id = target_ent.id

                        target_ent = by_id.get(target_id) if target_id else None

                        if target_id is not None and source_id != target_id:
                            _add(
                                source_id,
                                target_id,
                                rel_type,
                                line_no,
                                rel_meta,
                                reference_start_byte=node.start_byte,
                                reference_end_byte=node.end_byte,
                                definition_start_byte=target_ent.start_byte,
                                definition_end_byte=target_ent.end_byte,
                                roles=role,
                                confidence=1.0,
                            )
                        elif target_id is None:
                            if not _prune_unresolved(target_ref, rel_type, file_imports, self._language_name, filepath, prune_enabled, imported_names):
                                unres = _make_contextual_stub(target_ref, line_no, rel_type, caller_scope=source_id)
                                if unres.id not in unresolved_emitted:
                                    unresolved_emitted.add(unres.id)
                                    unresolved_entities.append(unres)
                                _add(
                                    source_id,
                                    unres.id,
                                    rel_type,
                                    line_no,
                                    rel_meta,
                                    reference_start_byte=node.start_byte,
                                    reference_end_byte=node.end_byte,
                                    roles=role,
                                )

                elif rel_type in (
                    RelationshipType.INHERITS,
                    RelationshipType.IMPLEMENTS,
                ):
                    source_ent = _find_enclosing(node.start_byte)
                    if source_ent is None:
                        continue

                    normalized_ref = None
                    target_id = None
                    target_ent = by_name.get(ref_text)
                    if target_ent is not None:
                        target_id = target_ent.id

                    if target_id is None:
                        normalized_ref = _normalize_import_target(ref_text)
                        if normalized_ref:
                            target_ent = by_name.get(normalized_ref)
                            if target_ent is not None:
                                target_id = target_ent.id

                    ref_to_use = normalized_ref if normalized_ref else ref_text
                    if target_id is None:
                        # FIX 10: use precomputed from_symbol_to_module (O(1))
                        # and non_from_modules list (prefix matching preserved).
                        mp = from_symbol_to_module.get(ref_to_use)
                        if mp is not None:
                            ref_to_use = f"{mp}.{ref_to_use}"
                        else:
                            for mp in non_from_modules:
                                if ref_to_use == mp or ref_to_use.startswith(mp + ".") or ref_to_use.startswith(mp + "/"):
                                    break

                    target_ent = by_id.get(target_id) if target_id else None

                    if target_id is not None and source_ent.id != target_id:
                        _add(
                            source_ent.id,
                            target_id,
                            rel_type,
                            line_no,
                            rel_meta,
                            reference_start_byte=node.start_byte,
                            reference_end_byte=node.end_byte,
                            definition_start_byte=target_ent.start_byte,
                            definition_end_byte=target_ent.end_byte,
                            roles=role,
                            confidence=1.0,
                        )
                    else:
                        if not _prune_unresolved(ref_to_use, rel_type, file_imports, self._language_name, filepath, prune_enabled, imported_names):
                            unres = _make_contextual_stub(ref_to_use, line_no, rel_type, caller_scope=source_ent.id)
                            if unres.id not in unresolved_emitted:
                                unresolved_emitted.add(unres.id)
                                unresolved_entities.append(unres)
                            _add(
                                source_ent.id,
                                unres.id,
                                rel_type,
                                line_no,
                                rel_meta,
                                reference_start_byte=node.start_byte,
                                reference_end_byte=node.end_byte,
                                roles=role,
                            )

        # T5 rationale layer: every comment/doc entity gets a RATIONALE_FOR
        # edge to the symbol it explains — docstrings resolve via their
        # parent_id; marker comments attribute to the smallest enclosing
        # FUNCTION/METHOD/CLASS, else the immediately-following one.
        _ents_by_id = {e.id: e for e in entities}
        for ent in entities:
            if ent.type != EntityType.COMMENT_BLOCK:
                continue
            target_id = getattr(ent, "parent_id", None)
            if target_id:
                # parent_id bypasses the enclosing-symbol scan — but only
                # when the parent is a kind a comment can explain (a docstring
                # parented to MODULE/FILE must still attribute, not point at
                # the file container).
                parent_ent = _ents_by_id.get(target_id)
                if (
                    parent_ent is None
                    or parent_ent.type not in _RATIONALE_TARGET_TYPES
                ):
                    target_id = None
            if not target_id or target_id == ent.id:
                target_id = self._rationale_target_id(
                    ent, sorted_ents, sorted_starts, source
                )
            if target_id and target_id != ent.id:
                _add(
                    ent.id,
                    target_id,
                    RelationshipType.RATIONALE_FOR,
                    ent.start_line,
                    {
                        # Annotation-edge contract (schemas.ANNOTATION_RELATIONS
                        # / rules.py tag postpass): derived semantics, not
                        # structure — always stamped so G4/G6 edge_class
                        # filters see a consistent shape. `edge_class` also
                        # distinguishes this extraction emission from
                        # apply-layer overlay edges during `plugins apply`.
                        "edge_class": "annotation",
                        "semantic": True,
                        "rationale_kind": (ent.metadata or {}).get(
                            "rationale_kind", "comment"
                        ),
                    },
                    # INFERRED-grade confidence, matching the rules-engine
                    # convention for derived edges: 0.75 when the comment is
                    # parse-verified; marker entities found by the raw line
                    # scan (no parse tree to verify the hit is a real comment)
                    # get 0.5 — the marker could sit inside a string.
                    confidence=(
                        0.5
                        if (ent.metadata or {}).get("line_scan_fallback")
                        else 0.75
                    ),
                )

        return unresolved_entities, relationships

    # ------------------------------------------------------------------
    # T5 rationale layer — marker comments
    # ------------------------------------------------------------------

    def _marker_comment_pattern(self) -> re.Pattern[bytes] | None:
        """Build the byte-regex matching ``<delim> <MARKER>`` for this language.

        Line prefixes and block openers come from the per-language delimiter
        tables; repeated delimiter chars are allowed (`///`, `##`, `/**`).
        Returns None for languages without configured comment syntax.
        """
        # `get(key, default)` not `or`: an explicit empty list must flow
        # through to `if not markers` and disable the marker layer (EXT-14);
        # only a missing/null value falls back to defaults.
        markers = self._parsing_config.get(
            "rationale_markers", list(_DEFAULT_RATIONALE_MARKERS)
        )
        if markers is None:
            markers = list(_DEFAULT_RATIONALE_MARKERS)
        line_prefixes = _LINE_COMMENT_PREFIXES.get(self._language_name, ())
        block_pairs = _BLOCK_COMMENT_PAIRS.get(self._language_name, ())
        if not markers or (not line_prefixes and not block_pairs):
            return None
        delims: list[bytes] = []
        for prefix in line_prefixes:
            enc = prefix.encode()
            delims.append(re.escape(enc[:-1]) + re.escape(enc[-1:]) + b"+")
        for opener, _closer in block_pairs:
            enc = opener.encode()
            delims.append(re.escape(enc[:-1]) + re.escape(enc[-1:]) + b"+")
        marker_alt = b"|".join(re.escape(m.encode()) for m in markers)
        flags = (
            0
            if self._parsing_config.get("rationale_markers_case_sensitive", True)
            else re.IGNORECASE
        )
        return re.compile(rb"(?:" + b"|".join(delims) + rb")\s*(" + marker_alt + rb")", flags)

    def _extract_marker_comment_entities(
        self,
        source: bytes,
        filepath: str,
        root_node: Node | None = None,
    ) -> list[Entity]:
        """Scan source lines for marker comments and promote each to a
        COMMENT_BLOCK entity carrying ``rationale_kind`` metadata.

        Works on raw bytes so offsets stay exact even under
        ``errors="replace"`` decoding elsewhere. Matches markers at line start
        and in trailing comments (`x = f()  # WHY: fast path`).

        When *root_node* is provided (the normal ``parse_file`` path), each
        regex hit is verified against the parse tree: only hits whose bytes
        sit inside a real comment node are promoted, so a ``# WHY:`` line
        inside a triple-quoted string or a ``// WHY:`` inside a JS template
        literal produces nothing. Without *root_node* the raw line scan is
        kept and the entity is tagged ``line_scan_fallback`` so downstream
        RATIONALE_FOR edges emit at reduced confidence.
        """
        pat = self._marker_comment_pattern()
        if pat is None:
            return []
        # Block-continuation hits (`* WHY: …` inside a /* */ body) carry no
        # delimiter on their own line — only valid when a parse tree can
        # prove the byte sits inside a comment node.
        cont_pat: re.Pattern[bytes] | None = None
        if root_node is not None:
            markers = self._parsing_config.get(
                "rationale_markers", list(_DEFAULT_RATIONALE_MARKERS)
            )
            if markers is None:
                markers = list(_DEFAULT_RATIONALE_MARKERS)
            if markers:
                marker_alt = b"|".join(re.escape(m.encode()) for m in markers)
                cont_flags = (
                    0
                    if self._parsing_config.get(
                        "rationale_markers_case_sensitive", True
                    )
                    else re.IGNORECASE
                )
                cont_pat = re.compile(
                    rb"^\s*\*+\s*(" + marker_alt + rb")",
                    cont_flags | re.MULTILINE,
                )
        # Cheap reject before the line loop — must check BOTH patterns: a
        # jsdoc-style marker (`/**\n * WHY:`) only matches the continuation
        # form, so gating on pat alone would skip those files entirely.
        if not pat.search(source) and not (
            cont_pat is not None and cont_pat.search(source)
        ):
            return []
        stem = Path(filepath).stem
        entities: list[Entity] = []
        offset = 0
        for lineno, raw_line in enumerate(source.split(b"\n"), start=1):
            # A line can carry multiple delimiter+marker hits (`s = "# WHY:"
            # # WHY: real`); when a parse tree is available, take the first
            # hit that lands inside a real comment node.
            m: re.Match[bytes] | None = None
            m_start = -1
            comment_node: Node | None = None
            for cand in pat.finditer(raw_line):
                if root_node is None:
                    m = cand
                    m_start = offset + cand.start()
                    break
                node = _comment_node_at(root_node, offset + cand.start())
                if node is not None:
                    m = cand
                    m_start = offset + cand.start()
                    comment_node = node
                    break
            if m is None and cont_pat is not None:
                cand = cont_pat.search(raw_line)
                if cand is not None:
                    node = _comment_node_at(root_node, offset + cand.start())
                    if node is not None:
                        m = cand
                        m_start = offset + cand.start()
                        comment_node = node
            if m is not None:
                marker_text = m.group(1).decode("utf-8", errors="replace")
                kind = marker_text.rstrip(":").strip().lower() or "comment"
                if comment_node is not None:
                    # Span the whole comment node — a multi-line /* */ marker
                    # must end at `*/`, not end-of-line, so the gap to the
                    # following def is pure whitespace (attaches cleanly) and
                    # same-line code after `*/` isn't swallowed into the span.
                    start_byte = comment_node.start_byte
                    start_line = comment_node.start_point[0] + 1
                    end_byte = comment_node.end_byte
                    end_line = comment_node.end_point[0] + 1
                else:
                    # Fallback (no parse tree): keep the end-of-line span.
                    start_byte = m_start
                    start_line = lineno
                    end_byte = offset + len(raw_line)
                    end_line = lineno
                # T16: classification via the plugin hook when a host is
                # active (byte-identical to the inline fallback below —
                # parity in tests/sdk/test_hooks.py).
                try:
                    from batho_plugin.runtime import get_active_plugin_host

                    _host = get_active_plugin_host()
                except Exception:
                    _host = None
                if _host is not None:
                    from batho_plugin.hooks import classify_marker

                    metadata = classify_marker(
                        marker_text, self._language_name, root_node is not None
                    )
                    # T16: transient hint consumed by the dispatched
                    # ON_COMMENT_CLASSIFY hook in _build_relationships (produces
                    # the identical metadata + records the bsg.hooks mark).
                    # Stripped there whether or not dispatch ran.
                    metadata["_marker_text"] = marker_text
                else:
                    metadata: dict[str, Any] = {
                        "rationale_kind": kind,
                        "marker_comment": True,
                        "language": self._language_name,
                    }
                    if root_node is None:
                        metadata["line_scan_fallback"] = True
                # Content/hash must cover the comment itself, not the whole
                # code line — a trailing `x = f()  # WHY:` hit must not bake
                # the code prefix into the entity's identity.
                if comment_node is not None:
                    comment_bytes = source[
                        comment_node.start_byte:comment_node.end_byte
                    ]
                else:
                    comment_bytes = raw_line[m.start():]
                entities.append(
                    Entity(
                        type=EntityType.COMMENT_BLOCK,
                        name=f"{stem}::comment@{lineno}",
                        file=filepath,
                        start_line=start_line,
                        end_line=end_line,
                        start_byte=start_byte,
                        end_byte=end_byte,
                        enclosing_start_byte=start_byte,
                        enclosing_end_byte=end_byte,
                        signature=None,
                        metadata=metadata,
                        raw_content=comment_bytes.decode("utf-8", errors="replace").strip(),
                        content_hash=compute_bytes_hash(comment_bytes),
                        is_documentation=True,
                    )
                )
            offset += len(raw_line) + 1
        return entities

    def _rationale_target_id(
        self,
        comment: Entity,
        sorted_ents: list[Entity],
        sorted_starts: list[int],
        source: bytes,
    ) -> str | None:
        """Attribute a marker comment to its symbol.

        Inside case: smallest enclosing FUNCTION/METHOD/CLASS span.
        Preceding case: the next such entity whose span starts after the
        comment, when only blank/comment/decorator lines sit between —
        a comment between two functions attributes to the following def.
        """
        # Inside: smallest enclosing target-kind entity.
        idx = bisect.bisect_right(sorted_starts, comment.start_byte) - 1
        best: Entity | None = None
        while idx >= 0:
            ent = sorted_ents[idx]
            if (
                ent.type in _RATIONALE_TARGET_TYPES
                and ent.id != comment.id
                and ent.start_byte <= comment.start_byte
                and comment.end_byte <= ent.end_byte
            ):
                if best is None or (
                    ent.end_byte - ent.start_byte < best.end_byte - best.start_byte
                ):
                    best = ent
            if best and ent.start_byte < best.start_byte:
                break
            idx -= 1
        if best is not None:
            return best.id

        # Preceding: first following target-kind entity, attachable gap only.
        # The gap ends at the START OF THE LINE containing the definition so
        # leading modifiers (`export`, `pub`, `async`, `public static`) do not
        # count as intervening code.
        nxt = bisect.bisect_left(sorted_starts, comment.end_byte)
        while nxt < len(sorted_ents):
            ent = sorted_ents[nxt]
            if ent.type in _RATIONALE_TARGET_TYPES:
                line_start = source.rfind(b"\n", 0, ent.start_byte) + 1
                if self._rationale_gap_is_attachable(
                    source, comment.end_byte, line_start
                ):
                    return ent.id
                return None
            nxt += 1
        return None

    def _rationale_gap_is_attachable(
        self, source: bytes, gap_start: int, gap_end: int
    ) -> bool:
        """True when only blank lines, comment lines, or decorators/annotations
        sit between a marker comment and the following definition."""
        gap = source[gap_start:gap_end].decode("utf-8", errors="replace")
        line_prefixes = _LINE_COMMENT_PREFIXES.get(self._language_name, ())
        block_pairs = _BLOCK_COMMENT_PAIRS.get(self._language_name, ())
        block_openers = tuple(o for o, _ in block_pairs)
        block_closers = tuple(c for _o, c in block_pairs)
        for line in gap.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if line_prefixes and stripped.startswith(line_prefixes):
                continue
            if block_openers and stripped.startswith(block_openers):
                continue
            # Comment-tail lines: `* continuation` or a bare block closer —
            # a truncated marker end_byte (root_node=None fallback) can leave
            # the comment's remaining lines inside the gap.
            if re.fullmatch(r"\*+\s.*", stripped) or stripped in block_closers:
                continue
            if stripped.startswith("@"):  # decorator / annotation
                continue
            return False
        return True

    def _determine_symbol_role(self, cap_name: str, node: Node) -> SymbolRole:
        """Process tree-sitter capture and return symbol role."""
        from batho.core.schemas import SymbolRole
        if cap_name.startswith("ref.write"):
            return SymbolRole.WriteAccess
        elif cap_name.startswith("ref.read"):
            # If it's a read capture, but the node is also in a write position of a standard assignment,
            # skip ReadAccess.
            if node.parent and node.parent.type in ("assignment", "assignment_expression"):
                left_node = node.parent.child_by_field_name("left")
                if left_node == node or (left_node and left_node.start_byte <= node.start_byte < left_node.end_byte):
                    return SymbolRole(0)
            return SymbolRole.ReadAccess
        elif cap_name.startswith("ref.call"):
            return SymbolRole.ReadAccess
        elif cap_name.startswith("ref.indirect_call"):
            # T10: Indirect call — function passed as argument
            return SymbolRole.Dynamic | SymbolRole.ReadAccess
        elif cap_name.startswith("ref.import"):
            return SymbolRole.Import
        elif cap_name.startswith("ref.dynamic_import"):
            # T11: Dynamic import() — explicit but dynamic
            return SymbolRole.Import | SymbolRole.Dynamic
        elif cap_name.startswith("ref.re_export"):
            # T12: Re-export — explicit re-export from another module
            return SymbolRole.Import
        elif cap_name.startswith("ref.inherit"):
            return SymbolRole.ReadAccess
        elif cap_name.startswith("ref.implement"):
            return SymbolRole.ReadAccess
        return SymbolRole(0)

    # ------------------------------------------------------------------
    # Internal — metadata / signature helpers
    # ------------------------------------------------------------------

    def _collect_metadata_with_source(
        self,
        base_key: str,
        decl_node: Node,
        auxiliary_nodes: dict[tuple[str, str], list[Node]],
        source: bytes,
        source_lines: list[str] | None = None,
    ) -> EntityMetadata:
        """Collect full EntityMetadata including text fields that require source bytes.

        Args:
            base_key:       Capture base key (e.g. ``"def.function"``).
            decl_node:      tree-sitter declaration node.
            auxiliary_nodes: Parsed capture auxiliary map.
            source:         Raw file bytes.
            source_lines:   Pre-split lines, passed to avoid repeated
                            decode+splitlines in ``_extract_leading_doc_comment``.
        """
        metadata: EntityMetadata = {}
        metadata["language"] = self._language_name

        suffix_key_map: list[tuple[str, str]] = [
            ("visibility", "visibility"),
            ("invocation", "invocation_snippet"),
            ("docstring", "docstring"),
            ("bases", "bases"),
            ("extends", "extends"),
            ("trait", "trait"),
            ("receiver", "receiver"),
        ]
        for suffix, meta_key in suffix_key_map:
            nodes = auxiliary_nodes.get((base_key, suffix), [])
            node = self._nearest_ancestor(nodes, decl_node)
            if node is None:
                continue
            text = _node_text(node, source)
            if suffix == "docstring":
                text = _clean_docstring(text)
            metadata[meta_key] = text

        if not metadata.get("docstring"):
            fallback_doc = self._extract_leading_doc_comment(
                decl_node=decl_node, source=source, lines=source_lines
            )
            if fallback_doc:
                metadata["docstring"] = _clean_docstring(fallback_doc)

        # implements: comma-separated list
        impl_nodes = auxiliary_nodes.get((base_key, "implements"), [])
        impl_node = self._nearest_ancestor(impl_nodes, decl_node)
        if impl_node is not None:
            raw = _node_text(impl_node, source)
            metadata["implements"] = [s.strip() for s in raw.split(",") if s.strip()]

        # field_type
        ft_nodes = auxiliary_nodes.get((base_key, "type"), [])
        ft_node = self._nearest_ancestor(ft_nodes, decl_node)
        if ft_node is not None:
            metadata["field_type"] = _node_text(ft_node, source)

        return metadata

    def _extract_leading_doc_comment(
        self,
        decl_node: Node,
        source: bytes,
        lines: list[str] | None = None,
    ) -> str | None:
        """Extract contiguous comment lines immediately above a declaration.

        Args:
            decl_node: The tree-sitter Node for the declaration.
            source:    Raw source bytes (used only when *lines* is not provided).
            lines:     Pre-split text lines.  When provided, the *source* bytes
                       are NOT decoded, avoiding repeated O(n) decode+split per
                       entity call (EXT-04).
        """
        if lines is None:
            try:
                text = source.decode("utf-8", errors="replace")
            except Exception:
                return None
            lines = text.splitlines()
        line_idx = decl_node.start_point[0] - 1
        if line_idx < 0:
            return None

        comment_prefixes = ["#", "//", "--", ";", "%"]
        collected: list[str] = []
        in_block = False

        while line_idx >= 0:
            raw = lines[line_idx].rstrip()
            stripped = raw.strip()

            if not stripped:
                if collected:
                    break
                line_idx -= 1
                continue

            if stripped.endswith("*/"):
                in_block = True

            if in_block:
                cleaned = stripped
                cleaned = cleaned.lstrip("/*").rstrip("*/").strip()
                if cleaned:
                    collected.append(cleaned)
                if stripped.startswith("/*"):
                    in_block = False
                line_idx -= 1
                continue

            matched_prefix = next(
                (prefix for prefix in comment_prefixes if stripped.startswith(prefix)),
                None,
            )
            if matched_prefix is not None:
                cleaned = stripped[len(matched_prefix) :].strip()
                if cleaned:
                    collected.append(cleaned)
                line_idx -= 1
                continue

            break

        if not collected:
            return None
        return "\n".join(reversed(collected)).strip() or None

    def _build_signature(
        self,
        name: str,
        base_key: str,
        decl_node: Node,
        auxiliary_nodes: dict[tuple[str, str], list[Node]],
        source: bytes,
    ) -> str | None:
        """Construct a human-readable signature string from params + return type."""
        params_nodes = auxiliary_nodes.get((base_key, "params"), [])
        rt_nodes = auxiliary_nodes.get((base_key, "return_type"), [])

        params_node = self._nearest_ancestor(params_nodes, decl_node)
        rt_node = self._nearest_ancestor(rt_nodes, decl_node)

        if params_node is None and rt_node is None:
            return None

        params_text = _node_text(params_node, source) if params_node else "()"
        rt_text = _node_text(rt_node, source) if rt_node else ""

        if rt_text:
            return f"{name}{params_text} -> {rt_text}"
        return f"{name}{params_text}"

    @staticmethod
    def _nearest_ancestor(nodes: list[Node], decl_node: Node) -> Node | None:
        """
        Return the node from *nodes* whose ancestor chain passes through
        *decl_node*, i.e. the auxiliary node that belongs to this specific
        definition. Falls back to the first node if none are nested.
        """
        if not nodes:
            return None
        for candidate in nodes:
            current: Node | None = candidate.parent
            while current is not None:
                if current.id == decl_node.id:
                    return candidate
                current = current.parent
        return nodes[0]

    # ------------------------------------------------------------------
    # UTF-8 decoding helpers
    # ------------------------------------------------------------------

    def _safe_decode(
        self, raw_bytes: bytes, filepath: str, context: str = ""
    ) -> tuple[str, bytes | None]:
        """Decode bytes with strict UTF-8, falling back to replace mode on error.

        Args:
            raw_bytes: Bytes to decode.
            filepath: File path for error reporting.
            context: Additional context for error messages.

        Returns:
            Tuple of (decoded_string, raw_bytes_for_storage).
            raw_bytes_for_storage is None if strict decode succeeded,
            otherwise contains the original bytes for lossless reconstruction.

        Note:
            When UTF-8 decode fails, the returned decoded_string uses replacement
            characters () for invalid bytes. The raw_bytes field preserves the
            original bytes for truly lossless reconstruction during the bidirectional
            phase. This means raw_content may not round-trip perfectly, but raw_bytes
            ensures exact byte-level reconstruction.
        """
        try:
            decoded = raw_bytes.decode("utf-8", errors="strict")
            return decoded, None
        except UnicodeDecodeError as exc:
            self.logger.debug(
                "utf8_decode_fallback",
                filepath=filepath,
                context=context,
                error=str(exc),
                bytes_length=len(raw_bytes),
            )
            # Store raw bytes for lossless reconstruction
            decoded = raw_bytes.decode("utf-8", errors="replace")
            return decoded, raw_bytes

    # ------------------------------------------------------------------
    # Gap extraction (SYNTAX_GLUE entities)
    # ------------------------------------------------------------------

    _COMMENT_PREFIXES: set[str] = {"#", "//", "--", ";", "%", "(*", "/*"}

    def _classify_gap_type(self, raw: str) -> str:
        """Classify a gap's content into a category.

        Returns one of: ``whitespace``, ``comment``, ``import``, ``code``,
        ``separator``, ``partial_entity``.
        """
        stripped = raw.strip()
        if not stripped:
            return "whitespace"
        # Check for separator patterns first (before comment detection,
        # since some separators like --- start with comment prefix --)
        if re.match(r"^[=\-*]{3,}$", stripped):
            return "separator"
        # Check for comment prefixes
        first_line = stripped.partition("\n")[0].strip()
        if any(first_line.startswith(p) for p in self._COMMENT_PREFIXES):
            return "comment"
        # Check for import statements
        if (
            first_line.startswith("import ")
            or first_line.startswith("from ")
            or first_line.startswith("#include")
            or first_line.startswith("use ")
            or first_line.startswith("require")
            or "import " in first_line[:20]
        ):
            return "import"
        # If the gap is between entities where one or both have partial coverage
        # this is a heuristic fallback. We don't have AST access here but can infer
        # from content that looks like code (not whitespace/comments)
        return "code"

    def _extract_gaps(
        self,
        content: bytes,
        filepath: str,
        entities: list[Entity],
    ) -> list[Entity]:
        """Emit SYNTAX_GLUE entities for every byte gap between semantic entities.

        Args:
            content: Raw source bytes.
            filepath: Repo-relative path for the entity ``file`` field.
            entities: Semantic entities already extracted (sorted by start_byte).

        Returns:
            List of SYNTAX_GLUE Entity models covering uncovered byte ranges.
        """
        if not content:
            return []

        file_size = len(content)
        gap_entities: list[Entity] = []

        # Merged intervals representing covered regions
        intervals = [(e.start_byte, e.end_byte) for e in entities]
        merged_intervals = []
        if intervals:
            # Sort by start_byte, then end_byte descending to process outer intervals first
            sorted_intervals = sorted(intervals, key=lambda x: (x[0], -x[1]))
            merged_intervals.append(sorted_intervals[0])
            for start, end in sorted_intervals[1:]:
                prev_start, prev_end = merged_intervals[-1]
                if start <= prev_end:
                    merged_intervals[-1] = (prev_start, max(prev_end, end))
                else:
                    merged_intervals.append((start, end))

        # Precompute line start byte offsets using a single regex scan of newlines
        line_starts = [0] + [m.start() + 1 for m in re.finditer(b"\n", content)]

        # Helper to decode raw bytes with strict UTF-8 fallback
        def _decode_slice(start: int, end: int) -> tuple[str, bytes | None]:
            raw_bytes_slice = content[start:end]
            decoded, stored_raw_bytes = self._safe_decode(
                raw_bytes_slice, filepath, context=f"gap {start}-{end}"
            )
            return decoded, stored_raw_bytes

        # Helper to compute line number from byte offset using fast binary search
        def _byte_to_line(offset: int) -> int:
            off = min(offset, file_size)
            return bisect.bisect_right(line_starts, off)

        def _add_gap(start: int, end: int) -> None:
            if start >= end:
                return
            raw, raw_bytes = _decode_slice(start, end)
            gap_entities.append(
                Entity(
                    type=EntityType.SYNTAX_GLUE,
                    name="<glue>",
                    file=filepath,
                    start_line=_byte_to_line(start),
                    end_line=_byte_to_line(end),
                    start_byte=start,
                    end_byte=end,
                    raw_content=raw,
                    content_hash=compute_bytes_hash(content[start:end]),
                    raw_bytes=raw_bytes,
                    metadata={
                        "language": self._language_name,
                        "gap_type": self._classify_gap_type(raw),
                        "is_empty": not raw.strip(),
                        "contains_comments": any(
                            p in raw for p in self._COMMENT_PREFIXES
                        ),
                    },
                )
            )

        if not merged_intervals:
            _add_gap(0, file_size)
        else:
            # Leading gap
            _add_gap(0, merged_intervals[0][0])
            # Inter-interval gaps
            for i in range(len(merged_intervals) - 1):
                _add_gap(merged_intervals[i][1], merged_intervals[i+1][0])
            # Trailing gap
            _add_gap(merged_intervals[-1][1], file_size)

        return gap_entities

    def _enrich_bidirectional_attributes(
        self,
        entities: list[Entity],
        content: bytes,
    ) -> list[Entity]:
        """Compute parent_id, children_order, leading_whitespace, and trailing_whitespace.

        Uses a single-pass algorithm to resolve containment hierarchy via a
        monotonic stack, then applies whitespace and relationship data in one
        final ``_evolve()`` call per entity — avoiding the previous 3×
        frozen-model reconstruction overhead.

        Args:
            entities: Extracted semantic entities (any order).
            content: Raw file content bytes.

        Returns:
            List of updated Entity objects, in original input order.
        """
        if not content or not entities:
            return entities

        content_len = len(content)
        ws_set = b" \t\n\r"

        # ------------------------------------------------------------------
        # Step 1: Whitespace resolution
        # Compute leading/trailing whitespace bytes for each non-GLUE entity.
        # Stored as a parallel list indexed by entity position in `entities`.
        # ------------------------------------------------------------------
        leading_list: list[str] = [""] * len(entities)
        trailing_list: list[str] = [""] * len(entities)
        semantic_indices: list[int] = []  # positions of non-GLUE entities

        # First pass: identify semantic entities
        for idx, e in enumerate(entities):
            if e.type != EntityType.SYNTAX_GLUE:
                semantic_indices.append(idx)

        # Precompute limits for leading whitespace using sorted single-pass approach.
        # Sort by end_byte to find the nearest previous entity ending before each entity starts.
        leading_ws_bytes: list[bytes] = [b""] * len(entities)
        sorted_by_end = sorted(semantic_indices, key=lambda idx: entities[idx].end_byte)
        
        for idx in semantic_indices:
            e = entities[idx]
            # Find the entity with the highest end_byte that is <= e.start_byte
            limit_left = 0
            # Binary search for the rightmost entity ending at or before e.start_byte
            lo, hi = 0, len(sorted_by_end)
            while lo < hi:
                mid = (lo + hi) // 2
                mid_idx = sorted_by_end[mid]
                if entities[mid_idx].end_byte <= e.start_byte:
                    lo = mid + 1
                else:
                    hi = mid
            # lo is now the insertion point; the entity before it is the last one ending <= e.start_byte
            if lo > 0:
                limit_left = entities[sorted_by_end[lo - 1]].end_byte
            
            i = e.start_byte - 1
            while i >= limit_left and content[i] in ws_set:
                i -= 1
            leading_bytes = content[i + 1:e.start_byte]
            leading_ws_bytes[idx] = leading_bytes
            leading_list[idx] = leading_bytes.decode("utf-8", errors="replace")

        # Compute trailing whitespace limits using sorted approach.
        # For each entity, find the entity with the smallest start_byte that is >= e.end_byte,
        # then use its leading whitespace start as the limit.
        limit_right_arr: list[int] = [content_len] * len(entities)
        sorted_by_start = sorted(semantic_indices, key=lambda idx: entities[idx].start_byte)
        
        # Precompute leading whitespace start positions
        leading_ws_start: dict[int, int] = {
            idx: entities[idx].start_byte - len(leading_ws_bytes[idx])
            for idx in semantic_indices
        }
        
        for idx in semantic_indices:
            e = entities[idx]
            # Find the leftmost entity starting at or after e.end_byte
            lo, hi = 0, len(sorted_by_start)
            while lo < hi:
                mid = (lo + hi) // 2
                mid_idx = sorted_by_start[mid]
                if entities[mid_idx].start_byte < e.end_byte:
                    lo = mid + 1
                else:
                    hi = mid
            # lo is now the first entity with start_byte >= e.end_byte
            if lo < len(sorted_by_start):
                other_idx = sorted_by_start[lo]
                limit_right_arr[idx] = leading_ws_start[other_idx]
        
        for idx in semantic_indices:
            e = entities[idx]
            j = e.end_byte
            limit_right = limit_right_arr[idx]
            while j < limit_right and content[j] in ws_set:
                j += 1
            trailing_list[idx] = content[e.end_byte:j].decode("utf-8", errors="replace")

        # ------------------------------------------------------------------
        # Step 2: Containment hierarchy via monotonic stack
        # Sort semantic entities by (start_byte ASC, end_byte DESC) so that
        # parent entities always precede their children.
        # ------------------------------------------------------------------
        # Map original index -> semantic order position for stack work
        sorted_sem = sorted(
            semantic_indices,
            key=lambda idx: (entities[idx].start_byte, -entities[idx].end_byte),
        )

        stack: list[int] = []  # indices into `entities`
        parent_map: dict[str, str] = {}   # child entity.id -> parent entity.id
        children_map: dict[str, list[str]] = {}  # parent entity.id -> [child ids]

        for idx in sorted_sem:
            e = entities[idx]
            # Pop stack until we find a true ancestor
            while stack:
                anc = entities[stack[-1]]
                if anc.start_byte <= e.start_byte and e.end_byte <= anc.end_byte:
                    break
                stack.pop()

            if stack:
                parent_e = entities[stack[-1]]
                parent_map[e.id] = parent_e.id
                children_map.setdefault(parent_e.id, []).append(e.id)

            stack.append(idx)

        # ------------------------------------------------------------------
        # Step 3: Single-pass final Entity construction via _evolve()
        # Each entity is evolved at most once, applying whitespace + hierarchy
        # together to avoid the previous 3× frozen-model reconstruction.
        # ------------------------------------------------------------------
        result: list[Entity] = []
        for idx, e in enumerate(entities):
            if e.type == EntityType.SYNTAX_GLUE:
                result.append(e)
                continue

            p_id = e.parent_id or parent_map.get(e.id)
            c_order = children_map.get(e.id, [])
            leading = leading_list[idx]
            trailing = trailing_list[idx]

            # Only evolve if any attribute actually changed to avoid unnecessary
            # model_copy() overhead on already-correct entities
            # Compare c_order with children_order using tuple() to avoid list creation
            current_children = e.children_order
            children_changed = (
                c_order != current_children
                if isinstance(current_children, list)
                else c_order != list(current_children)
            )
            if (
                p_id != e.parent_id
                or children_changed
                or leading != e.leading_whitespace
                or trailing != e.trailing_whitespace
            ):
                e = e._evolve(
                    parent_id=p_id,
                    leading_whitespace=leading,
                    trailing_whitespace=trailing,
                    children_order=c_order,
                )
            result.append(e)

        return result


# ---------------------------------------------------------------------------
# MarkupConfigExtractor — base for markup and config file extractors
# ---------------------------------------------------------------------------


class MarkupConfigExtractor(ASTExtractor):
    """
    Abstract base class for markup and configuration file extractors.

    Handles HTML, CSS, Markdown, JSON, YAML, TOML, HCL — formats that
    have different structures than programming languages.

    Subclasses must implement:
    - _extract_elements(): Extract structural elements from the content
    - _extract_references(): Extract references/relationships between elements
    """

    def __init__(
        self, language: str, parsing_config: dict[str, Any] | None = None
    ) -> None:
        self._language_name = language
        self._ts_parser = None
        self._ts_language = None
        self._parsing_config: dict[str, Any] = parsing_config or {}
        self.logger = get_logger(__name__, operation="markup_extract").bind(
            language=language
        )

    def _query_source(self) -> str:
        """Return empty query — subclasses override parse_file() directly."""
        return ""

    @abc.abstractmethod
    def _extract_elements(
        self,
        source: bytes,
        filepath: str,
    ) -> list[Entity]:
        """Extract elements from markup/config content."""

    @abc.abstractmethod
    def _extract_references(
        self,
        source: bytes,
        filepath: str,
        entities: list[Entity],
    ) -> list[Relationship]:
        """Extract relationships from markup/config content."""

    def parse_file(
        self,
        filepath: str,
        content: bytes,
        index_id: str | None = None,
        include_gaps: bool = False,
        package: PackageMetadata | None = None,
    ) -> tuple[list[Entity], list[Relationship]]:
        """Parse a markup or configuration file."""
        t0 = time.perf_counter()

        try:
            entities = self._extract_elements(content, filepath)

            # Enrich extracted elements with raw content, content hash, and raw bytes.
            # Use model_copy to avoid manual field-by-field reconstruction.
            for i, entity in enumerate(entities):
                raw_content = entity.raw_content
                content_hash = entity.content_hash
                raw_bytes = entity.raw_bytes

                if raw_content is None or not content_hash:
                    start_byte = min(max(0, entity.start_byte), len(content))
                    end_byte = min(max(start_byte, entity.end_byte), len(content))
                    raw_bytes_slice = content[start_byte:end_byte]

                    decoded_content, stored_raw_bytes = self._safe_decode(
                        raw_bytes_slice, filepath, context=f"markup entity {entity.name}"
                    )
                    c_hash = compute_bytes_hash(raw_bytes_slice)

                    if raw_content is None:
                        raw_content = decoded_content
                    if not content_hash:
                        content_hash = c_hash
                    if raw_bytes is None:
                        raw_bytes = stored_raw_bytes

                    # Only update if we computed new values
                    if raw_content != entity.raw_content or content_hash != entity.content_hash or raw_bytes != entity.raw_bytes:
                        entities[i] = entity.model_copy(update={
                            "raw_content": raw_content,
                            "content_hash": content_hash,
                            "raw_bytes": raw_bytes,
                        })

            # Stamp entities with index_id in metadata using model_copy.
            if index_id:
                for i, entity in enumerate(entities):
                    metadata = dict(entity.metadata or {})
                    metadata["bsg.index_id"] = index_id
                    entities[i] = entity.model_copy(update={"metadata": metadata})
            entities = self._enrich_bidirectional_attributes(entities, content)
            relationships = self._extract_references(content, filepath, entities)
            entities.sort(key=lambda e: e.start_byte)

            if include_gaps and entities:
                gap_entities = self._extract_gaps(content, filepath, entities)
                entities.extend(gap_entities)
                entities.sort(key=lambda e: e.start_byte)
        except Exception as exc:
            self.logger.warning(
                "markup_parse_failed",
                filepath=filepath,
                error=str(exc),
            )
            return [], []

        parse_ms = round((time.perf_counter() - t0) * 1000, 2)
        self.logger.debug(
            "parse_file_complete",
            filepath=filepath,
            parse_ms=parse_ms,
            entity_count=len(entities),
            relationship_count=len(relationships),
            include_gaps=include_gaps,
        )
        return entities, relationships

    def _create_entity(
        self,
        entity_type: EntityType,
        name: str,
        filepath: str,
        start_line: int,
        end_line: int,
        start_byte: int,
        end_byte: int,
        metadata: EntityMetadata | None = None,
    ) -> Entity:
        """Helper to create an Entity with consistent defaults."""
        payload = dict(metadata or {})
        payload.setdefault("language", self._language_name)
        return Entity(
            type=entity_type,
            name=name,
            file=filepath,
            start_line=start_line,
            end_line=end_line,
            start_byte=start_byte,
            end_byte=end_byte,
            signature=None,
            metadata=payload,
        )

    def _create_relationship(
        self,
        source_id: str,
        target_id: str,
        rel_type: RelationshipType,
        line: int,
        *,
        reference_start_byte: int | None = None,
        reference_end_byte: int | None = None,
        definition_start_byte: int | None = None,
        definition_end_byte: int | None = None,
        roles: SymbolRole | int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Relationship:
        """Helper to create a Relationship with consistent defaults."""
        role_val = SymbolRole(roles) if roles is not None else SymbolRole(0)
        meta = {"line_number": line}
        if metadata:
            meta.update(metadata)
        return Relationship(
            source_id=source_id,
            target_id=target_id,
            type=rel_type,
            roles=role_val,
            reference_start_byte=reference_start_byte,
            reference_end_byte=reference_end_byte,
            definition_start_byte=definition_start_byte,
            definition_end_byte=definition_end_byte,
            metadata=meta,
        )

    def _extract_key_value_pairs(
        self,
        source: bytes,
        filepath: str,
    ) -> list[Entity]:
        """Default implementation for extracting key-value pairs (no-op)."""
        return []
