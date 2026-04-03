📁 (root)/
  📄 batho.py (40 entities: 2 entry_point, 38 func)
    if __name__ == "__main__":
    sys.exit(main()) [L1-1736]
    __name__ [L1734-1734]
    _generate_index_id() -> str [L70-72]
    _ensure_ctn_dir(root: Path) -> Path [L75-78]
    _load_index_metadata(ctn_dir: Path) -> dict[str, Any] [L105-122]
    _save_index_metadata(ctn_dir: Path, metadata: dict[str, Any]) -> None [L125-136]
    _write_json(path: Path, data: Any) -> None [L139-141]
    _write_text(path: Path, content: str) -> None [L144-146]
    _write_metrics(path: Path, payload: dict[str, Any]) -> None [L149-151]
    _estimate_tokens(text: str) -> int [L154-157]
    _collect_repo_metrics(
    root: Path, max_file_size_kb: int | None = None
) -> dict[str, Any] [L160-191]
    _needs_metrics_backfill(metadata: dict[str, Any]) -> bool [L194-206]
    _backfill_index_metrics(ctn_dir: Path, root: Path) -> bool [L209-241]
    _compute_repo_hash(root: Path) -> str [L244-256]
    _load_current_graph(ctn_dir: Path, index_id: str) -> InMemoryGraph | None [L259-267]
    _strip_files(graph: InMemoryGraph, file_paths: Iterable[str]) -> None [L270-284]
    _reindex_files(
    root: Path, files: list[Path], indexer: CodeGraphIndexer, graph: InMemoryGraph
) -> None [L287-311]
    _files_from_diff(diff_path: Path, root: Path) -> list[Path] [L314-446]
    cmd_index(args: argparse.Namespace) -> int [L454-656]
    cmd_stats(args: argparse.Namespace) -> int [L659-688]
    cmd_snapshots(args: argparse.Namespace) -> int [L691-696]
    cmd_diff_snapshots(args: argparse.Namespace) -> int [L699-708]
    _detect_file_changes(root: Path, files: list[Path], ctn_dir: Path, base_snapshot_id: str) -> list[FileChange] [L711-765]
    _auto_detect_changes(root: Path, ctn_dir: Path, base_snapshot_id: str, max_file_size_kb: int) -> list[FileChange] [L768-840]
    _get_latest_snapshot(ctn_dir: Path) -> str | None [L843-857]
    cmd_patch(args: argparse.Namespace) -> int [L860-881]
    _cmd_patch_index_based(args: argparse.Namespace, root: Path, ctn_dir: Path) -> int [L884-1086]
    _cmd_patch_snapshot_based(
    args: argparse.Namespace, root: Path, ctn_dir: Path
) -> int [L1089-1198]
    cmd_webhook(args: argparse.Namespace) -> int [L1201-1218]
    cmd_webhook_server(args: argparse.Namespace) -> int [L1221-1267]
    cmd_invalidate(args: argparse.Namespace) -> int [L1270-1279]
    cmd_repomap(args: argparse.Namespace) -> int [L1282-1346]
    build_parser() -> argparse.ArgumentParser [L1354-1506]
    cmd_patches(args: argparse.Namespace) -> int [L1513-1549]
    cmd_patch_info(args: argparse.Namespace) -> int [L1552-1579]
    cmd_patch_chain(args: argparse.Namespace) -> int [L1582-1611]
    cmd_apply_patch(args: argparse.Namespace) -> int [L1614-1683]
    cmd_cherry_pick(args: argparse.Namespace) -> int [L1686-1714]
    extract_patch_deltas(operation) -> dict[str, Any] [L1717-1725]
    main(argv: list[str] | None = None) -> int [L1728-1731]
    deps: argparse, batho.yaml, batho_core.config, batho_core.context.codegraph, batho_core.context.languages.detector (+18 more)
  📄 extract_graph_data.py (7 entities: 2 entry_point, 5 func)
    if __name__ == "__main__":
    main() [L1-259]
    __name__ [L257-257]
    find_workspace_root() -> str [L56-64]
    load_index(ctn_dir: Path) -> str [L67-77]
    normalize_path(file_path: str, root: str) -> str [L80-87]
    extract_graph(ctn_dir: Path, index_id: str, index_meta: dict, root: str) -> str [L90-213]
    main() -> str [L216-254]
    deps: collections, pathlib, sys, tests/testdata/outputs/repomaps/flask_sample_repomap.json, tests/testdata/repositories/flask/.readthedocs.yaml
  📄 test.py (3 entities: 2 entry_point, 1 func)
    if __name__ == "__main__":
    sys.exit(main()) [L1-87]
    __name__ [L85-85]
    main() -> int [L22-82]
    deps: pathlib, subprocess, sys
📁 batho_core/
  📄 config.py (15 entities: 5 cls, 10 func)
    LoggingConfig [L44-59]
    PathsConfig [L62-63]
    IndexerConfig [L66-87]
    FlagsConfig [L90-95]
    Config [L98-111]
    _env(name: str, default: Optional[str] = None) -> Optional[str] [L114-116]
    _env_int(name: str, default: int) -> int [L119-123]
    _env_float(name: str, default: float) -> float [L126-130]
    _env_list(name: str) -> list[str] | None [L133-140]
    _load_config_file(path: Path) -> dict[str, Any] [L143-148]
    _merge_config(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any] [L151-158]
    get_log_level() -> int [L161-162]
    get_build_info() -> dict[str, str] [L165-173]
    get_config() -> Dict[str, Any] [L176-337]
    reload_config() -> Dict[str, Any] [L345-347]
  📄 time_machine.py (46 entities: 6 cls, 32 func, 8 meth)
    timeout_handler(signum, frame) -> dict[str, Any] [L47-50]
    check_patch_limits(changes: list[FileChange], max_changes: int) -> None [L61-67]
    log_change_summary(changes: list[FileChange]) -> None [L70-82]
    change_to_dict(change: FileChange) -> dict[str, Any] [L144-152]
    dict_to_change(d: dict[str, Any]) -> FileChange [L172-177]
    _snapshot_dir(ctn_dir: Path) -> Path [L439-442]
    generate_snapshot_id() -> str [L445-447]
    create_snapshot(
    ctn_dir: Path,
    root: Path,
    graph: InMemoryGraph,
    repomap: RepoMap,
    label: str | None = None,
) -> str [L450-484]
    list_snapshots(ctn_dir: Path) -> list[dict[str, Any]] [L487-503]
    load_snapshot(ctn_dir: Path, snapshot_id: str) -> dict[str, Any] | None [L506-524]
    diff_snapshots(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any] [L527-543]
    compare_file_lists(
    current_files: dict[str, str], snapshot_files: dict[str, str]
) -> list[FileChange] [L546-580]
    aggregate_changes(changes: list[FileChange]) -> list[FileChange] [L583-590]
    parse_git_diff(diff_output: str) -> list[FileChange] [L593-614]
    compute_staleness(
    prev_entry: dict[str, Any] | None,
    current_repo_hash: str,
    stats: dict[str, Any] | None = None,
) -> float [L617-661]
    incremental_patch(
    ctn_dir: Path,
    base_snapshot_id: str,
    changes: list[FileChange],
) -> dict[str, Any] [L664-1005]
    _rollback_changes(
    graph: InMemoryGraph,
    applied_changes: list[FileChange],
    rollback_actions: list[tuple],
    updater: IncrementalGraphUpdater,
    root_path: Path,
) -> None [L1008-1042]
    _patch_dir(ctn_dir: Path) -> Path [L1049-1051]
    save_patch_operation(ctn_dir: Path, operation: PatchOperation) -> None [L1054-1067]
    load_patch_operation(ctn_dir: Path, operation_id: str) -> PatchOperation | None [L1070-1093]
    update_patch_index(ctn_dir: Path, operation: PatchOperation) -> None [L1096-1130]
    list_patch_operations(ctn_dir: Path, filters: dict[str, Any] | None = None) -> list[PatchOperation] [L1133-1164]
    get_patches_for_snapshot(ctn_dir: Path, snapshot_id: str) -> list[PatchOperation] [L1167-1176]
    cleanup_old_patches(ctn_dir: Path, config: dict[str, Any]) -> int [L1179-1218]
    build_patch_chain(ctn_dir: Path, base_snapshot_id: str, current_operation_id: str) -> list[str] [L1221-1235]
    estimate_token_changes(changes: list[FileChange]) -> int [L1238-1250]
    parse_unified_diff(diff_content: str) -> list[FileChange] [L1257-1306]
    validate_patch_compatibility(patch_data: dict[str, Any], base_snapshot_id: str, ctn_dir: Path) -> bool [L1309-1389]
    _validate_patch_dependencies(dependencies: list[str], base_snapshot_id: str, ctn_dir: Path) -> bool [L1392-1424]
    extract_patch_deltas(operation: PatchOperation) -> dict[str, Any] [L1427-1435]
    apply_deltas_to_snapshot(ctn_dir: Path, base_snapshot_id: str, deltas: dict[str, Any]) -> str | None [L1438-1473]
    webhook_stub(
    event_payload: dict[str, Any],
    headers: dict[str, str] | None = None,
) -> dict[str, Any] [L1476-1531]
    FileChangeType [L85-89]
    FileChange [L93-102]
    FileChangeSummary [L106-112]
    FileTrackingConfig [L116-122]
    PatchOperation [L126-192]
    FileChangeTracker [L195-436]
    validate(self) -> bool [L138-141]
    serialize(self) -> dict[str, Any] [L143-167]
    __init__(self, root: Path) -> dict[str, Any] [L198-200]
    load(self, cache_path: Path) -> bool [L202-214]
    save(self, cache_path: Path) -> None [L216-223]
    scan_for_changes(
        self,
        max_file_size_kb: int = 500,
        base_snapshot: dict | None = None,
        config: FileTrackingConfig | None = None,
    ) -> list[FileChange] [L225-420]
    get_changed_files(self, changes: list[FileChange]) -> list[Path] [L422-428]
    get_deleted_files(self, changes: list[FileChange]) -> list[str] [L430-436]
    deps: batho_core.context.languages.detector, batho_core.context.languages.registry, batho_core.webhook.parser
📁 batho_core/context/
  📄 categorizer.py (13 entities: 2 cls, 1 func, 10 meth)
    FileCategory [L19-29]
    FileCategorizer [L32-438]
    __str__(self) -> str [L28-29]
    __init__(self) -> None [L300-302]
    categorize(self, file_path: str) -> str [L304-346]
    _is_test_file(self, parts: list[str], filename: str, stem: str, suffix: str) -> bool [L348-365]
    _is_doc_file(self, parts: list[str], filename: str, stem: str, suffix: str) -> bool [L367-384]
    _is_config_file(self, parts: list[str], filename: str, stem: str, suffix: str) -> bool [L386-407]
    _is_source_file(self, parts: list[str], filename: str, suffix: str) -> bool [L409-419]
    _is_cache_file(self, parts: list[str]) -> bool [L421-426]
    _is_test_data_file(self, parts: list[str]) -> bool [L428-431]
    _get_folder_category(self, path: PurePosixPath, parts: list[str]) -> str [L433-438]
    categorize_file(file_path: str) -> str [L445-455]
  📄 codegraph.py (42 entities: 4 cls, 2 func, 36 meth)
    InMemoryGraph [L62-159]
    _FileStateCache [L167-431]
    IncrementalGraphUpdater [L439-638]
    CodeGraphIndexer [L646-1165]
    __init__(
        self,
        entities: dict[str, Entity] | None = None,
        relationships: list[Relationship] | None = None,
    ) -> None [L71-81]
    add_entity(self, entity: Entity) -> None [L83-84]
    add_relationship(self, relationship: Relationship) -> None [L86-89]
    get_entity(self, entity_id: str) -> Entity | None [L91-92]
    _build_index(self) -> None [L94-101]
    neighbors(self, entity_id: str, direction: str = "out") -> list[str] [L103-112]
    entities_by_file(self, file_path: str) -> list[Entity] [L114-115]
    entities_by_type(self, entity_type: EntityType) -> list[Entity] [L117-118]
    root_entities(self) -> list[Entity] [L120-121]
    stats(self) -> dict[str, Any] [L123-134]
    to_dict(self) -> dict[str, Any] [L136-141]
    __len__(self) -> int [L152-153]
    __contains__(self, entity_id: str) -> bool [L155-156]
    __repr__(self) -> str [L158-159]
    __init__(self, cache_path: Path, root: Path | None = None) -> None [L182-194]
    _load(self) -> None [L196-237]
    _mark_corrupt(self, reason: str) -> None [L239-266]
    _normalise(self, filepath: str) -> str [L272-279]
    save(self) -> None [L281-317]
    force_save(self) -> None [L319-323]
    get_cache_stats(self) -> dict[str, Any] [L325-333]
    is_cached(self, filepath: str, content_hash: str) -> bool [L335-367]
    update(
        self, filepath: str, mtime: float, content_hash: str, size: int | None = None
    ) -> None [L369-381]
    invalidate(self, filepath: str) -> None [L383-392]
    __init__(self) -> None [L447-448]
    update_entities_for_file(
        self,
        graph: InMemoryGraph,
        file_path: str,
        extractor: ASTExtractor,
    ) -> None [L450-471]
    remove_entities_for_file(self, graph: InMemoryGraph, file_path: str) -> None [L473-533]
    add_entities_for_file(
        self,
        graph: InMemoryGraph,
        file_path: str,
        extractor: ASTExtractor,
    ) -> None [L535-600]
    validate_graph_consistency(self, graph: InMemoryGraph) -> bool [L602-638]
    __init__(
        self, cache_path: str = ".ctn/file_cache.json", root: str | None = None
    ) -> None [L668-675]
    build_graph(
        self,
        root: str,
        extractor: ASTExtractor | None = None,
        extensions: list[str] | None = None,
        max_workers: int = 0,
        max_file_size_kb: int | None = None,
        verbose: bool = False,
        metrics_callback: Callable[[str, Dict[str, Any]], None] | None = None,
    ) -> InMemoryGraph [L681-1040]
    index_file(
        self,
        filepath: str,
        extractor: ASTExtractor,
        max_file_size_kb: int | None = None,
    ) -> tuple[list[Entity], list[Relationship]] [L1042-1085]
    invalidate(self, filepath: str) -> None [L1087-1093]
    stats(self) -> dict[str, int] [L1095-1098]
    get_cache_stats(self) -> dict[str, Any] [L1100-1102]
    _resolve_imports(self, graph: InMemoryGraph) -> InMemoryGraph [L1108-1165]
    _handle_file_error(
            filepath: str, error: Exception, error_type: str = "parse"
        ) -> None [L828-845]
    _process_file(
            args: tuple[Path, str],
        ) -> tuple[str, list[Entity], list[Relationship], bool] | None [L847-927]
  📄 extractor.py (20 entities: 2 cls, 4 func, 14 meth)
    _node_text(node: Node, source: bytes) -> str [L89-91]
    _clean_docstring(text: str) -> str [L94-100]
    _add(src_id: str, tgt_id: str, rel_type: RelationshipType, line: int) -> None [L323-334]
    _find_enclosing(byte_offset: int) -> Entity | None [L351-359]
    ASTExtractor [L111-523]
    MarkupConfigExtractor [L531-647]
    __init__(self, language: str) -> None [L137-148]
    parse_file(
        self,
        filepath: str,
        content: bytes,
    ) -> tuple[list[Entity], list[Relationship]] [L168-230]
    _process_captures(
        self,
        captures: dict[str, list[Node]],
        source: bytes,
        filepath: str,
    ) -> tuple[list[Entity], list[Relationship]] [L236-265]
    _build_entities(
        self,
        definition_nodes: dict[str, list[Node]],
        auxiliary_nodes: dict[tuple[str, str], list[Node]],
        source: bytes,
        filepath: str,
    ) -> list[Entity] [L267-310]
    _build_relationships(
        self,
        captures: dict[str, list[Node]],
        entities: list[Entity],
        source: bytes,
        filepath: str,
    ) -> list[Relationship] [L312-416]
    _collect_metadata_with_source(
        self,
        base_key: str,
        decl_node: Node,
        auxiliary_nodes: dict[tuple[str, str], list[Node]],
        source: bytes,
    ) -> EntityMetadata [L422-464]
    _build_signature(
        self,
        name: str,
        base_key: str,
        decl_node: Node,
        auxiliary_nodes: dict[tuple[str, str], list[Node]],
        source: bytes,
    ) -> str | None [L466-489]
    _enrich_entity(
        self,
        entity: Entity,
        decl_node: Node,
        auxiliary_nodes: dict[tuple[str, str], list[Node]],
        source: bytes,
    ) -> Entity [L508-523]
    __init__(self, language: str) -> None [L543-547]
    _query_source(self) -> str [L549-551]
    parse_file(
        self,
        filepath: str,
        content: bytes,
    ) -> tuple[list[Entity], list[Relationship]] [L570-598]
    _create_entity(
        self,
        entity_type: EntityType,
        name: str,
        filepath: str,
        start_line: int,
        end_line: int,
        start_byte: int,
        end_byte: int,
        metadata: EntityMetadata | None = None,
    ) -> Entity [L600-624]
    _create_relationship(
        self,
        source_id: str,
        target_id: str,
        rel_type: RelationshipType,
        line: int,
    ) -> Relationship [L626-639]
    _extract_key_value_pairs(
        self,
        source: bytes,
        filepath: str,
    ) -> list[Entity] [L641-647]
  📄 repomap.py (23 entities: 1 cls, 4 func, 18 meth)
    _text_tokens(text: str) -> int [L38-40]
    _rel(p: str) -> str [L93-98]
    _rel(p: str) -> str [L239-244]
    get_depth(path: str) -> int [L925-926]
    RepoMap [L49-973]
    __post_init__(self) -> None [L70-71]
    patch(self, changes: list["FileChange"], graph: "InMemoryGraph") -> None [L77-164]
    render_full(self) -> str [L288-314]
    render_compressed(
        self, budget: int, fail_on_overflow: bool = True
    ) -> tuple[str, dict[str, int]] [L316-372]
    render_json(self) -> dict[str, Any] [L374-421]
    _get_directory_label(self, dir_path: str) -> str | None [L427-447]
    group_by_directory(self) -> dict[str, list[tuple[str, list[Entity]]]] [L449-461]
    render_hierarchical(
        self,
        include_entities: bool = True,
    ) -> str [L463-513]
    render_tree_only(self) -> str [L515-517]
    categorize_files(self) -> dict[str, dict[str, list[Entity]]] [L523-539]
    render_category(
        self,
        category: str,
        include_full_entities: bool = False,
    ) -> str [L541-615]
    render_uncategorized_categories(self, include_full_entities: bool = False) -> str [L617-703]
    _group_by_directory_for_files(
        self,
        files_data: dict[str, list[Entity]],
    ) -> dict[str, list[tuple[str, list[Entity]]]] [L705-717]
    _summarize_entity_types(self, entities: list[Entity]) -> str [L719-733]
    render_overview(
        self,
        stack_info: dict[str, Any] | None = None,
        repo_name: str | None = None,
        timestamp: str | None = None,
    ) -> str [L739-882]
    _count_by_language(self) -> dict[str, int] [L884-918]
    _render_high_level_tree(self, max_depth: int = 3) -> list[str] [L920-953]
    estimate_tokens(self) -> int [L959-963]
    deps: batho_core.time_machine, datetime
  📄 schema.py (14 entities: 4 cls, 10 meth)
    EntityType [L29-55]
    RelationshipType [L58-75]
    Entity [L83-156]
    Relationship [L164-218]
    __str__(self) -> str [L54-55]
    __str__(self) -> str [L74-75]
    to_dict(self) -> dict[str, Any] [L119-132]
    __str__(self) -> str [L144-146]
    __hash__(self) -> int [L148-149]
    __eq__(self, other: object) -> bool [L151-156]
    to_dict(self) -> dict[str, Any] [L188-195]
    __str__(self) -> str [L207-208]
    __hash__(self) -> int [L210-211]
    __eq__(self, other: object) -> bool [L213-218]
  📄 stack_detector.py (21 entities: 21 func)
    _normalize_package_name(name: str) -> str [L472-474]
    _match_framework(package_name: str, framework_map: dict[str, str]) -> str | None [L477-493]
    _safe_read(path: Path) -> str [L496-500]
    _detect_package_manager(root_path: Path) -> list[str] [L503-508]
    _dedupe_preserve_order(values: list[str]) -> list[str] [L511-512]
    _detect_java(root_path: Path) -> None [L515-551]
    _scan_deps(text: str) -> None [L522-529]
    _detect_dotnet(root_path: Path) -> dict[str, Any] | None [L554-572]
    _detect_go(root_path: Path) -> dict[str, Any] | None [L575-589]
    _detect_php(root_path: Path) -> dict[str, Any] | None [L592-611]
    _detect_ruby(root_path: Path) -> dict[str, Any] | None [L614-628]
    _detect_rust(root_path: Path) -> dict[str, Any] | None [L631-660]
    _detect_mobile(root_path: Path) -> dict[str, Any] | None [L663-677]
    _detect_infra(root_path: Path) -> list[str] [L680-689]
    _extract_python_version_from_requires_python(requires_python: str) -> str [L692-705]
    _detect_build_tool(pyproject_data: dict[str, Any]) -> str | None [L708-737]
    detect_python_stack(root_dir: str | Path) -> dict[str, Any] | None [L740-873]
    detect_node_stack(root_dir: str | Path) -> dict[str, Any] | None [L876-942]
    _find_all_node_stacks(root_path: Path) -> list[dict[str, Any]] [L945-964]
    detect_stack(root_dir: str | Path) -> dict[str, Any] [L967-1056]
    _detect_special_files(
    root_path: Path,
    languages: list[str],
    frameworks: set[str],
    build_tools: list[str],
) -> None [L1059-1119]
    deps: re, tomllib
📁 batho_core/context/languages/
  📄 _common.py (6 entities: 4 cls, 2 func)
    CommonQueries [L23-133]
    ProgrammingLanguageExtractor [L141-175]
    ImportPatterns [L183-208]
    CallPatterns [L211-238]
    build_query(segments: list[str]) -> str [L246-256]
    comment_block(title: str, width: int = 70) -> str [L259-271]
  📄 bash.py (3 entities: 1 cls, 2 meth)
    BashExtractor [L17-58]
    __init__(self) -> None [L20-21]
    _query_source(self) -> str [L23-58]
  📄 c.py (3 entities: 1 cls, 2 meth)
    CExtractor [L20-59]
    __init__(self) -> None [L23-24]
    _query_source(self) -> str [L26-59]
  📄 cpp.py (3 entities: 1 cls, 2 meth)
    CppExtractor [L23-85]
    __init__(self) -> None [L26-27]
    _query_source(self) -> str [L29-85]
  📄 csharp.py (3 entities: 1 cls, 2 meth)
    CSharpExtractor [L21-84]
    __init__(self) -> None [L24-25]
    _query_source(self) -> str [L27-84]
  📄 css.py (5 entities: 1 cls, 4 meth)
    CSSExtractor [L26-242]
    __init__(self) -> None [L29-30]
    _extract_elements(
        self,
        source: bytes,
        filepath: str,
    ) -> list[Entity] [L32-163]
    _count_properties(self, properties_block: str) -> int [L165-170]
    _extract_references(
        self,
        source: bytes,
        filepath: str,
        entities: list[Entity],
    ) -> list[Relationship] [L172-242]
  📄 dart.py (3 entities: 1 cls, 2 meth)
    DartExtractor [L19-82]
    __init__(self) -> None [L22-23]
    _query_source(self) -> str [L25-82]
  📄 detector.py (15 entities: 2 cls, 7 func, 6 meth)
    DetectionResult [L41-63]
    LanguageDetector [L375-525]
    is_confident(self, threshold: float = 0.7) -> bool [L57-59]
    is_available(self) -> bool [L61-63]
    __init__(self, min_confidence: float = 0.5) -> None [L398-406]
    detect(
        self,
        filepath: Path,
        content: bytes,
    ) -> DetectionResult | None [L408-443]
    detect_with_fallback(
        self,
        filepath: Path,
        content: bytes,
    ) -> DetectionResult | None [L445-489]
    get_extractor(
        self,
        filepath: Path,
        content: bytes,
    ) -> object | None [L491-525]
    detect_by_extension(filepath: Path, content: bytes) -> DetectionResult | None [L71-98]
    detect_by_special_filename(filepath: Path, content: bytes) -> DetectionResult | None [L141-173]
    detect_by_shebang(content: bytes) -> DetectionResult | None [L204-245]
    detect_by_magic_bytes(content: bytes) -> DetectionResult | None [L265-297]
    detect_by_content_heuristics(content: bytes) -> DetectionResult | None [L334-367]
    detect_language(
    filepath: str | Path,
    content: bytes,
) -> DetectionResult | None [L547-561]
    detect_language_with_fallback(
    filepath: str | Path,
    content: bytes,
) -> DetectionResult | None [L564-578]
  📄 erlang.py (3 entities: 1 cls, 2 meth)
    ErlangExtractor [L18-74]
    __init__(self) -> None [L21-22]
    _query_source(self) -> str [L24-74]
  📄 factory.py (8 entities: 1 cls, 5 func, 2 meth)
    ConfigurableExtractor [L33-59]
    __init__(self, language: str, query_source: str) -> None [L46-55]
    _query_source(self) -> str [L57-59]
    create_extractor(language: str, query_source: str) -> ASTExtractor [L62-80]
    get_extractor(language: str) -> ASTExtractor | None [L430-460]
    register_extractor(language: str, query_source: str) -> None [L463-481]
    list_supported_languages() -> list[str] [L484-491]
    clear_extractor_cache() -> None [L494-500]
  📄 go.py (3 entities: 1 cls, 2 meth)
    GoExtractor [L21-65]
    __init__(self) -> None [L24-25]
    _query_source(self) -> str [L27-65]
  📄 hack.py (3 entities: 1 cls, 2 meth)
    HackExtractor [L23-81]
    __init__(self) -> None [L26-27]
    _query_source(self) -> str [L29-81]
  📄 haskell.py (3 entities: 1 cls, 2 meth)
    HaskellExtractor [L18-85]
    __init__(self) -> None [L21-22]
    _query_source(self) -> str [L24-85]
  📄 hcl.py (6 entities: 1 cls, 5 meth)
    HCLExtractor [L24-353]
    __init__(self) -> None [L27-28]
    _extract_elements(
        self,
        source: bytes,
        filepath: str,
    ) -> list[Entity] [L30-172]
    _find_block_end(self, content: str, start_pos: int, brace_positions: list) -> int [L174-186]
    _extract_attributes(
        self,
        content: str,
        filepath: str,
        parent_path: str,
        entities: list[Entity],
        line_offset: int,
        get_line_from_offset: Any,
        exclude_blocks: bool = False,
    ) -> None [L188-234]
    _extract_references(
        self,
        source: bytes,
        filepath: str,
        entities: list[Entity],
    ) -> list[Relationship] [L236-353]
  📄 html.py (5 entities: 1 cls, 4 meth)
    HTMLExtractor [L27-249]
    __init__(self) -> None [L30-31]
    _extract_elements(
        self,
        source: bytes,
        filepath: str,
    ) -> list[Entity] [L33-150]
    _extract_title(self, content: str) -> str | None [L152-157]
    _extract_references(
        self,
        source: bytes,
        filepath: str,
        entities: list[Entity],
    ) -> list[Relationship] [L159-249]
  📄 java.py (3 entities: 1 cls, 2 meth)
    JavaExtractor [L18-63]
    __init__(self) -> None [L21-22]
    _query_source(self) -> str [L24-63]
  📄 javascript.py (3 entities: 1 cls, 2 meth)
    JavaScriptExtractor [L22-62]
    __init__(self) -> None [L25-26]
    _query_source(self) -> str [L28-62]
  📄 json.py (6 entities: 1 cls, 5 meth)
    JSONExtractor [L24-236]
    __init__(self) -> None [L27-28]
    _extract_elements(
        self,
        source: bytes,
        filepath: str,
    ) -> list[Entity] [L30-79]
    _process_value(
        self,
        value: Any,
        filepath: str,
        name: str,
        entities: list[Entity],
        line_offset: int,
        source: bytes,
        parent_path: str = "",
    ) -> None [L81-170]
    _serialize_value(self, value: Any) -> Any [L172-176]
    _extract_references(
        self,
        source: bytes,
        filepath: str,
        entities: list[Entity],
    ) -> list[Relationship] [L178-236]
  📄 julia.py (3 entities: 1 cls, 2 meth)
    JuliaExtractor [L18-81]
    __init__(self) -> None [L21-22]
    _query_source(self) -> str [L24-81]
  📄 kotlin.py (3 entities: 1 cls, 2 meth)
    KotlinExtractor [L19-74]
    __init__(self) -> None [L22-23]
    _query_source(self) -> str [L25-74]
  📄 lua.py (3 entities: 1 cls, 2 meth)
    LuaExtractor [L17-67]
    __init__(self) -> None [L20-21]
    _query_source(self) -> str [L23-67]
  📄 markdown.py (5 entities: 1 cls, 4 meth)
    MarkdownExtractor [L26-352]
    __init__(self) -> None [L29-30]
    _extract_elements(
        self,
        source: bytes,
        filepath: str,
    ) -> list[Entity] [L32-228]
    _extract_frontmatter(self, content: str) -> dict[str, Any] | None [L230-256]
    _extract_references(
        self,
        source: bytes,
        filepath: str,
        entities: list[Entity],
    ) -> list[Relationship] [L258-352]
  📄 objectivec.py (3 entities: 1 cls, 2 meth)
    ObjectiveCExtractor [L21-105]
    __init__(self) -> None [L24-25]
    _query_source(self) -> str [L27-105]
  📄 ocaml.py (3 entities: 1 cls, 2 meth)
    OCamlExtractor [L18-85]
    __init__(self) -> None [L21-22]
    _query_source(self) -> str [L24-85]
  📄 perl.py (3 entities: 1 cls, 2 meth)
    PerlExtractor [L17-73]
    __init__(self) -> None [L20-21]
    _query_source(self) -> str [L23-73]
  📄 php.py (3 entities: 1 cls, 2 meth)
    PHPExtractor [L19-72]
    __init__(self) -> None [L22-23]
    _query_source(self) -> str [L25-72]
  📄 python.py (3 entities: 1 cls, 2 meth)
    PythonExtractor [L22-91]
    __init__(self) -> None [L25-26]
    _query_source(self) -> str [L28-91]
  📄 r.py (3 entities: 1 cls, 2 meth)
    RExtractor [L16-71]
    __init__(self) -> None [L19-20]
    _query_source(self) -> str [L22-71]
  📄 registry.py (9 entities: 9 func)
    is_language_available(language: str) -> bool [L235-276]
    _build_class_map() -> None [L283-363]
    _get_extractor_instance(language: str) -> ASTExtractor | None [L373-409]
    _discover_language_modules() -> None [L412-504]
    discover_and_register_all() -> None [L507-517]
    get_extractor(extension: str) -> ASTExtractor | None [L520-558]
    get_extractor_for_language(language: str) -> ASTExtractor | None [L561-575]
    get_language_for_extension(extension: str) -> str | None [L578-588]
    get_extensions_for_language(language: str) -> list[str] [L591-601]
  📄 ruby.py (3 entities: 1 cls, 2 meth)
    RubyExtractor [L21-59]
    __init__(self) -> None [L24-25]
    _query_source(self) -> str [L27-59]
  📄 rust.py (3 entities: 1 cls, 2 meth)
    RustExtractor [L23-73]
    __init__(self) -> None [L26-27]
    _query_source(self) -> str [L29-73]
  📄 scala.py (3 entities: 1 cls, 2 meth)
    ScalaExtractor [L19-97]
    __init__(self) -> None [L22-23]
    _query_source(self) -> str [L25-97]
  📄 swift.py (3 entities: 1 cls, 2 meth)
    SwiftExtractor [L20-92]
    __init__(self) -> None [L23-24]
    _query_source(self) -> str [L26-92]
  📄 toml.py (6 entities: 1 cls, 5 meth)
    TOMLExtractor [L36-256]
    __init__(self) -> None [L39-40]
    _extract_elements(
        self,
        source: bytes,
        filepath: str,
    ) -> list[Entity] [L42-98]
    _process_value(
        self,
        value: Any,
        filepath: str,
        name: str,
        entities: list[Entity],
        line_offset: int,
        source: bytes,
        parent_path: str = "",
    ) -> None [L100-192]
    _serialize_value(self, value: Any) -> Any [L194-198]
    _extract_references(
        self,
        source: bytes,
        filepath: str,
        entities: list[Entity],
    ) -> list[Relationship] [L200-256]
  📄 typescript.py (3 entities: 1 cls, 2 meth)
    TypeScriptExtractor [L20-71]
    __init__(self) -> None [L23-24]
    _query_source(self) -> str [L26-71]
  📄 verilog.py (3 entities: 1 cls, 2 meth)
    VerilogExtractor [L22-98]
    __init__(self) -> None [L25-26]
    _query_source(self) -> str [L28-98]
  📄 yaml.py (6 entities: 1 cls, 5 meth)
    YAMLExtractor [L30-278]
    __init__(self) -> None [L33-34]
    _extract_elements(
        self,
        source: bytes,
        filepath: str,
    ) -> list[Entity] [L36-120]
    _process_value(
        self,
        value: Any,
        filepath: str,
        name: str,
        entities: list[Entity],
        line_offset: int,
        source: bytes,
        parent_path: str = "",
    ) -> None [L122-214]
    _serialize_value(self, value: Any) -> Any [L216-220]
    _extract_references(
        self,
        source: bytes,
        filepath: str,
        entities: list[Entity],
    ) -> list[Relationship] [L222-278]
  📄 zig.py (3 entities: 1 cls, 2 meth)
    ZigExtractor [L20-86]
    __init__(self) -> None [L23-24]
    _query_source(self) -> str [L26-86]
📁 batho_core/utils/ (Utilities)
  📄 dependencies.py (16 entities: 16 func)
    extract_package_name(dep_spec: str) -> str [L38-58]
    parse_requirements_txt(content: str) -> list[str] [L66-88]
    parse_requirements_txt_file(path: Path) -> list[str] [L91-106]
    parse_pyproject_toml(content: str) -> dict[str, Any] [L114-193]
    _detect_build_tool_from_pyproject(data: dict[str, Any]) -> str | None [L196-222]
    _parse_pyproject_toml_regex(content: str) -> dict[str, Any] [L225-240]
    parse_pyproject_toml_file(path: Path) -> dict[str, Any] [L243-263]
    parse_setup_py(content: str) -> dict[str, Any] [L271-303]
    parse_setup_py_file(path: Path) -> dict[str, Any] [L306-321]
    parse_package_json(content: str) -> dict[str, Any] [L329-372]
    parse_package_json_file(path: Path) -> dict[str, Any] [L375-402]
    _detect_node_package_manager(root_path: Path) -> str | None [L405-415]
    parse_cargo_toml(content: str) -> dict[str, Any] [L423-480]
    parse_cargo_toml_file(path: Path) -> dict[str, Any] [L483-502]
    extract_all_dependencies(base_path: Path | str) -> dict[str, list[str]] [L510-574]
    extract_dependency_names(base_path: Path | str) -> list[str] [L577-614]
    deps: tomllib
  📄 encoding.py (3 entities: 3 func)
    read_text_with_fallback(
    filepath: Path | str, encodings: list[str] | None = None, errors: str = "replace"
) -> str [L16-51]
    decode_bytes_with_fallback(
    data: bytes, encodings: list[str] | None = None, errors: str = "replace"
) -> str [L54-84]
    normalize_to_utf8(data: bytes, errors: str = "replace") -> bytes [L87-106]
  📄 file_io.py (5 entities: 5 func)
    read_file_bytes(
    filepath: Union[str, Path],
    max_size_kb: int | None = None,
    normalize_encoding: bool = True,
    detect_binary: bool = False,
) -> bytes | None [L28-83]
    read_file_text(
    filepath: Union[str, Path],
    max_size_kb: int | None = None,
    encoding: str = "utf-8",
    errors: str = "replace",
) -> str | None [L86-117]
    write_atomically(
    path: Union[str, Path],
    content: Union[str, bytes, dict],
    *,
    is_json: bool = False,
    encoding: str = "utf-8",
    indent: int | None = 2,
    ensure_parent: bool = True,
) -> bool [L120-189]
    _read_file_bytes(filepath: str, max_size_kb: int = 500) -> bytes | None [L193-195]
    _read_file_content(filepath: str, max_size_kb: int | None = None) -> bytes | None [L198-200]
    deps: batho_core.utils.encoding
  📄 file_lock.py (12 entities: 2 cls, 10 meth)
    FileLockError [L19-21]
    FileLock [L24-231]
    __init__(self, lock_path: Path, timeout: float = 30.0, poll_interval: float = 0.1) -> bool [L32-44]
    _is_process_alive(self, pid: int) -> bool [L46-51]
    _read_lock_info(self) -> Optional[tuple[int, float]] [L53-77]
    _is_lock_stale(self, pid: int, timestamp: float) -> bool [L79-101]
    _cleanup_stale_lock(self) -> bool [L103-124]
    acquire(self) -> bool [L126-193]
    release(self) -> None [L195-217]
    __enter__(self) -> bool [L219-222]
    __exit__(self, exc_type, exc_val, exc_tb) -> bool [L224-226]
    __del__(self) -> bool [L228-231]
  📄 hash.py (7 entities: 7 func)
    _calculate_shannon_entropy(data: bytes) -> float [L53-66]
    _is_binary(content: bytes) -> bool [L69-95]
    compute_bytes_hash(content: bytes, truncate: int | None = None) -> str [L98-110]
    compute_string_hash(
    content: str, encoding: str = "utf-8", truncate: int | None = None
) -> str [L113-127]
    compute_file_hash(filepath: Path | str, chunk_size: int = 8192) -> str | None [L130-160]
    generate_entity_id(entity_type: str, name: str, file: str, line: int) -> str [L178-195]
    generate_relationship_id(source_id: str, target_id: str, rel_type: str) -> str [L198-214]
  📄 ignore.py (5 entities: 5 func)
    load_ignore_spec(
    root: Path,
    extra_patterns: list[str] | None = None,
    ignore_files: list[str] | None = None,
) -> Any [L138-196]
    is_ignored(file_path: Path, root: Path, spec: Any) -> bool [L199-240]
    should_ignore_path(
    path: Path,
    root: Path,
    spec: Any | None = None,
    include_hidden: bool = True,
) -> bool [L243-279]
    walk_ignored_filtered(
    root: Path,
    spec: Any | None = None,
    skip_hidden: bool = True,
) -> Any [L287-322]
    rglob_ignored_filtered(
    root: Path,
    pattern: str,
    spec: Any | None = None,
    skip_hidden: bool = True,
) -> Any [L325-348]
    deps: fnmatch, pathspec
  📄 logging.py (4 entities: 4 func)
    get_logger(name: str | None = None, **context: Any) -> BindableLogger [L21-36]
    get_context_logger(**context: Any) -> BindableLogger [L39-42]
    get_log_level(level_name: str = "INFO") -> int [L45-55]
    configure_logging(level: int = logging.INFO, json_format: bool | None = None) -> None [L58-93]
  📄 memory_monitor.py (9 entities: 2 cls, 3 func, 4 meth)
    MemoryStats [L20-26]
    MemoryMonitor [L29-147]
    __init__(self, warning_threshold_mb: float = 500.0, critical_threshold_mb: float = 1000.0) -> MemoryStats [L32-45]
    get_memory_stats(self) -> MemoryStats [L47-100]
    check_memory_usage(self, operation: str = "unknown") -> Optional[str] [L102-129]
    log_memory_stats(self, operation: str) -> None [L131-147]
    force_garbage_collection() -> Dict[str, Any] [L212-243]
    get_system_memory_info() -> Dict[str, Any] [L246-268]
    check_memory_pressure(threshold_percent: float = 90.0) -> bool [L271-286]
  📄 patch_errors.py (19 entities: 7 cls, 12 meth)
    PatchValidationError [L25-30]
    PatchConsistencyError [L33-38]
    PatchSnapshotError [L41-46]
    PatchFileError [L49-57]
    PatchTimeoutError [L60-65]
    PatchAuditLogEntry [L69-109]
    PatchAuditLogger [L112-215]
    __init__(self, message: str, details: dict[str, Any] | None = None) -> None [L28-30]
    __init__(self, message: str, inconsistencies: list[str] | None = None) -> None [L36-38]
    __init__(self, message: str, snapshot_id: str | None = None) -> None [L44-46]
    __init__(
        self, message: str, file_path: str | None = None, operation: str | None = None
    ) -> None [L52-57]
    __init__(self, message: str, timeout_seconds: float | None = None) -> None [L63-65]
    to_dict(self) -> dict[str, Any] [L83-95]
    complete(
        self,
        success: bool,
        new_snapshot_id: str | None = None,
        error_message: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None [L97-109]
    __init__(self, log_file: Path | None = None) -> None [L115-117]
    start_operation(
        self,
        operation_id: str,
        operation_type: str,
        base_snapshot_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> PatchAuditLogEntry [L119-144]
    complete_operation(
        self,
        operation_id: str,
        success: bool,
        new_snapshot_id: str | None = None,
        error_message: str | None = None,
        change_count: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> None [L146-172]
    _write_audit_log(self) -> None [L174-193]
    get_operation_history(
        self,
        operation_type: str | None = None,
        base_snapshot_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]] [L195-215]
  📄 path_sanitizer.py (7 entities: 1 cls, 6 func)
    PathSecurityError [L15-17]
    sanitize_path(
    path: Union[str, Path], 
    base_dir: Optional[Union[str, Path]] = None,
    allow_absolute: bool = False
) -> Path [L20-57]
    _is_path_safe(path: Path, base_dir: Path) -> bool [L60-75]
    safe_join(base_dir: Union[str, Path], *paths: Union[str, Path]) -> Path [L78-106]
    sanitize_diff_path(diff_path: str, base_dir: Union[str, Path]) -> Path [L109-157]
    is_safe_filename(filename: str) -> bool [L160-192]
    validate_path_list(paths: list[Union[str, Path]], base_dir: Union[str, Path]) -> list[Path] [L195-212]
📁 batho_core/webhook/
  📄 auth.py (2 entities: 2 func)
    verify_github_signature(payload: bytes, signature: str, secret: str | None) -> bool [L9-34]
    verify_gitlab_token(token: str, secret: str | None) -> bool [L37-49]
  📄 config.py (10 entities: 6 cls, 4 meth)
    ServerConfig [L13-19]
    RepositoryConfig [L23-33]
    ProcessingConfig [L37-46]
    RateLimitConfig [L50-53]
    LoggingConfig [L57-60]
    WebhookConfig [L64-144]
    get_github_secret(self) -> Optional[str] [L76-81]
    get_gitlab_token(self) -> Optional[str] [L83-88]
    get_allowed_ips(self) -> list[str] [L90-94]
    get_repo_rate_limit_per_hour(self) -> int [L96-99]
  📄 handler.py (17 entities: 2 cls, 15 meth)
    WebhookResult [L23-40]
    WebhookHandler [L43-235]
    to_response(self) -> dict[str, Any] [L32-40]
    __init__(self, config: WebhookConfig, repo_path: Path) -> WebhookResult [L46-51]
    start(self) -> None [L53-54]
    stop(self) -> None [L56-57]
    verify_github_signature(self, payload: bytes, signature: str) -> bool [L59-60]
    verify_gitlab_token(self, token: str) -> bool [L62-63]
    handle_webhook(
        self,
        payload_bytes: bytes,
        headers: dict[str, str],
        source_ip: str | None = None,
    ) -> WebhookResult [L65-106]
    handle_github_webhook(
        self,
        payload_bytes: bytes,
        signature: str,
        headers: dict[str, str],
        source_ip: str | None = None,
    ) -> WebhookResult [L108-119]
    handle_gitlab_webhook(
        self,
        payload_bytes: bytes,
        token: str,
        headers: dict[str, str],
        source_ip: str | None = None,
    ) -> WebhookResult [L121-132]
    get_health(self) -> dict[str, Any] [L134-139]
    _authenticate(self, payload: bytes, headers: dict[str, str]) -> WebhookResult | None [L141-155]
    _is_allowed_ip(self, source_ip: str | None) -> bool [L157-178]
    _extract_repository(self, payload: dict[str, Any]) -> str [L180-193]
    _is_rate_limited(self, repository: str) -> bool [L195-208]
    _check_and_track_delivery(self, headers: dict[str, str]) -> WebhookResult | None [L210-227]
  📄 parser.py (8 entities: 3 cls, 5 func)
    WebhookPlatform [L12-15]
    WebhookEventType [L18-29]
    WebhookEvent [L33-41]
    parse_webhook_event(payload: dict[str, Any], headers: dict[str, str]) -> WebhookEvent [L44-62]
    _header(headers: dict[str, str], name: str) -> str | None [L65-70]
    _require(payload: dict[str, Any], key: str) -> Any [L73-76]
    _parse_github_event(payload: dict[str, Any], event: str) -> WebhookEvent [L79-167]
    _parse_gitlab_event(payload: dict[str, Any], event: str) -> WebhookEvent [L170-258]
  📄 processor.py (8 entities: 1 cls, 7 meth)
    WebhookProcessor [L18-219]
    __init__(self, config: WebhookConfig, repo_path: Path) -> dict[str, Any] [L21-26]
    process_webhook(
        self,
        payload: dict[str, Any],
        headers: dict[str, str],
    ) -> dict[str, Any] [L28-100]
    start(self) -> None [L102-105]
    stop(self) -> None [L107-110]
    _handle_queue_item(self, item: QueueItem) -> bool [L112-176]
    _find_latest_snapshot(self) -> Optional[str] [L178-187]
    _validate_event(self, event: WebhookEvent) -> dict[str, str] | None [L189-206]
    deps: batho_core.time_machine
  📄 queue.py (11 entities: 2 cls, 9 meth)
    QueueItem [L24-52]
    WebhookQueue [L58-248]
    to_payload(self) -> dict[str, Any] [L33-41]
    __init__(self, config: Optional[ProcessingConfig] = None, max_size: int = 1000) -> dict[str, Any] [L61-78]
    _initialize_backend(self) -> None [L80-123]
    put(self, item: QueueItem) -> bool [L125-134]
    start_processing(self, handler: Callable[[QueueItem], bool]) -> None [L136-157]
    stop_processing(self) -> None [L159-173]
    _dispatch(self, handler: Callable[[QueueItem], bool], item: QueueItem) -> bool [L175-186]
    _process_items(self, handler: Callable[[QueueItem], bool]) -> None [L188-237]
    get_stats(self) -> dict[str, int] [L239-248]
  📄 server.py (13 entities: 2 cls, 1 func, 10 meth)
    create_webhook_app(handler: WebhookHandler, config: WebhookConfig) [L33-51]
    _FallbackWebhookRequestHandler [L54-98]
    WebhookServer [L101-186]
    do_POST(self) -> None [L60-78]
    do_GET(self) -> None [L80-89]
    _send_json(self, status_code: int, payload: dict) -> None [L91-95]
    log_message(self, format: str, *args) -> None [L97-98]
    __init__(self, config: WebhookConfig, repo_path: Path) -> None [L104-114]
    start(self) -> None [L116-130]
    stop(self) -> None [L132-146]
    serve_forever(self) -> None [L148-157]
    _start_fastapi(self) -> None [L159-172]
    _start_fallback_server(self) -> None [L174-186]