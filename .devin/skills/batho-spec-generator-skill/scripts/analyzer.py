#!/usr/bin/env python3
"""
Requirements Analyzer.

Analyzes user requirements and planning documents to extract entities,
actions, components, and relationships for task breakdown generation.

Example:
    $ python analyzer.py --input "Build a user authentication system"
    $ python analyzer.py --file docs/requirements.md
"""

import sys
import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Entity:
    """Represents a noun/thing identified in requirements."""
    name: str
    entity_type: str  # component, data_structure, interface, service
    description: str = ""
    attributes: List[str] = field(default_factory=list)
    relationships: List[str] = field(default_factory=list)


@dataclass
class Action:
    """Represents a verb/action identified in requirements."""
    name: str
    action_type: str  # create, read, update, delete, validate, transform
    target: str = ""
    description: str = ""
    conditions: List[str] = field(default_factory=list)


@dataclass
class Component:
    """Represents a logical grouping of related entities and actions."""
    name: str
    description: str
    entities: List[str] = field(default_factory=list)
    actions: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)


@dataclass
class AnalysisResult:
    """Result of requirements analysis."""
    entities: List[Entity] = field(default_factory=list)
    actions: List[Action] = field(default_factory=list)
    components: List[Component] = field(default_factory=list)
    raw_requirements: str = ""
    source_files: List[str] = field(default_factory=list)
    metadata: Dict = field(default_factory=dict)


class RequirementsAnalyzer:
    """
    Analyzes requirements text or documents to extract structured information.

    This class parses requirements to identify:
    - Entities (components, data structures, interfaces)
    - Actions (operations to be performed)
    - Components (logical groupings)
    - Relationships between elements

    Attributes:
        config: Configuration options for analysis

    Example:
        >>> analyzer = RequirementsAnalyzer()
        >>> result = analyzer.analyze("Build a user authentication system")
        >>> print(f"Found {len(result.entities)} entities")
    """

    COMPONENT_KEYWORDS = {
        'cli', 'command', 'argument', 'parser', 'formatter',
        'core', 'schema', 'contract', 'exception', 'config', 'utility',
        'compress', 'compressor', 'encoder', 'decoder', 'archive',
        'extract', 'extractor', 'parser', 'file', 'content',
        'graph', 'node', 'edge', 'traversal', 'dependency',
        'checksum', 'hash', 'integrity', 'validation', 'verification',
        'storage', 'backend', 'cache', 'persistence',
        'orchestrator', 'build', 'export', 'patch', 'workflow'
    }

    ACTION_VERBS = {
        'create': ['create', 'add', 'register', 'new', 'insert'],
        'read': ['get', 'fetch', 'retrieve', 'read', 'list', 'search', 'query'],
        'update': ['update', 'modify', 'edit', 'change', 'patch'],
        'delete': ['delete', 'remove', 'drop', 'unregister'],
        'validate': ['validate', 'verify', 'check', 'authenticate', 'authorize'],
        'transform': ['convert', 'transform', 'map', 'serialize', 'parse'],
        'notify': ['send', 'notify', 'push', 'emit', 'broadcast'],
        'store': ['save', 'store', 'persist', 'cache', 'index']
    }

    DATA_STRUCTURE_KEYWORDS = {
        'user', 'account', 'profile', 'session', 'token', 'permission',
        'role', 'group', 'team', 'organization', 'project', 'resource',
        'file', 'document', 'image', 'payment', 'order', 'product',
        'category', 'tag', 'comment', 'notification', 'event', 'log'
    }

    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize the analyzer with optional configuration.

        Args:
            config: Optional configuration dictionary with analysis settings
        """
        self.config = config or {}
        self.min_entity_length = self.config.get('min_entity_length', 2)
        self.max_entities = self.config.get('max_entities', 50)

    def analyze(self, requirements: str, source_files: Optional[List[str]] = None) -> AnalysisResult:
        """
        Analyze requirements text and optionally referenced files.

        Args:
            requirements: The requirements text to analyze
            source_files: Optional list of file paths to include in analysis

        Returns:
            AnalysisResult containing extracted entities, actions, and components

        Raises:
            ValueError: If requirements text is empty or invalid
        """
        if not requirements or not requirements.strip():
            raise ValueError("Requirements text cannot be empty")

        result = AnalysisResult(raw_requirements=requirements)

        if source_files:
            for file_path in source_files:
                content = self._read_file(file_path)
                if content:
                    result.raw_requirements += f"\n\n--- From {file_path} ---\n{content}"
                    result.source_files.append(file_path)

        result.entities = self._extract_entities(result.raw_requirements)
        result.actions = self._extract_actions(result.raw_requirements)
        result.components = self._identify_components(result.entities, result.actions)
        result.metadata = {
            'analyzed_at': datetime.now().isoformat(),
            'source_count': len(source_files) if source_files else 0,
            'entity_count': len(result.entities),
            'action_count': len(result.actions),
            'component_count': len(result.components)
        }

        return result

    def _read_file(self, file_path: str) -> Optional[str]:
        """
        Read content from a file path.

        Args:
            file_path: Path to the file to read

        Returns:
            File content as string, or None if file cannot be read
        """
        try:
            path = Path(file_path)
            if path.exists() and path.is_file():
                return path.read_text(encoding='utf-8')
        except (OSError, PermissionError):
            pass
        return None

    def _extract_entities(self, text: str) -> List[Entity]:
        """
        Extract entities (nouns/components) from requirements text.

        Args:
            text: Requirements text to analyze

        Returns:
            List of Entity objects found in the text
        """
        entities = []
        seen_names = set()

        text_lower = text.lower()

        for keyword in self.COMPONENT_KEYWORDS:
            pattern = rf'\b(\w*{keyword}\w*)\b'
            matches = re.findall(pattern, text_lower)
            for match in matches:
                if match not in seen_names and len(match) >= self.min_entity_length:
                    entity_type = self._classify_entity(match, keyword)
                    entity = Entity(
                        name=self._normalize_name(match),
                        entity_type=entity_type,
                        description=f"Identified from '{match}' keyword"
                    )
                    entities.append(entity)
                    seen_names.add(match)

        for keyword in self.DATA_STRUCTURE_KEYWORDS:
            pattern = rf'\b(\w*{keyword}\w*)\b'
            matches = re.findall(pattern, text_lower)
            for match in matches:
                if match not in seen_names and len(match) >= self.min_entity_length:
                    entity = Entity(
                        name=self._normalize_name(match),
                        entity_type='data_structure',
                        description=f"Data structure for {match}"
                    )
                    entities.append(entity)
                    seen_names.add(match)

        custom_patterns = [
            (r'\b([A-Z][a-z]+(?:[A-Z][a-z]+)+)\b', 'component'),
            (r'`([^`]+)`', 'interface'),
            (r'"([^"]+)"\s+(?:API|endpoint|interface)', 'interface')
        ]

        for pattern, etype in custom_patterns:
            matches = re.findall(pattern, text)
            for match in matches:
                if match.lower() not in seen_names:
                    entity = Entity(
                        name=match,
                        entity_type=etype,
                        description=f"Identified from pattern: {pattern}"
                    )
                    entities.append(entity)
                    seen_names.add(match.lower())

        return entities[:self.max_entities]

    def _classify_entity(self, name: str, keyword: str) -> str:
        """
        Classify entity type based on name and matched keyword.

        Args:
            name: Entity name
            keyword: Matched keyword

        Returns:
            Entity type classification
        """
        name_lower = name.lower()
        if keyword in {'api', 'endpoint', 'route'}:
            return 'interface'
        elif keyword in {'database', 'repository', 'table', 'collection'}:
            return 'data_structure'
        elif keyword in {'service', 'worker', 'queue'}:
            return 'service'
        elif keyword in {'controller', 'handler', 'processor'}:
            return 'component'
        elif keyword in {'model', 'schema'}:
            return 'data_structure'
        elif keyword in {'middleware', 'filter'}:
            return 'component'
        else:
            return 'component'

    def _normalize_name(self, name: str) -> str:
        """
        Normalize entity name to a readable format.

        Args:
            name: Raw entity name

        Returns:
            Normalized name
        """
        name = re.sub(r'[_-]', ' ', name)
        name = re.sub(r'(\w)([A-Z])', r'\1 \2', name)
        return name.title()

    def _extract_actions(self, text: str) -> List[Action]:
        """
        Extract actions (verbs/operations) from requirements text.

        Args:
            text: Requirements text to analyze

        Returns:
            List of Action objects found in the text
        """
        actions = []
        seen_actions = set()

        sentences = re.split(r'[.!?\n]', text)

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue

            sentence_lower = sentence.lower()

            for action_type, verbs in self.ACTION_VERBS.items():
                for verb in verbs:
                    if verb in sentence_lower:
                        action_key = f"{action_type}:{verb}"
                        if action_key not in seen_actions:
                            target = self._extract_action_target(sentence, verb)
                            action = Action(
                                name=verb,
                                action_type=action_type,
                                target=target,
                                description=sentence
                            )
                            actions.append(action)
                            seen_actions.add(action_key)
                            break

        modal_verbs = ['should', 'must', 'need', 'require', 'want', 'would like']
        for modal in modal_verbs:
            pattern = rf'\b{modal}\s+(?:be\s+)?(\w+(?:\s+\w+)?)'
            matches = re.findall(pattern, text.lower())
            for match in matches:
                action_key = f"requirement:{match}"
                if action_key not in seen_actions:
                    action = Action(
                        name=match,
                        action_type='requirement',
                        target=match,
                        description=f"Requirement identified via '{modal}'"
                    )
                    actions.append(action)
                    seen_actions.add(action_key)

        return actions

    def _extract_action_target(self, sentence: str, verb: str) -> str:
        """
        Extract the target of an action from the sentence.

        Args:
            sentence: Sentence containing the action
            verb: The action verb

        Returns:
            Target of the action, or empty string
        """
        pattern = rf'{verb}\s+(?:the\s+)?(\w+(?:\s+\w+)?)'
        match = re.search(pattern, sentence.lower())
        if match:
            return match.group(1)
        return ""

    def _identify_components(self, entities: List[Entity], actions: List[Action]) -> List[Component]:
        """
        Identify logical components by grouping related entities and actions.

        Args:
            entities: List of extracted entities
            actions: List of extracted actions

        Returns:
            List of Component objects
        """
        components = []
        component_map = {}

        cli_keywords = {'cli', 'command', 'argument', 'parser', 'formatter', 'help'}
        core_keywords = {'core', 'schema', 'contract', 'exception', 'config', 'utility'}
        compression_keywords = {'compress', 'compressor', 'encoder', 'decoder', 'archive', 'zip', 'gzip'}
        extraction_keywords = {'extract', 'extractor', 'parser', 'file', 'content', 'unzip'}
        graph_keywords = {'graph', 'node', 'edge', 'traversal', 'dependency', 'codegraph'}
        integrity_keywords = {'checksum', 'hash', 'integrity', 'validation', 'verification', 'sha'}
        storage_keywords = {'storage', 'backend', 'cache', 'persistence', 'database', 'save'}
        orchestrator_keywords = {'orchestrator', 'build', 'export', 'patch', 'workflow', 'coordinate'}
        api_keywords = {'api', 'endpoint', 'route', 'rest', 'graphql'}
        data_keywords = {'data', 'model', 'schema', 'database', 'repository'}
        ui_keywords = {'ui', 'interface', 'frontend', 'view', 'component'}
        business_keywords = {'business', 'logic', 'service', 'domain'}

        for entity in entities:
            name_lower = entity.name.lower()
            component_name = None

            if any(kw in name_lower for kw in cli_keywords):
                component_name = "CLI"
            elif any(kw in name_lower for kw in core_keywords):
                component_name = "Core"
            elif any(kw in name_lower for kw in compression_keywords):
                component_name = "Modules/Compression"
            elif any(kw in name_lower for kw in extraction_keywords):
                component_name = "Modules/Extraction"
            elif any(kw in name_lower for kw in graph_keywords):
                component_name = "Modules/Graph"
            elif any(kw in name_lower for kw in integrity_keywords):
                component_name = "Modules/Integrity"
            elif any(kw in name_lower for kw in storage_keywords):
                component_name = "Modules/Storage"
            elif any(kw in name_lower for kw in orchestrator_keywords):
                component_name = "Orchestrator"
            elif any(kw in name_lower for kw in api_keywords):
                component_name = "API Layer"
            elif any(kw in name_lower for kw in data_keywords):
                component_name = "Data Layer"
            elif any(kw in name_lower for kw in ui_keywords):
                component_name = "User Interface"
            elif any(kw in name_lower for kw in business_keywords):
                component_name = "Business Logic"

            if component_name:
                if component_name not in component_map:
                    component_map[component_name] = Component(
                        name=component_name,
                        description=f"Component handling {component_name.lower()} concerns"
                    )
                component_map[component_name].entities.append(entity.name)

        for action in actions:
            target_lower = action.target.lower()
            component_name = None

            if any(kw in target_lower for kw in cli_keywords):
                component_name = "CLI"
            elif any(kw in target_lower for kw in core_keywords):
                component_name = "Core"
            elif any(kw in target_lower for kw in compression_keywords):
                component_name = "Modules/Compression"
            elif any(kw in target_lower for kw in extraction_keywords):
                component_name = "Modules/Extraction"
            elif any(kw in target_lower for kw in graph_keywords):
                component_name = "Modules/Graph"
            elif any(kw in target_lower for kw in integrity_keywords):
                component_name = "Modules/Integrity"
            elif any(kw in target_lower for kw in storage_keywords):
                component_name = "Modules/Storage"
            elif any(kw in target_lower for kw in orchestrator_keywords):
                component_name = "Orchestrator"

            if component_name and component_name in component_map:
                component_map[component_name].actions.append(action.name)

        if not component_map:
            default_component = Component(
                name="Core",
                description="Core functionality identified from requirements"
            )
            for entity in entities[:5]:
                default_component.entities.append(entity.name)
            for action in actions[:5]:
                default_component.actions.append(action.name)
            component_map["Core"] = default_component

        components = list(component_map.values())

        components = self._establish_component_dependencies(components)

        return components

    def _establish_component_dependencies(self, components: List[Component]) -> List[Component]:
        """
        Establish dependencies between components based on their roles.

        Args:
            components: List of identified components

        Returns:
            Components with dependency information
        """
        dependency_order = {
            "Data Layer": [],
            "Authentication": ["Data Layer"],
            "Business Logic": ["Data Layer", "Authentication"],
            "API Layer": ["Business Logic", "Authentication"],
            "User Interface": ["API Layer", "Business Logic"],
            "Core": []
        }

        for component in components:
            if component.name in dependency_order:
                component.dependencies = dependency_order[component.name]

        return components


def main():
    """Main function for command-line usage."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Analyze requirements and extract entities, actions, and components"
    )
    parser.add_argument(
        '--input', '-i',
        help='Requirements text to analyze'
    )
    parser.add_argument(
        '--file', '-f',
        action='append',
        help='File(s) to read requirements from (can be specified multiple times)'
    )
    parser.add_argument(
        '--output', '-o',
        default='analysis_output.json',
        help='Output file for analysis results'
    )
    parser.add_argument(
        '--config',
        help='Configuration file (JSON)'
    )

    args = parser.parse_args()

    if not args.input and not args.file:
        parser.error("Either --input or --file must be provided")

    config = {}
    if args.config:
        import json
        config = json.loads(Path(args.config).read_text())

    analyzer = RequirementsAnalyzer(config)

    requirements = args.input or ""
    source_files = args.file or []

    result = analyzer.analyze(requirements, source_files)

    import json
    output_data = {
        'entities': [
            {
                'name': e.name,
                'type': e.entity_type,
                'description': e.description
            }
            for e in result.entities
        ],
        'actions': [
            {
                'name': a.name,
                'type': a.action_type,
                'target': a.target,
                'description': a.description
            }
            for a in result.actions
        ],
        'components': [
            {
                'name': c.name,
                'description': c.description,
                'entities': c.entities,
                'actions': c.actions,
                'dependencies': c.dependencies
            }
            for c in result.components
        ],
        'metadata': result.metadata
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output_data, indent=2))
    print(f"Analysis complete. Results saved to: {output_path}")
    print(f"Found {len(result.entities)} entities, {len(result.actions)} actions, {len(result.components)} components")


if __name__ == "__main__":
    main()
