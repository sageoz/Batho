#!/usr/bin/env python3
"""
Task Breakdown Generator.

Generates detailed task specifications from analyzed requirements,
establishes dependencies, and orders tasks by complexity.

Example:
    $ python task_breakdown.py --analysis analysis_output.json
    $ python task_breakdown.py --requirements "Build a REST API"
"""

import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field
from datetime import datetime
from collections import defaultdict


@dataclass
class Task:
    """Represents a single implementation task."""
    id: str
    name: str
    description: str
    priority: str = "Medium"
    effort: str = "Medium"
    dependencies: List[str] = field(default_factory=list)
    acceptance_criteria: List[str] = field(default_factory=list)
    implementation_notes: List[str] = field(default_factory=list)
    files_to_create: List[str] = field(default_factory=list)
    files_to_modify: List[str] = field(default_factory=list)
    testing_requirements: List[str] = field(default_factory=list)
    definition_of_done: List[str] = field(default_factory=list)
    component: str = ""


@dataclass
class TaskBreakdownResult:
    """Result of task breakdown generation."""
    tasks: List[Task] = field(default_factory=list)
    dependency_graph: Dict[str, List[str]] = field(default_factory=dict)
    implementation_order: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    metadata: Dict = field(default_factory=dict)


class TaskBreakdownGenerator:
    """
    Generates detailed task specifications from requirements analysis.

    This class takes the output from RequirementsAnalyzer and produces
    detailed, implementable task specifications with proper dependencies.

    Attributes:
        config: Configuration options for task generation

    Example:
        >>> generator = TaskBreakdownGenerator()
        >>> result = generator.generate(analysis_result)
        >>> print(f"Generated {len(result.tasks)} tasks")
    """

    COMPONENT_TASK_TEMPLATES = {
        "CLI": {
            "base_tasks": [
                "Implement command handler",
                "Add argument parsing",
                "Create output formatter",
                "Add error handling",
                "Implement help system"
            ],
            "files_pattern": "batho/cli/",
            "effort": "Medium"
        },
        "Core": {
            "base_tasks": [
                "Update schema definitions",
                "Add contract interfaces",
                "Implement exception classes",
                "Update configuration",
                "Add core utilities"
            ],
            "files_pattern": "batho/core/",
            "effort": "Small"
        },
        "Modules/Compression": {
            "base_tasks": [
                "Implement compressor interface",
                "Add encoder/decoder",
                "Create archive handler",
                "Add compression options",
                "Implement error handling"
            ],
            "files_pattern": "batho/modules/compression/",
            "effort": "Large"
        },
        "Modules/Extraction": {
            "base_tasks": [
                "Implement extractor interface",
                "Add file parser",
                "Create content handler",
                "Add extraction options",
                "Implement error handling"
            ],
            "files_pattern": "batho/modules/extraction/",
            "effort": "Large"
        },
        "Modules/Graph": {
            "base_tasks": [
                "Implement graph data structure",
                "Add node operations",
                "Add edge operations",
                "Create graph algorithms",
                "Implement traversal methods"
            ],
            "files_pattern": "batho/modules/graph/",
            "effort": "Large"
        },
        "Modules/Integrity": {
            "base_tasks": [
                "Implement checksum calculator",
                "Add validation logic",
                "Create verification system",
                "Add integrity checks",
                "Implement error handling"
            ],
            "files_pattern": "batho/modules/integrity/",
            "effort": "Medium"
        },
        "Modules/Storage": {
            "base_tasks": [
                "Implement storage backend",
                "Add caching layer",
                "Create persistence handler",
                "Add storage options",
                "Implement error handling"
            ],
            "files_pattern": "batho/modules/storage/",
            "effort": "Large"
        },
        "Orchestrator": {
            "base_tasks": [
                "Implement build workflow",
                "Add export functionality",
                "Create patch system",
                "Add workflow coordination",
                "Implement error handling"
            ],
            "files_pattern": "batho/orchestrator/",
            "effort": "Large"
        }
    }

    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize the task breakdown generator.

        Args:
            config: Optional configuration dictionary
        """
        self.config = config or {}
        self.max_tasks = self.config.get('max_tasks', 50)
        self.min_tasks = self.config.get('min_tasks', 3)

    def generate(self, analysis_data: Dict) -> TaskBreakdownResult:
        """
        Generate task breakdown from analysis data.

        Args:
            analysis_data: Output from RequirementsAnalyzer

        Returns:
            TaskBreakdownResult with generated tasks and dependencies

        Raises:
            ValueError: If analysis data is invalid or incomplete
        """
        if not analysis_data:
            raise ValueError("Analysis data cannot be empty")

        result = TaskBreakdownResult()

        entities = analysis_data.get('entities', [])
        actions = analysis_data.get('actions', [])
        components = analysis_data.get('components', [])

        if not components:
            result.warnings.append("No components identified, generating generic tasks")
            components = [{'name': 'Core', 'description': 'Core functionality'}]

        tasks = self._generate_tasks_from_components(components, entities, actions)
        result.tasks = tasks[:self.max_tasks]

        result.dependency_graph = self._build_dependency_graph(result.tasks)

        has_cycle = self._detect_circular_dependencies(result.dependency_graph)
        if has_cycle:
            result.warnings.append(f"Circular dependencies detected: {has_cycle}")
            result.dependency_graph = self._break_circular_dependencies(
                result.dependency_graph, result.tasks
            )

        result.implementation_order = self._topological_sort(
            result.tasks, result.dependency_graph
        )

        result.metadata = {
            'generated_at': datetime.now().isoformat(),
            'task_count': len(result.tasks),
            'component_count': len(components),
            'warnings_count': len(result.warnings)
        }

        return result

    def _generate_tasks_from_components(
        self,
        components: List[Dict],
        entities: List[Dict],
        actions: List[Dict]
    ) -> List[Task]:
        """
        Generate tasks from identified components.

        Args:
            components: List of component dictionaries
            entities: List of entity dictionaries
            actions: List of action dictionaries

        Returns:
            List of Task objects
        """
        tasks = []
        task_counter = 1

        infrastructure_tasks = self._generate_infrastructure_tasks()
        tasks.extend(infrastructure_tasks)
        task_counter += len(infrastructure_tasks)

        sorted_components = sorted(
            components,
            key=lambda c: self._get_component_priority(c.get('name', '')),
            reverse=True
        )

        for component in sorted_components:
            component_name = component.get('name', 'Unknown')
            component_tasks = self._generate_component_tasks(
                component_name,
                component,
                entities,
                actions,
                task_counter
            )
            tasks.extend(component_tasks)
            task_counter += len(component_tasks)

        tasks = self._assign_priorities(tasks)
        tasks = self._assign_effort(tasks, entities, actions)

        return tasks

    def _get_component_priority(self, component_name: str) -> int:
        """
        Get priority order for component (lower = earlier in dependency chain).

        Args:
            component_name: Name of the component

        Returns:
            Priority number (lower = earlier)
        """
        priority_map = {
            "Core": 0,
            "CLI": 1,
            "Modules/Compression": 2,
            "Modules/Extraction": 2,
            "Modules/Graph": 2,
            "Modules/Integrity": 2,
            "Modules/Storage": 2,
            "Orchestrator": 3,
            "Unknown": 3
        }
        return priority_map.get(component_name, 3)

    def _generate_infrastructure_tasks(self) -> List[Task]:
        """
        Generate infrastructure tasks that should be done first.

        Returns:
            List of infrastructure tasks
        """
        tasks = [
            Task(
                id="T1",
                name="Set up project structure",
                description="Create the initial project directory structure, configuration files, and development environment",
                component="Core",
                files_to_create=[
                    "README.md",
                    ".gitignore",
                    "pyproject.toml or package.json",
                    "requirements.txt or package-lock.json",
                    "src/ or lib/ directory"
                ],
                implementation_notes=[
                    "Choose appropriate language/framework based on requirements",
                    "Set up virtual environment or container",
                    "Configure linting and formatting tools",
                    "Set up testing framework"
                ],
                testing_requirements=["Verify project builds successfully"],
                definition_of_done=["Project structure created", "Dependencies installable"]
            ),
            Task(
                id="T2",
                name="Set up logging and error handling",
                description="Configure application-wide logging and global error handling",
                component="Core",
                dependencies=["T1"],
                files_to_create=["src/logging.py", "src/exceptions.py"],
                implementation_notes=[
                    "Configure log levels (DEBUG, INFO, WARNING, ERROR)",
                    "Set up structured logging format",
                    "Create custom exception classes",
                    "Add global error handlers"
                ],
                testing_requirements=["Verify logs are written correctly", "Verify errors are handled gracefully"],
                definition_of_done=["Logging configured", "Error handling in place"]
            )
        ]
        return tasks

    def _generate_component_tasks(
        self,
        component_name: str,
        component: Dict,
        entities: List[Dict],
        actions: List[Dict],
        start_id: int
    ) -> List[Task]:
        """
        Generate tasks for a specific component.

        Args:
            component_name: Name of the component
            component: Component dictionary from analysis
            entities: List of entity dictionaries
            actions: List of action dictionaries
            start_id: Starting task ID number

        Returns:
            List of tasks for this component
        """
        tasks = []
        template = self.COMPONENT_TASK_TEMPLATES.get(
            component_name,
            self.COMPONENT_TASK_TEMPLATES["Core"]
        )

        base_tasks = template.get('base_tasks', [])
        component_entities = [
            e['name'] for e in entities
            if component_name.lower() in e.get('description', '').lower() or
               component_name.lower() in e.get('name', '').lower()
        ]
        component_actions = [
            a['name'] for a in actions
            if component_name.lower() in a.get('description', '').lower()
        ]

        for i, task_name in enumerate(base_tasks):
            task_id = f"T{start_id + i}"
            task = Task(
                id=task_id,
                name=task_name,
                description=self._generate_task_description(
                    component_name, task_name, component_entities, component_actions
                ),
                component=component_name,
                files_to_create=self._generate_file_list(component_name, task_name),
                implementation_notes=self._generate_implementation_notes(
                    component_name, task_name
                ),
                testing_requirements=self._generate_testing_requirements(task_name)
            )

            if component_name == "Core":
                task.dependencies = []
            elif component_name == "CLI":
                task.dependencies = ["T1"]
            elif component_name == "Modules/Compression":
                task.dependencies = ["T1"]
            elif component_name == "Modules/Extraction":
                task.dependencies = ["T1"]
            elif component_name == "Modules/Graph":
                task.dependencies = ["T1"]
            elif component_name == "Modules/Integrity":
                task.dependencies = ["T1"]
            elif component_name == "Modules/Storage":
                task.dependencies = ["T1"]
            elif component_name == "Orchestrator":
                task.dependencies = [f"T{i}" for i in range(1, start_id)]

            tasks.append(task)

        return tasks

    def _generate_task_description(
        self,
        component_name: str,
        task_name: str,
        entities: List[str],
        actions: List[str]
    ) -> str:
        """
        Generate a detailed task description.

        Args:
            component_name: Component name
            task_name: Task name
            entities: Related entities
            actions: Related actions

        Returns:
            Detailed task description
        """
        descriptions = {
            "CLI": {
                "Implement command handler": "Implement CLI command handler with argument parsing and validation",
                "Add argument parsing": "Add argument parsing using argparse or click",
                "Create output formatter": "Create output formatter for command results",
                "Add error handling": "Add error handling for CLI commands",
                "Implement help system": "Implement help system and documentation"
            },
            "Core": {
                "Update schema definitions": "Update schema definitions in batho/core/schemas.py",
                "Add contract interfaces": "Add contract interfaces in batho/core/contracts.py",
                "Implement exception classes": "Implement exception classes in batho/core/exceptions.py",
                "Update configuration": "Update configuration in batho/core/config/",
                "Add core utilities": "Add core utilities in batho/core/"
            },
            "Modules/Compression": {
                "Implement compressor interface": "Implement compressor interface following Batho compression patterns",
                "Add encoder/decoder": "Add encoder/decoder for compression format",
                "Create archive handler": "Create archive handler for compressed files",
                "Add compression options": "Add compression options and configuration",
                "Implement error handling": "Implement error handling for compression failures"
            },
            "Modules/Extraction": {
                "Implement extractor interface": "Implement extractor interface following Batho extraction patterns",
                "Add file parser": "Add file parser for extraction format",
                "Create content handler": "Create content handler for extracted data",
                "Add extraction options": "Add extraction options and configuration",
                "Implement error handling": "Implement error handling for extraction failures"
            },
            "Modules/Graph": {
                "Implement graph data structure": "Implement graph data structure for Batho code graph",
                "Add node operations": "Add node operations (add, remove, query)",
                "Add edge operations": "Add edge operations (add, remove, query)",
                "Create graph algorithms": "Create graph algorithms (traversal, shortest path)",
                "Implement traversal methods": "Implement traversal methods (DFS, BFS)"
            },
            "Modules/Integrity": {
                "Implement checksum calculator": "Implement checksum calculator for file integrity",
                "Add validation logic": "Add validation logic for integrity checks",
                "Create verification system": "Create verification system for integrity",
                "Add integrity checks": "Add integrity checks to Batho workflow",
                "Implement error handling": "Implement error handling for integrity failures"
            },
            "Modules/Storage": {
                "Implement storage backend": "Implement storage backend for Batho data",
                "Add caching layer": "Add caching layer for performance",
                "Create persistence handler": "Create persistence handler for data",
                "Add storage options": "Add storage options and configuration",
                "Implement error handling": "Implement error handling for storage failures"
            },
            "Orchestrator": {
                "Implement build workflow": "Implement build workflow in batho/orchestrator/build.py",
                "Add export functionality": "Add export functionality in batho/orchestrator/export.py",
                "Create patch system": "Create patch system in batho/orchestrator/",
                "Add workflow coordination": "Add workflow coordination for Batho operations",
                "Implement error handling": "Implement error handling for orchestrator failures"
            }
        }

        if component_name in descriptions and task_name in descriptions[component_name]:
            return descriptions[component_name][task_name]

        return f"Implement {task_name.lower()} for the {component_name} component"

    def _generate_file_list(self, component_name: str, task_name: str) -> List[str]:
        """
        Generate list of files to create for a task.

        Args:
            component_name: Component name
            task_name: Task name

        Returns:
            List of file paths
        """
        file_patterns = {
            "CLI": "batho/cli/",
            "Core": "batho/core/",
            "Modules/Compression": "batho/modules/compression/",
            "Modules/Extraction": "batho/modules/extraction/",
            "Modules/Graph": "batho/modules/graph/",
            "Modules/Integrity": "batho/modules/integrity/",
            "Modules/Storage": "batho/modules/storage/",
            "Orchestrator": "batho/orchestrator/"
        }

        base_path = file_patterns.get(component_name, "batho/")

        if "schema" in task_name.lower():
            return [f"{base_path}schemas.py"]
        elif "contract" in task_name.lower():
            return [f"{base_path}contracts.py"]
        elif "exception" in task_name.lower():
            return [f"{base_path}exceptions.py"]
        elif "config" in task_name.lower():
            return [f"{base_path}config/"]
        elif "handler" in task_name.lower():
            return [f"{base_path}handlers.py"]
        elif "interface" in task_name.lower():
            return [f"{base_path}interfaces.py"]
        elif "parser" in task_name.lower():
            return [f"{base_path}parsers.py"]
        elif "algorithm" in task_name.lower():
            return [f"{base_path}algorithms.py"]
        elif "backend" in task_name.lower():
            return [f"{base_path}backend.py"]
        elif "workflow" in task_name.lower():
            return [f"{base_path}workflows.py"]
        else:
            return [f"{base_path}{task_name.lower().replace(' ', '_')}.py"]

    def _generate_implementation_notes(self, component_name: str, task_name: str) -> List[str]:
        """
        Generate implementation notes for a task.

        Args:
            component_name: Component name
            task_name: Task name

        Returns:
            List of implementation notes
        """
        notes = [
            "Follow existing code style and conventions",
            "Add appropriate error handling",
            "Include logging for debugging",
            "Consider performance implications",
            "Document public interfaces"
        ]

        if "authentication" in component_name.lower() or "password" in task_name.lower():
            notes.append("Use secure cryptographic libraries")
            notes.append("Never log sensitive information")

        if "api" in component_name.lower():
            notes.append("Follow RESTful design principles")
            notes.append("Use appropriate HTTP status codes")

        return notes

    def _generate_testing_requirements(self, task_name: str) -> List[str]:
        """
        Generate testing requirements for a task.

        Args:
            task_name: Task name

        Returns:
            List of testing requirements
        """
        requirements = ["Write unit tests for core functionality"]

        if "database" in task_name.lower() or "model" in task_name.lower():
            requirements.append("Test data persistence")
            requirements.append("Test data validation")

        if "api" in task_name.lower() or "endpoint" in task_name.lower():
            requirements.append("Test API endpoints with mock data")
            requirements.append("Test error responses")

        if "auth" in task_name.lower():
            requirements.append("Test authentication flows")
            requirements.append("Test security edge cases")

        return requirements

    def _assign_priorities(self, tasks: List[Task]) -> List[Task]:
        """
        Assign priorities to tasks based on dependencies and component.

        Args:
            tasks: List of tasks

        Returns:
            Tasks with priorities assigned
        """
        for task in tasks:
            if task.dependencies:
                task.priority = "High"
            elif task.component in ["Infrastructure"]:
                task.priority = "High"
            elif task.component in ["Authentication", "API Layer"]:
                task.priority = "Medium"
            else:
                task.priority = "Medium"

        return tasks

    def _assign_effort(self, tasks: List[Task], entities: List[Dict], actions: List[Dict]) -> List[Task]:
        """
        Estimate effort for each task based on complexity.

        Args:
            tasks: List of tasks
            entities: List of entities
            actions: List of actions

        Returns:
            Tasks with effort estimates
        """
        total_entities = len(entities)
        total_actions = len(actions)
        complexity = (total_entities + total_actions) / 10

        for task in tasks:
            if complexity > 5:
                task.effort = "Large"
            elif complexity > 2:
                task.effort = "Medium"
            else:
                task.effort = "Small"

        return tasks

    def _build_dependency_graph(self, tasks: List[Task]) -> Dict[str, List[str]]:
        """
        Build a dependency graph from tasks.

        Args:
            tasks: List of tasks

        Returns:
            Dictionary mapping task IDs to their dependencies
        """
        graph = {}
        for task in tasks:
            graph[task.id] = task.dependencies.copy()
        return graph

    def _detect_circular_dependencies(self, graph: Dict[str, List[str]]) -> Optional[List[str]]:
        """
        Detect circular dependencies in the graph.

        Args:
            graph: Dependency graph

        Returns:
            List of nodes in cycle, or None if no cycle
        """
        visited = set()
        rec_stack = set()
        path = []

        def dfs(node: str) -> Optional[List[str]]:
            visited.add(node)
            rec_stack.add(node)
            path.append(node)

            for neighbor in graph.get(node, []):
                if neighbor not in visited:
                    cycle = dfs(neighbor)
                    if cycle:
                        return cycle
                elif neighbor in rec_stack:
                    cycle_start = path.index(neighbor)
                    return path[cycle_start:] + [neighbor]

            path.pop()
            rec_stack.remove(node)
            return None

        for node in graph:
            if node not in visited:
                cycle = dfs(node)
                if cycle:
                    return cycle

        return None

    def _break_circular_dependencies(
        self,
        graph: Dict[str, List[str]],
        tasks: List[Task]
    ) -> Dict[str, List[str]]:
        """
        Break circular dependencies by removing the weakest dependency.

        Args:
            graph: Dependency graph with cycles
            tasks: List of tasks

        Returns:
            Graph with cycles broken
        """
        task_map = {t.id: t for t in tasks}

        for task_id in list(graph.keys()):
            deps = graph[task_id]
            if len(deps) > 1:
                weakest = min(deps, key=lambda d: task_map.get(d, Task(id="", name="")).priority)
                graph[task_id].remove(weakest)

        return graph

    def _topological_sort(
        self,
        tasks: List[Task],
        graph: Dict[str, List[str]]
    ) -> List[str]:
        """
        Perform topological sort to get implementation order.

        Args:
            tasks: List of tasks
            graph: Dependency graph

        Returns:
            List of task IDs in execution order
        """
        in_degree = {task.id: 0 for task in tasks}
        for task_id, deps in graph.items():
            for dep in deps:
                if dep in in_degree:
                    in_degree[dep] = in_degree.get(dep, 0)

        for deps in graph.values():
            for dep in deps:
                in_degree[dep] = in_degree.get(dep, 0) + 1

        queue = [task_id for task_id, degree in in_degree.items() if degree == 0]
        result = []

        while queue:
            current = queue.pop(0)
            result.append(current)

            for task_id, deps in graph.items():
                if current in deps:
                    in_degree[task_id] -= 1
                    if in_degree[task_id] == 0:
                        queue.append(task_id)

        for task in tasks:
            if task.id not in result:
                result.append(task.id)

        return result


def main():
    """Main function for command-line usage."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate task breakdown from requirements analysis"
    )
    parser.add_argument(
        '--analysis', '-a',
        help='Analysis JSON file from analyzer.py'
    )
    parser.add_argument(
        '--requirements', '-r',
        help='Raw requirements text'
    )
    parser.add_argument(
        '--output', '-o',
        default='task_breakdown.json',
        help='Output file for task breakdown'
    )
    parser.add_argument(
        '--config',
        help='Configuration file (JSON)'
    )

    args = parser.parse_args()

    if not args.analysis and not args.requirements:
        parser.error("Either --analysis or --requirements must be provided")

    config = {}
    if args.config:
        config = json.loads(Path(args.config).read_text())

    generator = TaskBreakdownGenerator(config)

    if args.analysis:
        analysis_data = json.loads(Path(args.analysis).read_text())
    else:
        from analyzer import RequirementsAnalyzer
        analyzer = RequirementsAnalyzer(config)
        result = analyzer.analyze(args.requirements)
        analysis_data = {
            'entities': [
                {'name': e.name, 'type': e.entity_type, 'description': e.description}
                for e in result.entities
            ],
            'actions': [
                {'name': a.name, 'type': a.action_type, 'target': a.target, 'description': a.description}
                for a in result.actions
            ],
            'components': [
                {'name': c.name, 'description': c.description, 'entities': c.entities, 'actions': c.actions}
                for c in result.components
            ]
        }

    result = generator.generate(analysis_data)

    output_data = {
        'tasks': [
            {
                'id': t.id,
                'name': t.name,
                'description': t.description,
                'priority': t.priority,
                'effort': t.effort,
                'dependencies': t.dependencies,
                'component': t.component,
                'files_to_create': t.files_to_create,
                'implementation_notes': t.implementation_notes,
                'testing_requirements': t.testing_requirements
            }
            for t in result.tasks
        ],
        'dependency_graph': result.dependency_graph,
        'implementation_order': result.implementation_order,
        'warnings': result.warnings,
        'metadata': result.metadata
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output_data, indent=2))
    print(f"Task breakdown complete. Results saved to: {output_path}")
    print(f"Generated {len(result.tasks)} tasks in {len(set(t.component for t in result.tasks))} components")
    if result.warnings:
        print(f"Warnings: {result.warnings}")


if __name__ == "__main__":
    main()
