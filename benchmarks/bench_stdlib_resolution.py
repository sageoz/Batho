"""Benchmark I1 (stdlib resolution rate), I9 (per-language resolution coverage).

Reads a built Batho artifact and checks what fraction of the repo's actual
stdlib imports are correctly resolved as EXTERNAL_SYMBOL entities.
If no artifact path is provided, runs stdlib indexing in-memory only.
"""
import sys
import time
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from batho.modules.dependency.stdlib_tables import StdlibSymbolTable
from batho.modules.extraction.scope_manager import ScopeManager
from batho.modules.dependency.indexer import DependencyIndexer
from batho.core.schemas import EntityType

LANGUAGES = [
    "python", "javascript", "typescript", "go", "rust",
    "c", "cpp", "java", "ruby", "csharp", "php",
    "kotlin", "swift", "scala", "dart", "haskell",
    "lua", "r", "perl", "julia", "zig", "bash",
    "objc", "erlang", "ocaml", "hack", "verilog",
]


def bench_stdlib_scope_indexing():
    """I1 (indexing speed): Measure stdlib symbol indexing into ScopeManager."""
    table = StdlibSymbolTable()
    scope = ScopeManager()
    cfg = {"stdlib": {"enabled": True, "languages": LANGUAGES}}

    with tempfile.TemporaryDirectory() as tmp:
        indexer = DependencyIndexer(Path(tmp), scope, cfg)
        t0 = time.monotonic()
        indexer._index_stdlib()
        elapsed_ms = (time.monotonic() - t0) * 1000

    total_symbols = scope.global_symbol_count
    print(f"I1 (indexing): {total_symbols} symbols in {elapsed_ms:.1f}ms")
    return total_symbols


def bench_per_language_table_coverage():
    """I9 (table coverage): Per-language stdlib table coverage."""
    table = StdlibSymbolTable()
    per_lang = {}
    for lang in LANGUAGES:
        mods = table.get_all_modules(lang)
        sym_count = sum(len(v) for v in mods.values())
        per_lang[lang] = sym_count

    covered = sum(1 for v in per_lang.values() if v > 0)
    i9 = covered / len(LANGUAGES) * 100
    print(f"I9 (table coverage): {covered}/{len(LANGUAGES)} = {i9:.1f}%")
    for lang, count in sorted(per_lang.items()):
        print(f"  {lang}: {count} symbols")
    return i9


def bench_stdlib_resolution_rate(artifact_path: str | None = None):
    """I1 (resolution rate): What fraction of the repo's actual stdlib imports are resolved?

    Instead of checking if every theoretical stdlib module appears in the repo
    (which penalizes repos for not using modules they don't need), this measures
    resolution accuracy: of the stdlib modules the repo actually imports, how
    many are correctly materialized as EXTERNAL_SYMBOL entities?
    """
    if not artifact_path:
        print("I1 (resolution rate): No artifact path provided -- skipping")
        print("  (Run: python bench_stdlib_resolution.py /path/to/.batho/artifact)")
        return 0.0

    from batho.modules.storage.arrow_bundle import BathoBundleReader
    reader = BathoBundleReader(Path(artifact_path))
    all_entities = reader.get_all_entities()

    # Build set of all stdlib module names across all languages
    table = StdlibSymbolTable()
    stdlib_module_names: set[str] = set()
    for lang in LANGUAGES:
        mods = table.get_all_modules(lang)
        stdlib_module_names.update(mods.keys())

    # Collect all entity names and all resolved external symbol names
    all_entity_names: set[str] = set()
    all_resolved: set[str] = set()
    per_lang_entities: dict[str, set[str]] = {}
    per_lang_resolved: dict[str, set[str]] = {}

    for e in all_entities:
        etype = e.get("entity_type", "").upper()
        name = e.get("name", "")
        if not name:
            continue
        all_entity_names.add(name)

        # Track resolved external symbols
        if etype in ("EXTERNAL_SYMBOL", "EXTERNAL"):
            first_segment = name.split(".")[0].split("/")[0]
            all_resolved.add(first_segment)

        # Track per-language for I9
        lang = e.get("language", "").lower()
        if lang:
            per_lang_entities.setdefault(lang, set()).add(name)
            if etype in ("EXTERNAL_SYMBOL", "EXTERNAL"):
                first_segment = name.split(".")[0].split("/")[0]
                per_lang_resolved.setdefault(lang, set()).add(first_segment)

    # Find all entity names that look like stdlib imports
    actual_stdlib_refs: set[str] = set()
    for name in all_entity_names:
        first_segment = name.split(".")[0].split("/")[0]
        if first_segment in stdlib_module_names:
            actual_stdlib_refs.add(first_segment)

    # I1: Resolution rate = resolved / actual stdlib refs
    resolved = sum(1 for mod in actual_stdlib_refs if mod in all_resolved)
    total = len(actual_stdlib_refs)
    rate = (resolved / total * 100) if total > 0 else 100.0

    print(f"I1 (resolution rate): {resolved}/{total} = {rate:.1f}%")
    if total > 0:
        unresolved = actual_stdlib_refs - all_resolved
        if unresolved:
            print(f"  Unresolved stdlib refs: {sorted(unresolved)}")

    # I9: Per-language resolution rate
    print(f"I9 (per-language resolution):")
    lang_rates: list[float] = []
    for lang in sorted(per_lang_entities.keys()):
        lang_names = per_lang_entities[lang]
        lang_stdlib_refs: set[str] = set()
        for name in lang_names:
            first_segment = name.split(".")[0].split("/")[0]
            if first_segment in stdlib_module_names:
                lang_stdlib_refs.add(first_segment)
        lang_resolved = per_lang_resolved.get(lang, set())
        lang_resolved_refs = lang_stdlib_refs & lang_resolved
        lang_total = len(lang_stdlib_refs)
        lang_rate = (len(lang_resolved_refs) / lang_total * 100) if lang_total > 0 else 100.0
        lang_rates.append(lang_rate)
        print(f"  {lang}: {len(lang_resolved_refs)}/{lang_total} = {lang_rate:.1f}%")

    if lang_rates:
        i9 = min(lang_rates)  # Per-language minimum coverage
        print(f"I9 (min): {i9:.1f}%")
    else:
        i9 = 100.0
        print(f"I9 (min): {i9:.1f}% (no language-specific entities found)")

    return rate


if __name__ == "__main__":
    artifact = sys.argv[1] if len(sys.argv) > 1 else None
    print("=" * 60)
    print("Batho Stdlib Resolution Benchmark")
    print("=" * 60)
    bench_stdlib_scope_indexing()
    print()
    bench_per_language_table_coverage()
    print()
    bench_stdlib_resolution_rate(artifact)
