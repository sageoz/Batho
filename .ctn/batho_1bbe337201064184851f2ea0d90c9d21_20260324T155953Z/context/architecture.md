📁 (root)/
  📄 batho.py
    - if __name__ == "__main__":
    sys.exit(main()) (entry_point) [L1-716]
    - _generate_index_id() -> str (function) [L55-57]
    - _ensure_ctn_dir(root: Path) -> Path (function) [L60-63]
    - _load_index_metadata(ctn_dir: Path) -> dict[str, Any] (function) [L89-102]
    - _save_index_metadata(ctn_dir: Path, metadata: dict[str, Any]) -> None (function) [L105-112]
    - _write_json(path: Path, data: Any) -> None (function) [L115-119]
    - _write_text(path: Path, content: str) -> None (function) [L122-126]
    - _write_metrics(path: Path, payload: dict[str, Any]) -> None (function) [L129-133]
    - _estimate_tokens(text: str) -> int (function) [L136-139]
    - _collect_repo_metrics(root: Path, max_file_size_kb: int | None = None) -> dict[str, Any] (function) [L142-171]
    - _needs_metrics_backfill(metadata: dict[str, Any]) -> bool (function) [L174-186]
    - _backfill_index_metrics(ctn_dir: Path, root: Path) -> bool (function) [L189-213]
    - _compute_repo_hash(root: Path) -> str (function) [L216-228]
    - _load_current_graph(ctn_dir: Path, index_id: str) -> InMemoryGraph | None (function) [L231-239]
    - _strip_files(graph: InMemoryGraph, file_paths: Iterable[str]) -> None (function) [L242-250]
    - _reindex_files(root: Path, files: list[Path], indexer: CodeGraphIndexer, graph: InMemoryGraph) -> None (function) [L253-275]
    - _files_from_diff(diff_path: Path, root: Path) -> list[Path] (function) [L278-293]
    - cmd_index(args: argparse.Namespace) -> int (function) [L301-462]
    - cmd_stats(args: argparse.Namespace) -> int (function) [L465-493]
    - cmd_snapshots(args: argparse.Namespace) -> int (function) [L496-501]
    - cmd_diff_snapshots(args: argparse.Namespace) -> int (function) [L504-513]
    - cmd_patch(args: argparse.Namespace) -> int (function) [L516-628]
    - cmd_webhook(args: argparse.Namespace) -> int (function) [L631-639]
    - cmd_invalidate(args: argparse.Namespace) -> int (function) [L642-651]
    - build_parser() -> argparse.ArgumentParser (function) [L659-705]
    - main(argv: list[str] | None = None) -> int (function) [L708-711]
    - __name__ (entry_point) [L714-714]
    deps: argparse, batho_core.config, batho_core.context.categorizer, batho_core.context.codegraph, batho_core.context.languages.detector, batho_core.context.languages.registry, batho_core.context.repomap, batho_core.context.stack_detector, batho_core.time_machine, batho_core.utils.hash, batho_core.utils.ignore, contextlib, datetime, pathlib, sys, tests/testdata/outputs/configs/invalid_configs/type_errors.json, tests/testdata/repositories/flask/.readthedocs.yaml, tests/testdata/repositories/flask/repository_metadata.json, time, typing, uuid
  📄 test.py
    - if __name__ == "__main__":
    sys.exit(main()) (entry_point) [L1-87]
    - main() -> int (function) [L22-82]
    - __name__ (entry_point) [L85-85]
    deps: pathlib, subprocess, sys
  📄 verify_repomap_entity_types.py
    - if __name__ == "__main__":
    raise SystemExit(main()) (entry_point) [L1-182]
    - _load_repomap(root: Path, repomap_path: Path | None) -> tuple[Path, dict] (function) [L94-106]
    - _print_issue(label: str, values: Iterable[str], limit: int) -> None (function) [L109-113]
    - main() -> int (function) [L116-177]
    - __name__ (entry_point) [L180-180]
    deps: argparse, pathlib, re, tests/testdata/repositories/flask/repository_metadata.json, typing

📁 batho_core/
  📄 config.py
    - LoggingConfig (class) [L45-58]
    - PathsConfig (class) [L61-62]
    - IndexerConfig (class) [L65-84]
    - FlagsConfig (class) [L87-89]
    - Config (class) [L92-102]
    - _env(name: str, default: Optional[str] = None) -> Optional[str] (function) [L105-107]
    - _env_int(name: str, default: int) -> int (function) [L110-114]
    - _env_float(name: str, default: float) -> float (function) [L117-121]
    - _env_list(name: str) -> list[str] | None (function) [L124-131]
    - _load_config_file(path: Path) -> dict[str, Any] (function) [L134-145]
    - _merge_config(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any] (function) [L148-155]
    - get_log_level() -> int (function) [L158-159]
    - get_build_info() -> dict[str, str] (function) [L162-170]
    - get_config(config_file: str | None = None) -> Dict[str, Any] (function) [L173-274]
    - reload_config(config_file: str | None = None) -> Dict[str, Any] (function) [L282-284]
    deps: tests/testdata/repositories/flask/repository_metadata.json
  📄 time_machine.py
    - _snapshot_dir(ctn_dir: Path) -> Path (function) [L25-28]
    - generate_snapshot_id() -> str (function) [L31-33]
    - create_snapshot(
    ctn_dir: Path,
    root: Path,
    graph: InMemoryGraph,
    repomap: RepoMap,
    label: str | None = None,
) -> str (function) [L36-66]
    - list_snapshots(ctn_dir: Path) -> list[dict[str, Any]] (function) [L69-83]
    - load_snapshot(ctn_dir: Path, snapshot_id: str) -> dict[str, Any] | None (function) [L86-100]
    - diff_snapshots(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any] (function) [L103-115]
    - _files(rep_json: dict[str, Any]) -> set[str] (function) [L104-105]
    - compute_staleness(prev_entry: dict[str, Any] | None, current_repo_hash: str, stats: dict[str, Any] | None = None) -> float (function) [L118-151]
    - incremental_patch_stub(ctn_dir: Path, changed_files: Iterable[Path]) -> dict[str, Any] (function) [L154-167]
    - webhook_stub(event_payload: dict[str, Any]) -> dict[str, Any] (function) [L170-182]

📁 batho_core/context/
  📄 categorizer.py
    - FileCategory (class) [L19-29]
    - __str__(self) -> str (method) [L28-29]
    - FileCategorizer (class) [L32-238]
    - __init__(self) -> None (method) [L127-129]
    - categorize(self, file_path: str) -> FileCategory (method) [L131-165]
    - _is_test_file(self, parts: list[str], filename: str, stem: str, suffix: str) -> bool (method) [L167-184]
    - _is_doc_file(self, parts: list[str], filename: str, stem: str, suffix: str) -> bool (method) [L186-203]
    - _is_config_file(self, parts: list[str], filename: str, stem: str, suffix: str) -> bool (method) [L205-226]
    - _is_source_file(self, parts: list[str], filename: str, suffix: str) -> bool (method) [L228-238]
    - categorize_file(file_path: str) -> FileCategory (function) [L245-255]
  📄 codegraph.py
    - _calculate_shannon_entropy(data: bytes) -> float (function) [L63-76]
    - _is_binary(content: bytes) -> bool (function) [L79-106]
    - _read_file_content(filepath: str, max_size_kb: int | None = None) -> bytes | None (function) [L109-137]
    - InMemoryGraph (class) [L154-251]
    - __init__(
        self,
        entities: dict[str, Entity] | None = None,
        relationships: list[Relationship] | None = None,
    ) -> None (method) [L163-173]
    - add_entity(self, entity: Entity) -> None (method) [L175-176]
    - add_relationship(self, relationship: Relationship) -> None (method) [L178-181]
    - get_entity(self, entity_id: str) -> Entity | None (method) [L183-184]
    - _build_index(self) -> None (method) [L186-193]
    - neighbors(self, entity_id: str, direction: str = "out") -> list[str] (method) [L195-204]
    - entities_by_file(self, file_path: str) -> list[Entity] (method) [L206-207]
    - entities_by_type(self, entity_type: EntityType) -> list[Entity] (method) [L209-210]
    - root_entities(self) -> list[Entity] (method) [L212-213]
    - stats(self) -> dict[str, Any] (method) [L215-226]
    - to_dict(self) -> dict[str, Any] (method) [L228-233]
    - __len__(self) -> int (method) [L244-245]
    - __contains__(self, entity_id: str) -> bool (method) [L247-248]
    - __repr__(self) -> str (method) [L250-251]
    - _FileStateCache (class) [L259-351]
    - __init__(self, cache_path: Path, root: Path | None = None) -> None (method) [L272-278]
    - _load(self) -> None (method) [L280-297]
    - _mark_corrupt(self, reason: str) -> None (method) [L299-314]
    - _normalise(self, filepath: str) -> str (method) [L320-327]
    - save(self) -> None (method) [L329-338]
    - is_cached(self, filepath: str, content_hash: str) -> bool (method) [L340-345]
    - update(self, filepath: str, mtime: float, content_hash: str) -> None (method) [L347-348]
    - invalidate(self, filepath: str) -> None (method) [L350-351]
    - CodeGraphIndexer (class) [L359-723]
    - __init__(self, cache_path: str = ".ctn/file_cache.json", root: str | None = None) -> None (method) [L381-386]
    - build_graph(
        self,
        root: str,
        extractor: ASTExtractor | None = None,
        extensions: list[str] | None = None,
        max_workers: int = 0,
        max_file_size_kb: int | None = None,
        verbose: bool = False,
        metrics_callback: Callable[[str, Dict[str, Any]], None] | None = None,
    ) -> InMemoryGraph (method) [L392-611]
    - _process_file(args: tuple[Path, str]) -> tuple[str, list[Entity], list[Relationship], bool] | None (function) [L500-545]
    - index_file(
        self,
        filepath: str,
        extractor: ASTExtractor,
        max_file_size_kb: int | None = None,
    ) -> tuple[list[Entity], list[Relationship]] (method) [L613-656]
    - invalidate(self, filepath: str) -> None (method) [L658-664]
    - stats(self) -> dict[str, int] (method) [L666-668]
    - _resolve_imports(self, graph: InMemoryGraph) -> InMemoryGraph (method) [L674-723]
  📄 extractor.py
    - _node_text(node: Node, source: bytes) -> str (function) [L88-94]
    - _clean_docstring(text: str) -> str (function) [L97-103]
    - _read_file_bytes(filepath: str, max_size_kb: int = 500) -> bytes | None (function) [L106-131]
    - ASTExtractor (class) [L139-559]
    - __init__(self, language: str) -> None (method) [L165-176]
    - parse_file(
        self,
        filepath: str,
        content: bytes,
    ) -> tuple[list[Entity], list[Relationship]] (method) [L196-260]
    - _process_captures(
        self,
        captures: dict[str, list[Node]],
        source: bytes,
        filepath: str,
    ) -> tuple[list[Entity], list[Relationship]] (method) [L266-297]
    - _build_entities(
        self,
        definition_nodes: dict[str, list[Node]],
        auxiliary_nodes: dict[tuple[str, str], list[Node]],
        source: bytes,
        filepath: str,
    ) -> list[Entity] (method) [L299-344]
    - _build_relationships(
        self,
        captures: dict[str, list[Node]],
        entities: list[Entity],
        source: bytes,
        filepath: str,
    ) -> list[Relationship] (method) [L346-452]
    - _add(
            src_id: str, tgt_id: str, rel_type: RelationshipType, line: int
        ) -> None (function) [L357-370]
    - _find_enclosing(byte_offset: int) -> Entity | None (function) [L387-395]
    - _collect_metadata_with_source(
        self,
        base_key: str,
        decl_node: Node,
        auxiliary_nodes: dict[tuple[str, str], list[Node]],
        source: bytes,
    ) -> EntityMetadata (method) [L458-500]
    - _build_signature(
        self,
        name: str,
        base_key: str,
        decl_node: Node,
        auxiliary_nodes: dict[tuple[str, str], list[Node]],
        source: bytes,
    ) -> str | None (method) [L502-525]
    - _enrich_entity(
        self,
        entity: Entity,
        decl_node: Node,
        auxiliary_nodes: dict[tuple[str, str], list[Node]],
        source: bytes,
    ) -> Entity (method) [L544-559]
    - MarkupConfigExtractor (class) [L567-683]
    - __init__(self, language: str) -> None (method) [L579-583]
    - _query_source(self) -> str (method) [L585-587]
    - parse_file(
        self,
        filepath: str,
        content: bytes,
    ) -> tuple[list[Entity], list[Relationship]] (method) [L606-634]
    - _create_entity(
        self,
        entity_type: EntityType,
        name: str,
        filepath: str,
        start_line: int,
        end_line: int,
        start_byte: int,
        end_byte: int,
        metadata: EntityMetadata | None = None,
    ) -> Entity (method) [L636-660]
    - _create_relationship(
        self,
        source_id: str,
        target_id: str,
        rel_type: RelationshipType,
        line: int,
    ) -> Relationship (method) [L662-675]
    - _extract_key_value_pairs(
        self,
        source: bytes,
        filepath: str,
    ) -> list[Entity] (method) [L677-683]
    deps: tests/testdata/repositories/flask/.readthedocs.yaml
  📄 repomap.py
    - _text_tokens(text: str) -> int (function) [L34-36]
    - RepoMap (class) [L45-678]
    - __post_init__(self) -> None (method) [L66-67]
    - _rel(p: str) -> str (function) [L96-101]
    - render_full(self) -> str (method) [L143-169]
    - render_compressed(self, budget: int, fail_on_overflow: bool = True) -> tuple[str, dict[str, int]] (method) [L171-225]
    - render_json(self) -> dict[str, Any] (method) [L227-274]
    - _get_directory_label(self, dir_path: str) -> str | None (method) [L280-300]
    - group_by_directory(self) -> dict[str, list[tuple[str, list[Entity]]]] (method) [L302-312]
    - render_hierarchical(
        self,
        include_entities: bool = True,
    ) -> str (method) [L314-364]
    - render_tree_only(self) -> str (method) [L366-368]
    - categorize_files(self) -> dict[FileCategory, dict[str, list[Entity]]] (method) [L374-394]
    - render_category(
        self,
        category: FileCategory,
        include_full_entities: bool = False,
    ) -> str (method) [L396-454]
    - _group_by_directory_for_files(
        self,
        files_data: dict[str, list[Entity]],
    ) -> dict[str, list[tuple[str, list[Entity]]]] (method) [L456-468]
    - _summarize_entity_types(self, entities: list[Entity]) -> str (method) [L470-475]
    - render_overview(
        self,
        stack_info: dict[str, Any] | None = None,
        repo_name: str | None = None,
        timestamp: str | None = None,
    ) -> str (method) [L481-607]
    - _count_by_language(self) -> dict[str, int] (method) [L609-627]
    - _render_high_level_tree(self, max_depth: int = 3) -> list[str] (method) [L629-658]
    - get_depth(path: str) -> int (function) [L634-635]
    - estimate_tokens(self) -> int (method) [L664-668]
    deps: datetime
  📄 schema.py
    - EntityType (class) [L29-55]
    - __str__(self) -> str (method) [L54-55]
    - RelationshipType (class) [L58-75]
    - __str__(self) -> str (method) [L74-75]
    - Entity (class) [L83-152]
    - to_dict(self) -> dict[str, Any] (method) [L119-132]
    - __str__(self) -> str (method) [L142-144]
    - __hash__(self) -> int (method) [L146-147]
    - __eq__(self, other: object) -> bool (method) [L149-152]
    - Relationship (class) [L160-210]
    - to_dict(self) -> dict[str, Any] (method) [L184-191]
    - __str__(self) -> str (method) [L201-202]
    - __hash__(self) -> int (method) [L204-205]
    - __eq__(self, other: object) -> bool (method) [L207-210]
  📄 stack_detector.py
    - _normalize_package_name(name: str) -> str (function) [L459-461]
    - _match_framework(
    package_name: str, framework_map: dict[str, str]
) -> str | None (function) [L464-482]
    - _safe_read(path: Path) -> str (function) [L485-489]
    - _detect_package_manager(root_path: Path) -> list[str] (function) [L492-497]
    - _dedupe_preserve_order(values: list[str]) -> list[str] (function) [L500-501]
    - _detect_java(text: str) -> None (function) [L504-538]
    - _scan_deps(text: str) -> None (function) [L511-516]
    - _detect_dotnet(root_path: Path) -> dict[str, Any] | None (function) [L541-559]
    - _detect_go(root_path: Path) -> dict[str, Any] | None (function) [L562-576]
    - _detect_php(root_path: Path) -> dict[str, Any] | None (function) [L579-596]
    - _detect_ruby(root_path: Path) -> dict[str, Any] | None (function) [L599-613]
    - _detect_rust(root_path: Path) -> dict[str, Any] | None (function) [L616-645]
    - _detect_mobile(root_path: Path) -> dict[str, Any] | None (function) [L648-662]
    - _detect_infra(root_path: Path) -> list[str] (function) [L665-674]
    - _extract_python_version_from_requires_python(requires_python: str) -> str (function) [L677-690]
    - _detect_build_tool(pyproject_data: dict[str, Any]) -> str | None (function) [L693-722]
    - detect_python_stack(root_dir: str | Path) -> dict[str, Any] | None (function) [L725-857]
    - detect_node_stack(root_dir: str | Path) -> dict[str, Any] | None (function) [L860-925]
    - _find_all_node_stacks(root_path: Path) -> list[dict[str, Any]] (function) [L928-947]
    - detect_stack(root_dir: str | Path) -> dict[str, Any] (function) [L950-1039]
    - _detect_special_files(
    root_path: Path,
    languages: list[str],
    frameworks: set[str],
    build_tools: list[str],
) -> None (function) [L1042-1094]
    deps: re, tomllib

📁 batho_core/context/languages/
  📄 _common.py
    - CommonQueries (class) [L23-133]
    - ProgrammingLanguageExtractor (class) [L140-174]
    - ImportPatterns (class) [L181-206]
    - CallPatterns (class) [L209-236]
    - build_query(segments: list[str]) -> str (function) [L243-253]
    - comment_block(title: str, width: int = 70) -> str (function) [L256-268]
  📄 bash.py
    - BashExtractor (class) [L17-58]
    - __init__(self) -> None (method) [L20-21]
    - _query_source(self) -> str (method) [L23-58]
  📄 c.py
    - CExtractor (class) [L20-59]
    - __init__(self) -> None (method) [L23-24]
    - _query_source(self) -> str (method) [L26-59]
  📄 cpp.py
    - CppExtractor (class) [L23-85]
    - __init__(self) -> None (method) [L26-27]
    - _query_source(self) -> str (method) [L29-85]
  📄 csharp.py
    - CSharpExtractor (class) [L21-84]
    - __init__(self) -> None (method) [L24-25]
    - _query_source(self) -> str (method) [L27-84]
  📄 css.py
    - CSSExtractor (class) [L28-244]
    - __init__(self) -> None (method) [L31-32]
    - _extract_elements(
        self,
        source: bytes,
        filepath: str,
    ) -> list[Entity] (method) [L34-165]
    - _count_properties(self, properties_block: str) -> int (method) [L167-172]
    - _extract_references(
        self,
        source: bytes,
        filepath: str,
        entities: list[Entity],
    ) -> list[Relationship] (method) [L174-244]
  📄 dart.py
    - DartExtractor (class) [L19-82]
    - __init__(self) -> None (method) [L22-23]
    - _query_source(self) -> str (method) [L25-82]
  📄 detector.py
    - DetectionResult (class) [L41-63]
    - is_confident(self, threshold: float = 0.7) -> bool (method) [L57-59]
    - is_available(self) -> bool (method) [L61-63]
    - detect_by_extension(filepath: Path, content: bytes) -> DetectionResult | None (function) [L71-98]
    - detect_by_special_filename(filepath: Path, content: bytes) -> DetectionResult | None (function) [L141-173]
    - detect_by_shebang(content: bytes) -> DetectionResult | None (function) [L204-245]
    - detect_by_magic_bytes(content: bytes) -> DetectionResult | None (function) [L265-297]
    - detect_by_content_heuristics(content: bytes) -> DetectionResult | None (function) [L330-363]
    - LanguageDetector (class) [L371-523]
    - __init__(self, min_confidence: float = 0.5) -> None (method) [L396-404]
    - detect(
        self,
        filepath: Path,
        content: bytes,
    ) -> DetectionResult | None (method) [L406-441]
    - detect_with_fallback(
        self,
        filepath: Path,
        content: bytes,
    ) -> DetectionResult | None (method) [L443-487]
    - get_extractor(
        self,
        filepath: Path,
        content: bytes,
    ) -> object | None (method) [L489-523]
    - detect_language(
    filepath: str | Path,
    content: bytes,
) -> DetectionResult | None (function) [L545-559]
    - detect_language_with_fallback(
    filepath: str | Path,
    content: bytes,
) -> DetectionResult | None (function) [L562-576]
  📄 erlang.py
    - ErlangExtractor (class) [L18-74]
    - __init__(self) -> None (method) [L21-22]
    - _query_source(self) -> str (method) [L24-74]
  📄 factory.py
    - ConfigurableExtractor (class) [L33-59]
    - __init__(self, language: str, query_source: str) -> None (method) [L46-55]
    - _query_source(self) -> str (method) [L57-59]
    - create_extractor(language: str, query_source: str) -> ASTExtractor (function) [L62-80]
    - get_extractor(language: str) -> ASTExtractor | None (function) [L430-460]
    - register_extractor(language: str, query_source: str) -> None (function) [L463-481]
    - list_supported_languages() -> list[str] (function) [L484-491]
    - clear_extractor_cache() -> None (function) [L494-500]
  📄 go.py
    - GoExtractor (class) [L21-65]
    - __init__(self) -> None (method) [L24-25]
    - _query_source(self) -> str (method) [L27-65]
  📄 hack.py
    - HackExtractor (class) [L23-81]
    - __init__(self) -> None (method) [L26-27]
    - _query_source(self) -> str (method) [L29-81]
  📄 haskell.py
    - HaskellExtractor (class) [L18-85]
    - __init__(self) -> None (method) [L21-22]
    - _query_source(self) -> str (method) [L24-85]
  📄 hcl.py
    - HCLExtractor (class) [L26-355]
    - __init__(self) -> None (method) [L29-30]
    - _extract_elements(
        self,
        source: bytes,
        filepath: str,
    ) -> list[Entity] (method) [L32-173]
    - _find_block_end(self, content: str, start_pos: int, brace_positions: list) -> int (method) [L175-187]
    - _extract_attributes(
        self,
        content: str,
        filepath: str,
        parent_path: str,
        entities: list[Entity],
        line_offset: int,
        full_content: str,
        get_line_from_offset: Any,
        exclude_blocks: bool = False,
    ) -> None (method) [L189-236]
    - _extract_references(
        self,
        source: bytes,
        filepath: str,
        entities: list[Entity],
    ) -> list[Relationship] (method) [L238-355]
  📄 html.py
    - HTMLExtractor (class) [L29-254]
    - __init__(self) -> None (method) [L32-33]
    - _extract_elements(
        self,
        source: bytes,
        filepath: str,
    ) -> list[Entity] (method) [L35-155]
    - _extract_title(self, content: str) -> str | None (method) [L157-162]
    - _extract_references(
        self,
        source: bytes,
        filepath: str,
        entities: list[Entity],
    ) -> list[Relationship] (method) [L164-254]
  📄 java.py
    - JavaExtractor (class) [L18-63]
    - __init__(self) -> None (method) [L21-22]
    - _query_source(self) -> str (method) [L24-63]
  📄 javascript.py
    - JavaScriptExtractor (class) [L22-62]
    - __init__(self) -> None (method) [L25-26]
    - _query_source(self) -> str (method) [L28-62]
  📄 json.py
    - JSONExtractor (class) [L26-235]
    - __init__(self) -> None (method) [L29-30]
    - _extract_elements(
        self,
        source: bytes,
        filepath: str,
    ) -> list[Entity] (method) [L32-81]
    - _process_value(
        self,
        value: Any,
        filepath: str,
        name: str,
        entities: list[Entity],
        line_offset: int,
        source: bytes,
        parent_path: str = "",
    ) -> None (method) [L83-172]
    - _serialize_value(self, value: Any) -> Any (method) [L174-178]
    - _extract_references(
        self,
        source: bytes,
        filepath: str,
        entities: list[Entity],
    ) -> list[Relationship] (method) [L180-235]
  📄 julia.py
    - JuliaExtractor (class) [L18-81]
    - __init__(self) -> None (method) [L21-22]
    - _query_source(self) -> str (method) [L24-81]
  📄 kotlin.py
    - KotlinExtractor (class) [L19-74]
    - __init__(self) -> None (method) [L22-23]
    - _query_source(self) -> str (method) [L25-74]
  📄 lua.py
    - LuaExtractor (class) [L17-67]
    - __init__(self) -> None (method) [L20-21]
    - _query_source(self) -> str (method) [L23-67]
  📄 markdown.py
    - MarkdownExtractor (class) [L28-354]
    - __init__(self) -> None (method) [L31-32]
    - _extract_elements(
        self,
        source: bytes,
        filepath: str,
    ) -> list[Entity] (method) [L34-230]
    - _extract_frontmatter(self, content: str) -> dict[str, Any] | None (method) [L232-258]
    - _extract_references(
        self,
        source: bytes,
        filepath: str,
        entities: list[Entity],
    ) -> list[Relationship] (method) [L260-354]
  📄 ocaml.py
    - OCamlExtractor (class) [L18-85]
    - __init__(self) -> None (method) [L21-22]
    - _query_source(self) -> str (method) [L24-85]
  📄 perl.py
    - PerlExtractor (class) [L17-73]
    - __init__(self) -> None (method) [L20-21]
    - _query_source(self) -> str (method) [L23-73]
  📄 php.py
    - PHPExtractor (class) [L19-72]
    - __init__(self) -> None (method) [L22-23]
    - _query_source(self) -> str (method) [L25-72]
  📄 python.py
    - PythonExtractor (class) [L22-91]
    - __init__(self) -> None (method) [L25-26]
    - _query_source(self) -> str (method) [L28-91]
  📄 r.py
    - RExtractor (class) [L16-71]
    - __init__(self) -> None (method) [L19-20]
    - _query_source(self) -> str (method) [L22-71]
  📄 registry.py
    - is_language_available(language: str) -> bool (function) [L234-275]
    - _build_class_map() -> None (function) [L282-360]
    - _get_extractor_instance(language: str) -> ASTExtractor | None (function) [L370-406]
    - _discover_language_modules() -> None (function) [L409-500]
    - discover_and_register_all() -> None (function) [L503-513]
    - get_extractor(extension: str) -> ASTExtractor | None (function) [L516-554]
    - get_extractor_for_language(language: str) -> ASTExtractor | None (function) [L557-571]
    - get_language_for_extension(extension: str) -> str | None (function) [L574-584]
    - get_extensions_for_language(language: str) -> list[str] (function) [L587-597]
  📄 ruby.py
    - RubyExtractor (class) [L21-59]
    - __init__(self) -> None (method) [L24-25]
    - _query_source(self) -> str (method) [L27-59]
  📄 rust.py
    - RustExtractor (class) [L23-73]
    - __init__(self) -> None (method) [L26-27]
    - _query_source(self) -> str (method) [L29-73]
  📄 scala.py
    - ScalaExtractor (class) [L19-97]
    - __init__(self) -> None (method) [L22-23]
    - _query_source(self) -> str (method) [L25-97]
  📄 swift.py
    - SwiftExtractor (class) [L20-92]
    - __init__(self) -> None (method) [L23-24]
    - _query_source(self) -> str (method) [L26-92]
  📄 toml.py
    - TOMLExtractor (class) [L36-253]
    - __init__(self) -> None (method) [L39-40]
    - _extract_elements(
        self,
        source: bytes,
        filepath: str,
    ) -> list[Entity] (method) [L42-98]
    - _process_value(
        self,
        value: Any,
        filepath: str,
        name: str,
        entities: list[Entity],
        line_offset: int,
        source: bytes,
        parent_path: str = "",
    ) -> None (method) [L100-192]
    - _serialize_value(self, value: Any) -> Any (method) [L194-198]
    - _extract_references(
        self,
        source: bytes,
        filepath: str,
        entities: list[Entity],
    ) -> list[Relationship] (method) [L200-253]
  📄 typescript.py
    - TypeScriptExtractor (class) [L20-71]
    - __init__(self) -> None (method) [L23-24]
    - _query_source(self) -> str (method) [L26-71]
  📄 verilog.py
    - VerilogExtractor (class) [L22-98]
    - __init__(self) -> None (method) [L25-26]
    - _query_source(self) -> str (method) [L28-98]
  📄 yaml.py
    - YAMLExtractor (class) [L31-276]
    - __init__(self) -> None (method) [L34-35]
    - _extract_elements(
        self,
        source: bytes,
        filepath: str,
    ) -> list[Entity] (method) [L37-121]
    - _process_value(
        self,
        value: Any,
        filepath: str,
        name: str,
        entities: list[Entity],
        line_offset: int,
        source: bytes,
        parent_path: str = "",
    ) -> None (method) [L123-215]
    - _serialize_value(self, value: Any) -> Any (method) [L217-221]
    - _extract_references(
        self,
        source: bytes,
        filepath: str,
        entities: list[Entity],
    ) -> list[Relationship] (method) [L223-276]
  📄 zig.py
    - ZigExtractor (class) [L20-86]
    - __init__(self) -> None (method) [L23-24]
    - _query_source(self) -> str (method) [L26-86]

📁 batho_core/utils/ (Utilities)
  📄 dependencies.py
    - extract_package_name(dep_spec: str) -> str (function) [L37-57]
    - parse_requirements_txt(content: str) -> list[str] (function) [L65-87]
    - parse_requirements_txt_file(path: Path) -> list[str] (function) [L90-105]
    - parse_pyproject_toml(content: str) -> dict[str, Any] (function) [L113-191]
    - _detect_build_tool_from_pyproject(data: dict[str, Any]) -> str | None (function) [L194-220]
    - _parse_pyproject_toml_regex(content: str) -> dict[str, Any] (function) [L223-238]
    - parse_pyproject_toml_file(path: Path) -> dict[str, Any] (function) [L241-261]
    - parse_setup_py(content: str) -> dict[str, Any] (function) [L269-305]
    - parse_setup_py_file(path: Path) -> dict[str, Any] (function) [L308-323]
    - parse_package_json(content: str) -> dict[str, Any] (function) [L331-374]
    - parse_package_json_file(path: Path) -> dict[str, Any] (function) [L377-404]
    - _detect_node_package_manager(root_path: Path) -> str | None (function) [L407-417]
    - parse_cargo_toml(content: str) -> dict[str, Any] (function) [L425-481]
    - parse_cargo_toml_file(path: Path) -> dict[str, Any] (function) [L484-503]
    - extract_all_dependencies(base_path: Path | str) -> dict[str, list[str]] (function) [L511-575]
    - extract_dependency_names(base_path: Path | str) -> list[str] (function) [L578-615]
    deps: tomllib
  📄 encoding.py
    - read_text_with_fallback(
    filepath: Path | str,
    encodings: list[str] | None = None,
    errors: str = "replace"
) -> str (function) [L17-56]
    - decode_bytes_with_fallback(
    data: bytes,
    encodings: list[str] | None = None,
    errors: str = "replace"
) -> str (function) [L59-91]
    - normalize_to_utf8(data: bytes, errors: str = "replace") -> bytes (function) [L94-113]
  📄 hash.py
    - compute_bytes_hash(content: bytes, truncate: int | None = None) -> str (function) [L18-30]
    - compute_string_hash(content: str, encoding: str = "utf-8", truncate: int | None = None) -> str (function) [L33-45]
    - compute_file_hash(filepath: Path | str, chunk_size: int = 8192) -> str | None (function) [L48-68]
    - generate_entity_id(entity_type: str, name: str, file: str, line: int) -> str (function) [L86-103]
    - generate_relationship_id(source_id: str, target_id: str, rel_type: str) -> str (function) [L106-122]
  📄 ignore.py
    - load_ignore_spec(
    root: Path,
    extra_patterns: list[str] | None = None,
    ignore_files: list[str] | None = None,
) -> Any (function) [L138-192]
    - is_ignored(file_path: Path, root: Path, spec: Any) -> bool (function) [L195-236]
    - should_ignore_path(
    path: Path,
    root: Path,
    spec: Any | None = None,
    include_hidden: bool = True,
) -> bool (function) [L239-275]
    - walk_ignored_filtered(
    root: Path,
    spec: Any | None = None,
    skip_hidden: bool = True,
) -> Any (function) [L283-320]
    - rglob_ignored_filtered(
    root: Path,
    pattern: str,
    spec: Any | None = None,
    skip_hidden: bool = True,
) -> Any (function) [L323-346]
    deps: fnmatch, pathspec
  📄 logging.py
    - get_logger(name: str | None = None, **context: Any) -> BindableLogger (function) [L21-36]
    - get_context_logger(**context: Any) -> BindableLogger (function) [L39-42]
    - get_log_level(level_name: str = "INFO") -> int (function) [L45-55]
    - configure_logging(level: int = logging.INFO, json_format: bool | None = None) -> None (function) [L58-89]
