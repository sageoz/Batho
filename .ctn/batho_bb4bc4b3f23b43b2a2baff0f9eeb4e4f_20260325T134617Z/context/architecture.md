📁 (root)/
  📄 batho.py
    - if __name__ == "__main__":
    sys.exit(main()) (entry_point) [L1-928]
    - _generate_index_id() -> str (function) [L61-63]
    - _ensure_ctn_dir(root: Path) -> Path (function) [L66-69]
    - _load_index_metadata(ctn_dir: Path) -> dict[str, Any] (function) [L96-113]
    - _save_index_metadata(ctn_dir: Path, metadata: dict[str, Any]) -> None (function) [L116-127]
    - _write_json(path: Path, data: Any) -> None (function) [L130-132]
    - _write_text(path: Path, content: str) -> None (function) [L135-137]
    - _write_metrics(path: Path, payload: dict[str, Any]) -> None (function) [L140-142]
    - _estimate_tokens(text: str) -> int (function) [L145-148]
    - _collect_repo_metrics(root: Path, max_file_size_kb: int | None = None) -> dict[str, Any] (function) [L151-180]
    - _needs_metrics_backfill(metadata: dict[str, Any]) -> bool (function) [L183-195]
    - _backfill_index_metrics(ctn_dir: Path, root: Path) -> bool (function) [L198-228]
    - _compute_repo_hash(root: Path) -> str (function) [L231-243]
    - _load_current_graph(ctn_dir: Path, index_id: str) -> InMemoryGraph | None (function) [L246-254]
    - _strip_files(graph: InMemoryGraph, file_paths: Iterable[str]) -> None (function) [L257-267]
    - _reindex_files(
    root: Path, files: list[Path], indexer: CodeGraphIndexer, graph: InMemoryGraph
) -> None (function) [L270-294]
    - _files_from_diff(diff_path: Path, root: Path) -> list[Path] (function) [L297-312]
    - cmd_index(args: argparse.Namespace) -> int (function) [L320-547]
    - cmd_stats(args: argparse.Namespace) -> int (function) [L550-578]
    - cmd_snapshots(args: argparse.Namespace) -> int (function) [L581-586]
    - cmd_diff_snapshots(args: argparse.Namespace) -> int (function) [L589-598]
    - cmd_patch(args: argparse.Namespace) -> int (function) [L601-729]
    - cmd_webhook(args: argparse.Namespace) -> int (function) [L732-740]
    - cmd_invalidate(args: argparse.Namespace) -> int (function) [L743-752]
    - cmd_c4(args: argparse.Namespace) -> int (function) [L755-847]
    - build_parser() -> argparse.ArgumentParser (function) [L855-917]
    - main(argv: list[str] | None = None) -> int (function) [L920-923]
    - __name__ (entry_point) [L926-926]
    deps: argparse, batho_core.config, batho_core.context.c4_generator, batho_core.context.c4_structurizr, batho_core.context.categorizer, batho_core.context.codegraph, batho_core.context.languages.detector, batho_core.context.languages.registry, batho_core.context.repomap, batho_core.context.stack_detector, batho_core.time_machine, batho_core.utils.file_io, batho_core.utils.hash, batho_core.utils.ignore, contextlib, datetime, pathlib, sys, tests/testdata/outputs/configs/invalid_configs/schema_violation.json, tests/testdata/repositories/flask/.readthedocs.yaml, tests/testdata/repositories/flask/repository_metadata.json, time, traceback, typing, uuid
  📄 test.py
    - if __name__ == "__main__":
    sys.exit(main()) (entry_point) [L1-87]
    - main() -> int (function) [L22-82]
    - __name__ (entry_point) [L85-85]
    deps: pathlib, subprocess, sys

📁 batho_core/
  📄 config.py
    - LoggingConfig (class) [L45-60]
    - PathsConfig (class) [L63-64]
    - IndexerConfig (class) [L67-88]
    - FlagsConfig (class) [L91-93]
    - Config (class) [L96-106]
    - _env(name: str, default: Optional[str] = None) -> Optional[str] (function) [L109-111]
    - _env_int(name: str, default: int) -> int (function) [L114-118]
    - _env_float(name: str, default: float) -> float (function) [L121-125]
    - _env_list(name: str) -> list[str] | None (function) [L128-135]
    - _load_config_file(path: Path) -> dict[str, Any] (function) [L138-149]
    - _merge_config(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any] (function) [L152-159]
    - get_log_level() -> int (function) [L162-163]
    - get_build_info() -> dict[str, str] (function) [L166-174]
    - get_config(config_file: str | None = None) -> Dict[str, Any] (function) [L177-282]
    - reload_config(config_file: str | None = None) -> Dict[str, Any] (function) [L290-292]
    deps: tests/testdata/repositories/flask/repository_metadata.json
  📄 time_machine.py
    - _snapshot_dir(ctn_dir: Path) -> Path (function) [L26-29]
    - generate_snapshot_id() -> str (function) [L32-34]
    - create_snapshot(
    ctn_dir: Path,
    root: Path,
    graph: InMemoryGraph,
    repomap: RepoMap,
    label: str | None = None,
) -> str (function) [L37-71]
    - list_snapshots(ctn_dir: Path) -> list[dict[str, Any]] (function) [L74-90]
    - load_snapshot(ctn_dir: Path, snapshot_id: str) -> dict[str, Any] | None (function) [L93-111]
    - diff_snapshots(rep_json: dict[str, Any]) -> dict[str, Any] (function) [L114-131]
    - _files(rep_json: dict[str, Any]) -> set[str] (function) [L115-116]
    - compute_staleness(
    prev_entry: dict[str, Any] | None, current_repo_hash: str, stats: dict[str, Any] | None = None
) -> float (function) [L134-171]
    - incremental_patch_stub(ctn_dir: Path, changed_files: Iterable[Path]) -> dict[str, Any] (function) [L174-187]
    - webhook_stub(event_payload: dict[str, Any]) -> dict[str, Any] (function) [L190-202]

📁 batho_core/context/
  📄 c4_generator.py
    - C4Generator (class) [L20-767]
    - __init__(self, ctn_dir: Path, index_id: str) -> Dict[str, float] (method) [L23-35]
    - _load_graph(self) -> Dict[str, Any] (method) [L37-42]
    - _load_repomap(self) -> Dict[str, Any] (method) [L44-49]
    - _load_index_metadata(self) -> Dict[str, Any] (method) [L51-57]
    - generate_c4_model(self) -> Dict[str, Any] (method) [L59-89]
    - _analyze_imports(self) -> Dict[str, Any] (method) [L91-179]
    - _calculate_entity_importance(self) -> Dict[str, float] (method) [L181-227]
    - _generate_people(self) -> List[Dict[str, Any]] (method) [L229-262]
    - _generate_software_systems(self) -> List[Dict[str, Any]] (method) [L264-298]
    - _generate_containers(self) -> List[Dict[str, Any]] (method) [L300-374]
    - _generate_components(self) -> List[Dict[str, Any]] (method) [L376-434]
    - _map_file_to_container(self, file_path: str) -> str | None (method) [L436-453]
    - _get_language_from_file(self, file_path: str) -> str (method) [L455-471]
    - _generate_views(self) -> Dict[str, Any] (method) [L473-524]
    - _generate_documentation(self) -> Dict[str, Any] (method) [L526-532]
    - _generate_llm_extensions(self) -> Dict[str, Any] (method) [L534-583]
    - _infer_entity_purpose(self, entity: Dict[str, Any]) -> str (method) [L585-606]
    - _estimate_complexity(self, entity: Dict[str, Any]) -> str (method) [L608-619]
    - _analyze_data_flow(self) -> List[Dict[str, Any]] (method) [L621-641]
    - _classify_data_flow(self, source: Dict[str, Any], target: Dict[str, Any]) -> str (method) [L643-657]
    - _identify_extension_points(self) -> List[Dict[str, Any]] (method) [L659-683]
    - _calculate_complexity_metrics(self) -> Dict[str, Any] (method) [L685-708]
    - _infer_business_capabilities(self) -> List[str] (method) [L710-736]
    - _identify_tech_debt(self) -> List[Dict[str, Any]] (method) [L738-767]
  📄 c4_llm_extensions.py
    - LLMExtensionGenerator (class) [L15-1268]
    - __init__(self, graph: Dict[str, Any], repomap: Dict[str, Any], 
                 index_metadata: Dict[str, Any]) -> List[Dict[str, str]] (method) [L18-28]
    - generate_extensions(self) -> Dict[str, Any] (method) [L30-48]
    - _generate_executive_summary(self) -> Dict[str, Any] (method) [L50-81]
    - _generate_architecture_overview(self) -> Dict[str, Any] (method) [L83-107]
    - _analyze_key_workflows(self) -> List[Dict[str, Any]] (method) [L109-122]
    - _analyze_data_architecture(self) -> Dict[str, Any] (method) [L124-145]
    - _generate_api_catalog(self) -> List[Dict[str, Any]] (method) [L147-152]
    - _identify_business_domains(self) -> Dict[str, Any] (method) [L154-163]
    - _assess_technical_risks(self) -> List[Dict[str, Any]] (method) [L165-202]
    - _analyze_scalability(self) -> Dict[str, Any] (method) [L204-213]
    - _assess_security_posture(self) -> Dict[str, Any] (method) [L215-225]
    - _generate_dev_guidelines(self) -> Dict[str, Any] (method) [L227-236]
    - _generate_onboarding_guide(self) -> Dict[str, Any] (method) [L238-247]
    - _generate_change_impact_analysis(self) -> Dict[str, Any] (method) [L249-261]
    - _identify_performance_hotspots(self) -> List[Dict[str, Any]] (method) [L263-297]
    - _map_integration_points(self) -> List[Dict[str, Any]] (method) [L299-334]
    - _generate_glossary(self) -> Dict[str, str] (method) [L336-362]
    - _infer_system_purpose(self) -> str (method) [L366-377]
    - _assess_complexity_level(self) -> str (method) [L379-391]
    - _estimate_team_size(self) -> str (method) [L393-404]
    - _infer_business_value(self) -> str (method) [L406-417]
    - _detect_architectural_patterns(self) -> Dict[str, Any] (method) [L419-442]
    - _has_mvc_pattern(self) -> bool (method) [L444-454]
    - _has_layered_architecture(self) -> bool (method) [L456-463]
    - _has_microservice_patterns(self) -> bool (method) [L465-471]
    - _has_event_driven_patterns(self) -> bool (method) [L473-480]
    - _trace_workflow(self, entry_point: Dict[str, Any]) -> Dict[str, Any] | None (method) [L482-498]
    - _find_data_models(self) -> List[Dict[str, Any]] (method) [L500-519]
    - _extract_api_endpoints(self) -> List[Dict[str, Any]] (method) [L521-539]
    - _cluster_by_business_domain(self) -> Dict[str, List[str]] (method) [L541-571]
    - _infer_term_meaning(self, term: str, entity: Dict[str, Any]) -> str | None (method) [L573-592]
    - _identify_architectural_layers(self) -> List[Dict[str, str]] (method) [L594-619]
    - _analyze_dependencies(self) -> Dict[str, Any] (method) [L621-648]
    - _extract_design_principles(self) -> List[str] (method) [L650-670]
    - _get_presentation_tech(self) -> List[str] (method) [L672-682]
    - _get_business_tech(self) -> List[str] (method) [L684-694]
    - _get_data_tech(self) -> List[str] (method) [L696-708]
    - _get_infrastructure_tech(self) -> List[str] (method) [L710-720]
    - _identify_data_patterns(self, data_models: List[Dict[str, Any]]) -> List[str] (method) [L722-739]
    - _trace_data_flow(self) -> List[Dict[str, Any]] (method) [L741-755]
    - _identify_persistence_mechanisms(self) -> List[str] (method) [L757-769]
    - _assess_data_integrity(self) -> Dict[str, str] (method) [L771-777]
    - _identify_caching_strategy(self) -> str (method) [L779-789]
    - _check_outdated_dependencies(self) -> List[str] (method) [L791-794]
    - _find_complex_components(self) -> List[Dict[str, Any]] (method) [L796-811]
    - _check_security_patterns(self) -> List[str] (method) [L813-828]
    - _analyze_coupling(self) -> Dict[str, Any] (method) [L830-860]
    - _analyze_cohesion(self) -> Dict[str, Any] (method) [L862-888]
    - _identify_high_impact_areas(self) -> List[Dict[str, Any]] (method) [L890-915]
    - _map_change_propagation(self) -> List[Dict[str, Any]] (method) [L917-935]
    - _recommend_testing_strategy(self) -> Dict[str, Any] (method) [L937-944]
    - _identify_scalability_limitations(self) -> List[str] (method) [L946-960]
    - _identify_scaling_factors(self) -> List[str] (method) [L962-969]
    - _identify_bottlenecks(self) -> List[Dict[str, Any]] (method) [L971-984]
    - _generate_scalability_recommendations(self) -> List[str] (method) [L986-993]
    - _assess_horizontal_scaling(self) -> Dict[str, Any] (method) [L995-1009]
    - _assess_vertical_scaling(self) -> Dict[str, Any] (method) [L1011-1020]
    - _check_authentication(self) -> Dict[str, Any] (method) [L1022-1036]
    - _check_authorization(self) -> Dict[str, Any] (method) [L1038-1048]
    - _check_data_protection(self) -> Dict[str, Any] (method) [L1050-1058]
    - _check_input_validation(self) -> Dict[str, Any] (method) [L1060-1068]
    - _check_dependency_security(self) -> Dict[str, Any] (method) [L1070-1075]
    - _check_compliance(self) -> Dict[str, Any] (method) [L1077-1083]
    - _generate_security_recommendations(self) -> List[str] (method) [L1085-1093]
    - _extract_coding_standards(self) -> List[str] (method) [L1095-1108]
    - _analyze_testing_practices(self) -> Dict[str, Any] (method) [L1110-1123]
    - _generate_review_checklist(self) -> List[str] (method) [L1125-1134]
    - _document_common_patterns(self) -> List[Dict[str, Any]] (method) [L1136-1149]
    - _document_anti_patterns(self) -> List[Dict[str, Any]] (method) [L1151-1164]
    - _list_development_tooling(self) -> List[str] (method) [L1166-1178]
    - _create_quick_start(self) -> List[str] (method) [L1180-1187]
    - _document_dev_setup(self) -> Dict[str, str] (method) [L1189-1196]
    - _extract_key_concepts(self) -> List[str] (method) [L1198-1206]
    - _list_common_tasks(self) -> List[Dict[str, str]] (method) [L1208-1223]
    - _list_learning_resources(self) -> List[str] (method) [L1225-1233]
    - _identify_domain_experts(self) -> Dict[str, str] (method) [L1235-1242]
    - _find_database_in_loops(self) -> List[str] (method) [L1244-1247]
    - _find_large_file_processing(self) -> List[str] (method) [L1249-1252]
    - _find_synchronous_io(self) -> List[str] (method) [L1254-1257]
    - _assess_integration_criticality(self, target: str) -> str (method) [L1259-1268]
  📄 c4_rules.py
    - C4Rule (class) [L15-19]
    - ExternalSystemRule (class) [L23-28]
    - ContainerRule (class) [L32-38]
    - ComponentRule (class) [L42-47]
    - C4RuleEngine (class) [L50-506]
    - __init__(self) -> List[Dict[str, Any]] (method) [L53-56]
    - _init_external_system_rules(self) -> List[ExternalSystemRule] (method) [L58-172]
    - _init_container_rules(self) -> List[ContainerRule] (method) [L174-249]
    - _init_component_rules(self) -> List[ComponentRule] (method) [L251-302]
    - apply_external_system_rules(self, imports: List[str]) -> Dict[str, List[str]] (method) [L304-324]
    - apply_container_rules(self, frameworks: List[str], directories: List[str]) -> List[Dict[str, Any]] (method) [L326-348]
    - apply_component_rules(self, entities: List[Dict[str, Any]], 
                            importance_scores: Dict[str, float]) -> List[Dict[str, Any]] (method) [L350-382]
    - calculate_relationship_importance(self, relationship: Dict[str, Any],
                                        source_importance: float,
                                        target_importance: float) -> float (method) [L384-402]
    - filter_relationships(self, relationships: List[Dict[str, Any]],
                           entity_importance: Dict[str, float],
                           max_relationships: int = 100) -> List[Dict[str, Any]] (method) [L404-432]
    - infer_component_responsibility(self, entity: Dict[str, Any]) -> str (method) [L434-475]
    - suggest_view_filtering(self, components: List[Dict[str, Any]], 
                             max_components_per_view: int = 20) -> Dict[str, List[str]] (method) [L477-506]
  📄 c4_structurizr.py
    - StructurizrFormatter (class) [L14-409]
    - __init__(self, workspace_name: str, workspace_description: str) -> None (method) [L17-48]
    - add_person(self, person: Dict[str, Any]) -> None (method) [L50-61]
    - add_software_system(self, system: Dict[str, Any]) -> None (method) [L63-74]
    - add_container(self, container: Dict[str, Any]) -> None (method) [L76-89]
    - add_component(self, component: Dict[str, Any]) -> None (method) [L91-104]
    - add_system_context_view(self, view: Dict[str, Any]) -> None (method) [L106-136]
    - add_container_view(self, view: Dict[str, Any]) -> None (method) [L138-156]
    - add_component_view(self, view: Dict[str, Any]) -> None (method) [L158-176]
    - add_llm_extensions(self, extensions: Dict[str, Any]) -> None (method) [L178-196]
    - _generate_tags(self, element: Dict[str, Any], element_type: str) -> List[str] (method) [L198-222]
    - _format_view_elements(self, element_ids: List[str], additional_ids: List[str]) -> List[Dict[str, Any]] (method) [L224-236]
    - _format_markdown_content(self, section_name: str, content: Any) -> str (method) [L238-259]
    - add_relationships(self, relationships: List[Dict[str, Any]]) -> None (method) [L261-265]
    - add_styling(self) -> None (method) [L267-355]
    - to_dict(self) -> Dict[str, Any] (method) [L357-359]
    - to_json(self, indent: int = 2) -> str (method) [L361-363]
    - save_to_file(self, file_path: str) -> None (method) [L365-368]
    - validate(self) -> List[str] (method) [L370-409]
  📄 categorizer.py
    - FileCategory (class) [L19-29]
    - __str__(self) -> str (method) [L28-29]
    - FileCategorizer (class) [L32-402]
    - __init__(self) -> None (method) [L291-293]
    - categorize(self, file_path: str) -> FileCategory (method) [L295-329]
    - _is_test_file(self, parts: list[str], filename: str, stem: str, suffix: str) -> bool (method) [L331-348]
    - _is_doc_file(self, parts: list[str], filename: str, stem: str, suffix: str) -> bool (method) [L350-367]
    - _is_config_file(self, parts: list[str], filename: str, stem: str, suffix: str) -> bool (method) [L369-390]
    - _is_source_file(self, parts: list[str], filename: str, suffix: str) -> bool (method) [L392-402]
    - categorize_file(file_path: str) -> FileCategory (function) [L409-419]
  📄 codegraph.py
    - InMemoryGraph (class) [L55-152]
    - __init__(
        self,
        entities: dict[str, Entity] | None = None,
        relationships: list[Relationship] | None = None,
    ) -> None (method) [L64-72]
    - add_entity(self, entity: Entity) -> None (method) [L74-75]
    - add_relationship(self, relationship: Relationship) -> None (method) [L77-80]
    - get_entity(self, entity_id: str) -> Entity | None (method) [L82-83]
    - _build_index(self) -> None (method) [L85-92]
    - neighbors(self, entity_id: str, direction: str = "out") -> list[str] (method) [L94-103]
    - entities_by_file(self, file_path: str) -> list[Entity] (method) [L105-106]
    - entities_by_type(self, entity_type: EntityType) -> list[Entity] (method) [L108-109]
    - root_entities(self) -> list[Entity] (method) [L111-112]
    - stats(self) -> dict[str, Any] (method) [L114-125]
    - to_dict(self) -> dict[str, Any] (method) [L127-132]
    - __len__(self) -> int (method) [L143-144]
    - __contains__(self, entity_id: str) -> bool (method) [L146-147]
    - __repr__(self) -> str (method) [L149-152]
    - _FileStateCache (class) [L160-252]
    - __init__(self, cache_path: Path, root: Path | None = None) -> None (method) [L173-179]
    - _load(self) -> None (method) [L181-198]
    - _mark_corrupt(self, reason: str) -> None (method) [L200-215]
    - _normalise(self, filepath: str) -> str (method) [L221-228]
    - save(self) -> None (method) [L230-239]
    - is_cached(self, filepath: str, content_hash: str) -> bool (method) [L241-246]
    - update(self, filepath: str, mtime: float, content_hash: str) -> None (method) [L248-249]
    - invalidate(self, filepath: str) -> None (method) [L251-252]
    - CodeGraphIndexer (class) [L260-629]
    - __init__(self, cache_path: str = ".ctn/file_cache.json", root: str | None = None) -> None (method) [L282-287]
    - build_graph(
        self,
        root: str,
        extractor: ASTExtractor | None = None,
        extensions: list[str] | None = None,
        max_workers: int = 0,
        max_file_size_kb: int | None = None,
        verbose: bool = False,
        metrics_callback: Callable[[str, Dict[str, Any]], None] | None = None,
    ) -> InMemoryGraph (method) [L293-515]
    - _process_file(
            args: tuple[Path, str],
        ) -> tuple[str, list[Entity], list[Relationship], bool] | None (function) [L396-445]
    - index_file(
        self,
        filepath: str,
        extractor: ASTExtractor,
        max_file_size_kb: int | None = None,
    ) -> tuple[list[Entity], list[Relationship]] (method) [L517-560]
    - invalidate(self, filepath: str) -> None (method) [L562-568]
    - stats(self) -> dict[str, int] (method) [L570-572]
    - _resolve_imports(self, graph: InMemoryGraph) -> InMemoryGraph (method) [L578-629]
  📄 extractor.py
    - _node_text(node: Node, source: bytes) -> str (function) [L88-90]
    - _clean_docstring(text: str) -> str (function) [L93-99]
    - ASTExtractor (class) [L110-522]
    - __init__(self, language: str) -> None (method) [L136-147]
    - parse_file(
        self,
        filepath: str,
        content: bytes,
    ) -> tuple[list[Entity], list[Relationship]] (method) [L167-229]
    - _process_captures(
        self,
        captures: dict[str, list[Node]],
        source: bytes,
        filepath: str,
    ) -> tuple[list[Entity], list[Relationship]] (method) [L235-264]
    - _build_entities(
        self,
        definition_nodes: dict[str, list[Node]],
        auxiliary_nodes: dict[tuple[str, str], list[Node]],
        source: bytes,
        filepath: str,
    ) -> list[Entity] (method) [L266-309]
    - _build_relationships(
        self,
        captures: dict[str, list[Node]],
        entities: list[Entity],
        source: bytes,
        filepath: str,
    ) -> list[Relationship] (method) [L311-415]
    - _add(src_id: str, tgt_id: str, rel_type: RelationshipType, line: int) -> None (function) [L322-333]
    - _find_enclosing(byte_offset: int) -> Entity | None (function) [L350-358]
    - _collect_metadata_with_source(
        self,
        base_key: str,
        decl_node: Node,
        auxiliary_nodes: dict[tuple[str, str], list[Node]],
        source: bytes,
    ) -> EntityMetadata (method) [L421-463]
    - _build_signature(
        self,
        name: str,
        base_key: str,
        decl_node: Node,
        auxiliary_nodes: dict[tuple[str, str], list[Node]],
        source: bytes,
    ) -> str | None (method) [L465-488]
    - _enrich_entity(
        self,
        entity: Entity,
        decl_node: Node,
        auxiliary_nodes: dict[tuple[str, str], list[Node]],
        source: bytes,
    ) -> Entity (method) [L507-522]
    - MarkupConfigExtractor (class) [L530-646]
    - __init__(self, language: str) -> None (method) [L542-546]
    - _query_source(self) -> str (method) [L548-550]
    - parse_file(
        self,
        filepath: str,
        content: bytes,
    ) -> tuple[list[Entity], list[Relationship]] (method) [L569-597]
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
    ) -> Entity (method) [L599-623]
    - _create_relationship(
        self,
        source_id: str,
        target_id: str,
        rel_type: RelationshipType,
        line: int,
    ) -> Relationship (method) [L625-638]
    - _extract_key_value_pairs(
        self,
        source: bytes,
        filepath: str,
    ) -> list[Entity] (method) [L640-646]
  📄 repomap.py
    - _text_tokens(text: str) -> int (function) [L34-36]
    - RepoMap (class) [L45-704]
    - __post_init__(self) -> None (method) [L66-67]
    - _rel(p: str) -> str (function) [L96-101]
    - render_full(self) -> str (method) [L143-169]
    - render_compressed(
        self, budget: int, fail_on_overflow: bool = True
    ) -> tuple[str, dict[str, int]] (method) [L171-227]
    - render_json(self) -> dict[str, Any] (method) [L229-276]
    - _get_directory_label(self, dir_path: str) -> str | None (method) [L282-302]
    - group_by_directory(self) -> dict[str, list[tuple[str, list[Entity]]]] (method) [L304-314]
    - render_hierarchical(
        self,
        include_entities: bool = True,
    ) -> str (method) [L316-364]
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
    ) -> str (method) [L481-615]
    - _count_by_language(self) -> dict[str, int] (method) [L617-651]
    - _render_high_level_tree(self, max_depth: int = 3) -> list[str] (method) [L653-684]
    - get_depth(path: str) -> int (function) [L658-659]
    - estimate_tokens(self) -> int (method) [L690-694]
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
    - _normalize_package_name(name: str) -> str (function) [L472-474]
    - _match_framework(package_name: str, framework_map: dict[str, str]) -> str | None (function) [L477-493]
    - _safe_read(path: Path) -> str (function) [L496-500]
    - _detect_package_manager(root_path: Path) -> list[str] (function) [L503-508]
    - _dedupe_preserve_order(values: list[str]) -> list[str] (function) [L511-512]
    - _detect_java(root_path: Path) -> None (function) [L515-551]
    - _scan_deps(text: str) -> None (function) [L522-529]
    - _detect_dotnet(root_path: Path) -> dict[str, Any] | None (function) [L554-572]
    - _detect_go(root_path: Path) -> dict[str, Any] | None (function) [L575-589]
    - _detect_php(root_path: Path) -> dict[str, Any] | None (function) [L592-611]
    - _detect_ruby(root_path: Path) -> dict[str, Any] | None (function) [L614-628]
    - _detect_rust(root_path: Path) -> dict[str, Any] | None (function) [L631-660]
    - _detect_mobile(root_path: Path) -> dict[str, Any] | None (function) [L663-677]
    - _detect_infra(root_path: Path) -> list[str] (function) [L680-689]
    - _extract_python_version_from_requires_python(requires_python: str) -> str (function) [L692-705]
    - _detect_build_tool(pyproject_data: dict[str, Any]) -> str | None (function) [L708-737]
    - detect_python_stack(root_dir: str | Path) -> dict[str, Any] | None (function) [L740-873]
    - detect_node_stack(root_dir: str | Path) -> dict[str, Any] | None (function) [L876-942]
    - _find_all_node_stacks(root_path: Path) -> list[dict[str, Any]] (function) [L945-964]
    - detect_stack(root_dir: str | Path) -> dict[str, Any] (function) [L967-1056]
    - _detect_special_files(
    root_path: Path,
    languages: list[str],
    frameworks: set[str],
    build_tools: list[str],
) -> None (function) [L1059-1119]
    deps: re, tomllib

📁 batho_core/context/languages/
  📄 _common.py
    - CommonQueries (class) [L23-133]
    - ProgrammingLanguageExtractor (class) [L141-175]
    - ImportPatterns (class) [L183-208]
    - CallPatterns (class) [L211-238]
    - build_query(segments: list[str]) -> str (function) [L246-256]
    - comment_block(title: str, width: int = 70) -> str (function) [L259-271]
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
    - CSSExtractor (class) [L26-242]
    - __init__(self) -> None (method) [L29-30]
    - _extract_elements(
        self,
        source: bytes,
        filepath: str,
    ) -> list[Entity] (method) [L32-163]
    - _count_properties(self, properties_block: str) -> int (method) [L165-170]
    - _extract_references(
        self,
        source: bytes,
        filepath: str,
        entities: list[Entity],
    ) -> list[Relationship] (method) [L172-242]
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
    - detect_by_content_heuristics(content: bytes) -> DetectionResult | None (function) [L334-367]
    - LanguageDetector (class) [L375-525]
    - __init__(self, min_confidence: float = 0.5) -> None (method) [L398-406]
    - detect(
        self,
        filepath: Path,
        content: bytes,
    ) -> DetectionResult | None (method) [L408-443]
    - detect_with_fallback(
        self,
        filepath: Path,
        content: bytes,
    ) -> DetectionResult | None (method) [L445-489]
    - get_extractor(
        self,
        filepath: Path,
        content: bytes,
    ) -> object | None (method) [L491-525]
    - detect_language(
    filepath: str | Path,
    content: bytes,
) -> DetectionResult | None (function) [L547-561]
    - detect_language_with_fallback(
    filepath: str | Path,
    content: bytes,
) -> DetectionResult | None (function) [L564-578]
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
    - HCLExtractor (class) [L24-353]
    - __init__(self) -> None (method) [L27-28]
    - _extract_elements(
        self,
        source: bytes,
        filepath: str,
    ) -> list[Entity] (method) [L30-172]
    - _find_block_end(self, content: str, start_pos: int, brace_positions: list) -> int (method) [L174-186]
    - _extract_attributes(
        self,
        content: str,
        filepath: str,
        parent_path: str,
        entities: list[Entity],
        line_offset: int,
        get_line_from_offset: Any,
        exclude_blocks: bool = False,
    ) -> None (method) [L188-234]
    - _extract_references(
        self,
        source: bytes,
        filepath: str,
        entities: list[Entity],
    ) -> list[Relationship] (method) [L236-353]
  📄 html.py
    - HTMLExtractor (class) [L27-249]
    - __init__(self) -> None (method) [L30-31]
    - _extract_elements(
        self,
        source: bytes,
        filepath: str,
    ) -> list[Entity] (method) [L33-150]
    - _extract_title(self, content: str) -> str | None (method) [L152-157]
    - _extract_references(
        self,
        source: bytes,
        filepath: str,
        entities: list[Entity],
    ) -> list[Relationship] (method) [L159-249]
  📄 java.py
    - JavaExtractor (class) [L18-63]
    - __init__(self) -> None (method) [L21-22]
    - _query_source(self) -> str (method) [L24-63]
  📄 javascript.py
    - JavaScriptExtractor (class) [L22-62]
    - __init__(self) -> None (method) [L25-26]
    - _query_source(self) -> str (method) [L28-62]
  📄 json.py
    - JSONExtractor (class) [L24-236]
    - __init__(self) -> None (method) [L27-28]
    - _extract_elements(
        self,
        source: bytes,
        filepath: str,
    ) -> list[Entity] (method) [L30-79]
    - _process_value(
        self,
        value: Any,
        filepath: str,
        name: str,
        entities: list[Entity],
        line_offset: int,
        source: bytes,
        parent_path: str = "",
    ) -> None (method) [L81-170]
    - _serialize_value(self, value: Any) -> Any (method) [L172-176]
    - _extract_references(
        self,
        source: bytes,
        filepath: str,
        entities: list[Entity],
    ) -> list[Relationship] (method) [L178-236]
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
    - MarkdownExtractor (class) [L26-352]
    - __init__(self) -> None (method) [L29-30]
    - _extract_elements(
        self,
        source: bytes,
        filepath: str,
    ) -> list[Entity] (method) [L32-228]
    - _extract_frontmatter(self, content: str) -> dict[str, Any] | None (method) [L230-256]
    - _extract_references(
        self,
        source: bytes,
        filepath: str,
        entities: list[Entity],
    ) -> list[Relationship] (method) [L258-352]
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
    - is_language_available(language: str) -> bool (function) [L235-276]
    - _build_class_map() -> None (function) [L283-363]
    - _get_extractor_instance(language: str) -> ASTExtractor | None (function) [L373-409]
    - _discover_language_modules() -> None (function) [L412-503]
    - discover_and_register_all() -> None (function) [L506-516]
    - get_extractor(extension: str) -> ASTExtractor | None (function) [L519-557]
    - get_extractor_for_language(language: str) -> ASTExtractor | None (function) [L560-574]
    - get_language_for_extension(extension: str) -> str | None (function) [L577-587]
    - get_extensions_for_language(language: str) -> list[str] (function) [L590-600]
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
    - TOMLExtractor (class) [L36-256]
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
    ) -> list[Relationship] (method) [L200-256]
  📄 typescript.py
    - TypeScriptExtractor (class) [L20-71]
    - __init__(self) -> None (method) [L23-24]
    - _query_source(self) -> str (method) [L26-71]
  📄 verilog.py
    - VerilogExtractor (class) [L22-98]
    - __init__(self) -> None (method) [L25-26]
    - _query_source(self) -> str (method) [L28-98]
  📄 yaml.py
    - YAMLExtractor (class) [L30-278]
    - __init__(self) -> None (method) [L33-34]
    - _extract_elements(
        self,
        source: bytes,
        filepath: str,
    ) -> list[Entity] (method) [L36-120]
    - _process_value(
        self,
        value: Any,
        filepath: str,
        name: str,
        entities: list[Entity],
        line_offset: int,
        source: bytes,
        parent_path: str = "",
    ) -> None (method) [L122-214]
    - _serialize_value(self, value: Any) -> Any (method) [L216-220]
    - _extract_references(
        self,
        source: bytes,
        filepath: str,
        entities: list[Entity],
    ) -> list[Relationship] (method) [L222-278]
  📄 zig.py
    - ZigExtractor (class) [L20-86]
    - __init__(self) -> None (method) [L23-24]
    - _query_source(self) -> str (method) [L26-86]

📁 batho_core/utils/ (Utilities)
  📄 dependencies.py
    - extract_package_name(dep_spec: str) -> str (function) [L38-58]
    - parse_requirements_txt(content: str) -> list[str] (function) [L66-88]
    - parse_requirements_txt_file(path: Path) -> list[str] (function) [L91-106]
    - parse_pyproject_toml(content: str) -> dict[str, Any] (function) [L114-193]
    - _detect_build_tool_from_pyproject(data: dict[str, Any]) -> str | None (function) [L196-222]
    - _parse_pyproject_toml_regex(content: str) -> dict[str, Any] (function) [L225-240]
    - parse_pyproject_toml_file(path: Path) -> dict[str, Any] (function) [L243-263]
    - parse_setup_py(content: str) -> dict[str, Any] (function) [L271-303]
    - parse_setup_py_file(path: Path) -> dict[str, Any] (function) [L306-321]
    - parse_package_json(content: str) -> dict[str, Any] (function) [L329-372]
    - parse_package_json_file(path: Path) -> dict[str, Any] (function) [L375-402]
    - _detect_node_package_manager(root_path: Path) -> str | None (function) [L405-415]
    - parse_cargo_toml(content: str) -> dict[str, Any] (function) [L423-480]
    - parse_cargo_toml_file(path: Path) -> dict[str, Any] (function) [L483-502]
    - extract_all_dependencies(base_path: Path | str) -> dict[str, list[str]] (function) [L510-574]
    - extract_dependency_names(base_path: Path | str) -> list[str] (function) [L577-614]
    deps: tomllib
  📄 encoding.py
    - read_text_with_fallback(
    filepath: Path | str, encodings: list[str] | None = None, errors: str = "replace"
) -> str (function) [L16-51]
    - decode_bytes_with_fallback(
    data: bytes, encodings: list[str] | None = None, errors: str = "replace"
) -> str (function) [L54-84]
    - normalize_to_utf8(data: bytes, errors: str = "replace") -> bytes (function) [L87-106]
  📄 file_io.py
    - _calculate_shannon_entropy(data: bytes) -> float (function) [L48-64]
    - _is_binary(content: bytes) -> bool (function) [L67-93]
    - read_file_bytes(
    filepath: Union[str, Path],
    max_size_kb: int | None = None,
    normalize_encoding: bool = True,
    detect_binary: bool = False,
) -> bytes | None (function) [L96-148]
    - read_file_text(
    filepath: Union[str, Path],
    max_size_kb: int | None = None,
    encoding: str = "utf-8",
    errors: str = "replace",
) -> str | None (function) [L151-182]
    - write_atomically(
    path: Union[str, Path],
    content: Union[str, bytes, dict],
    *,
    is_json: bool = False,
    encoding: str = "utf-8",
    indent: int | None = 2,
    ensure_parent: bool = True,
) -> bool (function) [L185-248]
    - _read_file_bytes(filepath: str, max_size_kb: int = 500) -> bytes | None (function) [L252-254]
    - _read_file_content(filepath: str, max_size_kb: int | None = None) -> bytes | None (function) [L257-259]
    deps: batho_core.utils.encoding, collections, math
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
) -> Any (function) [L283-318]
    - rglob_ignored_filtered(
    root: Path,
    pattern: str,
    spec: Any | None = None,
    skip_hidden: bool = True,
) -> Any (function) [L321-344]
    deps: fnmatch, pathspec
  📄 logging.py
    - get_logger(name: str | None = None, **context: Any) -> BindableLogger (function) [L21-36]
    - get_context_logger(**context: Any) -> BindableLogger (function) [L39-42]
    - get_log_level(level_name: str = "INFO") -> int (function) [L45-55]
    - configure_logging(level: int = logging.INFO, json_format: bool | None = None) -> None (function) [L58-93]
