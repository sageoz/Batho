#!/usr/bin/env python3
"""
Specification Writer.

Generates markdown specification documents from task breakdowns.

Example:
    $ python spec_writer.py --tasks task_breakdown.json --output spec-output.md
"""

import json
import sys
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime


class SpecificationWriter:
    """
    Generates markdown specification documents from task breakdowns.

    This class takes the output from TaskBreakdownGenerator and produces
    formatted markdown documents with task specifications, dependency graphs,
    and implementation guidance.

    Attributes:
        config: Configuration options for output generation

    Example:
        >>> writer = SpecificationWriter()
        >>> writer.write(task_breakdown, "spec-output.md")
    """

    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize the specification writer.

        Args:
            config: Optional configuration dictionary
        """
        self.config = config or {}
        self.include_mermaid = self.config.get('include_mermaid', True)
        self.include_toc = self.config.get('include_toc', True)

    def write(
        self,
        task_breakdown: Dict,
        output_path: str,
        project_name: str = "Project",
        source_description: str = "User requirements"
    ) -> str:
        """
        Write task breakdown to a markdown specification file.

        Args:
            task_breakdown: Task breakdown data from TaskBreakdownGenerator
            output_path: Path to write the markdown file
            project_name: Name of the project
            source_description: Description of the requirements source

        Returns:
            Path to the written file

        Raises:
            ValueError: If task breakdown is invalid
        """
        if not task_breakdown or 'tasks' not in task_breakdown:
            raise ValueError("Invalid task breakdown data")

        tasks = task_breakdown.get('tasks', [])
        dependency_graph = task_breakdown.get('dependency_graph', {})
        implementation_order = task_breakdown.get('implementation_order', [])
        warnings = task_breakdown.get('warnings', [])
        metadata = task_breakdown.get('metadata', {})

        markdown = self._generate_markdown(
            tasks=tasks,
            dependency_graph=dependency_graph,
            implementation_order=implementation_order,
            warnings=warnings,
            metadata=metadata,
            project_name=project_name,
            source_description=source_description
        )

        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(markdown, encoding='utf-8')

        return str(output)

    def _generate_markdown(
        self,
        tasks: List[Dict],
        dependency_graph: Dict,
        implementation_order: List[str],
        warnings: List[str],
        metadata: Dict,
        project_name: str,
        source_description: str
    ) -> str:
        """
        Generate the complete markdown document.

        Args:
            tasks: List of task dictionaries
            dependency_graph: Dependency graph
            implementation_order: Ordered list of task IDs
            warnings: List of warnings
            metadata: Metadata about the breakdown
            project_name: Project name
            source_description: Source of requirements

        Returns:
            Complete markdown string
        """
        lines = []

        lines.append(f"# Project Specification: {project_name}")
        lines.append("")
        lines.append(f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"**Source**: {source_description}")
        lines.append(f"**Total Tasks**: {len(tasks)}")
        lines.append("")

        lines.extend(self._generate_executive_summary(tasks))

        if self.include_mermaid:
            lines.append("")
            lines.append("## Task Dependency Graph")
            lines.append("")
            lines.append("```mermaid")
            lines.append("graph TD")
            for task in tasks:
                lines.append(f'    {task["id"]}["{task["name"]}"]')
            for task_id, deps in dependency_graph.items():
                for dep in deps:
                    lines.append(f"    {dep} --> {task_id}")
            lines.append("```")
            lines.append("")

        lines.append("")
        lines.append("## Task Breakdown")
        lines.append("")

        for task in tasks:
            lines.extend(self._generate_task_section(task))

        lines.append("")
        lines.append("## Implementation Order")
        lines.append("")
        for i, task_id in enumerate(implementation_order, 1):
            task = next((t for t in tasks if t['id'] == task_id), None)
            if task:
                lines.append(f"{i}. **{task_id}**: {task['name']}")
                if task.get('dependencies'):
                    lines.append(f"   - Dependencies: {', '.join(task['dependencies'])}")
        lines.append("")

        if warnings:
            lines.append("")
            lines.append("## Warnings")
            lines.append("")
            for warning in warnings:
                lines.append(f"- {warning}")
            lines.append("")

        lines.extend(self._generate_risk_assessment(tasks))

        lines.append("")
        lines.append("---")
        lines.append(f"*Generated by spec-generator-skill v1.0.0*")

        return "\n".join(lines)

    def _generate_executive_summary(self, tasks: List[Dict]) -> List[str]:
        """
        Generate executive summary section.

        Args:
            tasks: List of tasks

        Returns:
            List of markdown lines
        """
        lines = []
        lines.append("")
        lines.append("## Executive Summary")
        lines.append("")

        components = set(task.get('component', 'Unknown') for task in tasks)
        high_priority = sum(1 for task in tasks if task.get('priority') == 'High')
        medium_priority = sum(1 for task in tasks if task.get('priority') == 'Medium')
        low_priority = sum(1 for task in tasks if task.get('priority') == 'Low')

        summary = (
            f"This specification defines {len(tasks)} implementation tasks "
            f"across {len(components)} components. "
        )

        if high_priority > 0:
            summary += f"{high_priority} high-priority tasks require immediate attention. "
        if medium_priority > 0:
            summary += f"{medium_priority} tasks are planned for the next phase. "
        if low_priority > 0:
            summary += f"{low_priority} tasks are lower priority and can be deferred. "

        summary += (
            "Tasks are ordered to respect dependencies, with infrastructure "
            "and foundational components implemented first."
        )

        lines.append(summary)
        lines.append("")

        lines.append("### Component Overview")
        lines.append("")
        lines.append("| Component | Tasks | Priority Distribution |")
        lines.append("|-----------|-------|----------------------|")

        component_stats = {}
        for task in tasks:
            comp = task.get('component', 'Unknown')
            if comp not in component_stats:
                component_stats[comp] = {'total': 0, 'high': 0, 'medium': 0, 'low': 0}
            component_stats[comp]['total'] += 1
            priority = task.get('priority', 'Medium').lower()
            if priority in component_stats[comp]:
                component_stats[comp][priority] += 1

        for comp, stats in sorted(component_stats.items()):
            dist = f"H:{stats['high']} M:{stats['medium']} L:{stats['low']}"
            lines.append(f"| {comp} | {stats['total']} | {dist} |")

        lines.append("")

        return lines

    def _generate_task_section(self, task: Dict) -> List[str]:
        """
        Generate markdown for a single task.

        Args:
            task: Task dictionary

        Returns:
            List of markdown lines
        """
        lines = []

        priority_emoji = {
            'High': '🔴',
            'Medium': '🟡',
            'Low': '🟢'
        }

        emoji = priority_emoji.get(task.get('priority', 'Medium'), '🟡')

        lines.append(f"### {task['id']}: {task['name']} {emoji}")
        lines.append("")
        lines.append(f"**Priority**: {task.get('priority', 'Medium')} | "
                    f"**Effort**: {task.get('effort', 'Medium')} | "
                    f"**Component**: {task.get('component', 'Unknown')}")
        lines.append("")

        if task.get('dependencies'):
            deps = ', '.join(task['dependencies'])
            lines.append(f"**Dependencies**: {deps}")
            lines.append("")

        lines.append("#### Description")
        lines.append("")
        lines.append(task.get('description', 'No description provided'))
        lines.append("")

        lines.append("#### Acceptance Criteria")
        lines.append("")
        criteria = task.get('implementation_notes', [])[:5]
        if criteria:
            for criterion in criteria:
                lines.append(f"- [ ] {criterion}")
        else:
            lines.append("- [ ] Implementation completed")
            lines.append("- [ ] Tests passing")
            lines.append("- [ ] Code reviewed")
        lines.append("")

        if task.get('implementation_notes'):
            lines.append("#### Implementation Notes")
            lines.append("")
            for note in task['implementation_notes']:
                lines.append(f"- {note}")
            lines.append("")

        files_to_create = task.get('files_to_create', [])
        if files_to_create:
            lines.append("#### Files to Create")
            lines.append("")
            for file_path in files_to_create:
                lines.append(f"- `{file_path}`")
            lines.append("")

        testing = task.get('testing_requirements', [])
        if testing:
            lines.append("#### Testing Requirements")
            lines.append("")
            for test in testing:
                lines.append(f"- {test}")
            lines.append("")

        lines.append("---")
        lines.append("")

        return lines

    def _generate_risk_assessment(self, tasks: List[Dict]) -> List[str]:
        """
        Generate risk assessment section.

        Args:
            tasks: List of tasks

        Returns:
            List of markdown lines
        """
        lines = []
        lines.append("")
        lines.append("## Risk Assessment")
        lines.append("")

        high_priority_tasks = [t for t in tasks if t.get('priority') == 'High']
        large_effort_tasks = [t for t in tasks if t.get('effort') == 'Large']
        tasks_with_deps = [t for t in tasks if t.get('dependencies')]

        risks = []

        if len(high_priority_tasks) > 5:
            risks.append({
                'risk': 'Many high-priority tasks',
                'mitigation': 'Prioritize and break into smaller sprints'
            })

        if len(large_effort_tasks) > 3:
            risks.append({
                'risk': 'Multiple large-effort tasks',
                'mitigation': 'Consider adding more resources or extending timeline'
            })

        if tasks_with_deps:
            risks.append({
                'risk': 'Complex task dependencies',
                'mitigation': 'Follow implementation order strictly; address blocking tasks first'
            })

        if not risks:
            risks.append({
                'risk': 'No significant risks identified',
                'mitigation': 'Proceed with implementation as planned'
            })

        for item in risks:
            lines.append(f"- **{item['risk']}**: {item['mitigation']}")

        lines.append("")

        return lines

    def write_detailed_specs(
        self,
        task_breakdown: Dict,
        output_dir: str,
        project_name: str = "Project"
    ) -> Dict[str, List[str]]:
        """
        Write detailed task specifications to separate .md files in component folders.

        Creates a folder structure like:
        output_dir/
        ├── SPEC_INDEX.md
        ├── infrastructure/
        │   ├── T1_project_structure.md
        │   └── T2_logging_error_handling.md
        ├── data_layer/
        │   ├── T3_database_schema.md
        │   └── ...
        └── ...

        Args:
            task_breakdown: Task breakdown data
            output_dir: Base directory to write specs
            project_name: Name of the project

        Returns:
            Dictionary mapping folders to lists of written file paths
        """
        tasks = task_breakdown.get('tasks', [])
        dependency_graph = task_breakdown.get('dependency_graph', {})
        implementation_order = task_breakdown.get('implementation_order', [])
        metadata = task_breakdown.get('metadata', {})

        base_path = Path(output_dir)
        base_path.mkdir(parents=True, exist_ok=True)

        written_files = {}
        component_folders = {}

        for task in tasks:
            component = task.get('component', 'Unknown')
            folder_name = self._sanitize_folder_name(component)

            if folder_name not in component_folders:
                component_folders[folder_name] = component

            # Handle nested folder paths (e.g., modules/compression)
            folder_parts = folder_name.split('/')
            folder_path = base_path
            for part in folder_parts:
                folder_path = folder_path / part
            folder_path.mkdir(parents=True, exist_ok=True)

            spec_content = self._generate_detailed_task_spec(
                task, project_name, tasks, dependency_graph
            )
            file_name = f"{task['id']}_{self._sanitize_file_name(task['name'])}.md"
            file_path = folder_path / file_name
            file_path.write_text(spec_content, encoding='utf-8')

            if folder_name not in written_files:
                written_files[folder_name] = []
            written_files[folder_name].append(str(file_path))

        index_content = self._generate_spec_index(
            project_name, tasks, component_folders, implementation_order, metadata
        )
        index_path = base_path / "SPEC_INDEX.md"
        index_path.write_text(index_content, encoding='utf-8')

        return written_files

    def _sanitize_folder_name(self, name: str) -> str:
        """Convert component name to valid folder name."""
        # Split by '/' first to preserve nested structure
        parts = name.split('/')
        sanitized_parts = []
        for part in parts:
            part = part.lower()
            part = part.replace(' ', '-').replace('_', '-')
            part = ''.join(c if c.isalnum() or c in '-' else '' for c in part)
            sanitized_parts.append(part)
        return '/'.join(sanitized_parts)

    def _sanitize_file_name(self, name: str) -> str:
        """Convert task name to valid file name."""
        name = name.lower()
        name = name.replace(' ', '_').replace('-', '_')
        name = ''.join(c if c.isalnum() or c == '_' else '' for c in name)
        return name

    def _generate_detailed_task_spec(
        self,
        task: Dict,
        project_name: str,
        all_tasks: List[Dict],
        dependency_graph: Dict
    ) -> str:
        """Generate a detailed specification for a single task."""
        lines = []

        priority_emoji = {'High': '🔴', 'Medium': '🟡', 'Low': '🟢'}
        effort_icons = {'Small': '⚡', 'Medium': '⚡⚡', 'Large': '⚡⚡⚡'}

        lines.append(f"# {task['id']}: {task['name']}")
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append(f"**Project**: {project_name}")
        lines.append(f"**Component**: {task.get('component', 'Unknown')}")
        lines.append(f"**Priority**: {priority_emoji.get(task.get('priority', 'Medium'), '🟡')} {task.get('priority', 'Medium')}")
        lines.append(f"**Estimated Effort**: {effort_icons.get(task.get('effort', 'Medium'), '⚡⚡')} {task.get('effort', 'Medium')}")
        lines.append(f"**Task ID**: {task['id']}")
        lines.append("")

        deps = task.get('dependencies', [])
        if deps:
            lines.append("## Dependencies")
            lines.append("")
            for dep_id in deps:
                dep_task = next((t for t in all_tasks if t['id'] == dep_id), None)
                if dep_task:
                    lines.append(f"- **{dep_id}**: {dep_task['name']}")
                else:
                    lines.append(f"- **{dep_id}**")
            lines.append("")

        lines.append("## Description")
        lines.append("")
        lines.append(task.get('description', 'No description provided.'))
        lines.append("")

        lines.append("## Detailed Requirements")
        lines.append("")
        notes = task.get('implementation_notes', [])
        if notes:
            for i, note in enumerate(notes, 1):
                lines.append(f"{i}. {note}")
        else:
            lines.append("- Implementation follows project conventions")
            lines.append("- Code passes all linting checks")
            lines.append("- Error handling is comprehensive")
        lines.append("")

        lines.append("## Acceptance Criteria")
        lines.append("")
        lines.append("Complete implementation when ALL of the following are true:")
        lines.append("")
        lines.append("### Functional Requirements")
        lines.append("")
        for i, note in enumerate(notes[:3], 1):
            lines.append(f"- [ ] {note}")
        lines.append("- [ ] Feature works as specified in description")
        lines.append("")

        lines.append("### Non-Functional Requirements")
        lines.append("")
        lines.append("- [ ] Code follows project style guide")
        lines.append("- [ ] No security vulnerabilities")
        lines.append("- [ ] Performance meets requirements")
        lines.append("- [ ] Error handling is robust")
        lines.append("")

        files_to_create = task.get('files_to_create', [])
        if files_to_create:
            lines.append("## Files to Create")
            lines.append("")
            for file_path in files_to_create:
                lines.append(f"### `{file_path}`")
                lines.append("")
                lines.append("*Purpose and implementation details go here*")
                lines.append("")
            lines.append("")

        lines.append("## Technical Implementation")
        lines.append("")
        lines.append("### Architecture Considerations")
        lines.append("")
        lines.append("- How this task fits into the overall architecture")
        lines.append("- Key interfaces or contracts to maintain")
        lines.append("- Dependencies on other components")
        lines.append("")

        lines.append("### Data Models (if applicable)")
        lines.append("")
        lines.append("```python")
        lines.append("# Define data models here")
        lines.append("```")
        lines.append("")

        lines.append("### API Contracts (if applicable)")
        lines.append("")
        lines.append("```yaml")
        lines.append("# API endpoint definitions")
        lines.append("```")
        lines.append("")

        lines.append("### Edge Cases")
        lines.append("")
        lines.append("- Handle null/empty inputs gracefully")
        lines.append("- Handle concurrent access if applicable")
        lines.append("- Handle network failures if applicable")
        lines.append("- Handle validation errors with clear messages")
        lines.append("")

        testing = task.get('testing_requirements', [])
        if testing:
            lines.append("## Testing Strategy")
            lines.append("")
            lines.append("### Unit Tests")
            lines.append("")
            for test in testing:
                lines.append(f"- {test}")
            lines.append("")
            lines.append("### Integration Tests")
            lines.append("")
            lines.append("- Test with real dependencies")
            lines.append("- Test error scenarios")
            lines.append("")
            lines.append("### Test Coverage")
            lines.append("")
            lines.append("- Aim for >80% code coverage")
            lines.append("- Critical paths should have 100% coverage")
            lines.append("")
        else:
            lines.append("## Testing Strategy")
            lines.append("")
            lines.append("- Write unit tests for core functionality")
            lines.append("- Test edge cases and error conditions")
            lines.append("- Aim for >80% code coverage")
            lines.append("")

        dependents = [t['id'] for t in all_tasks if task['id'] in t.get('dependencies', [])]
        if dependents:
            lines.append("## Tasks That Depend On This")
            lines.append("")
            for dep_id in dependents:
                dep_task = next((t for t in all_tasks if t['id'] == dep_id), None)
                if dep_task:
                    lines.append(f"- **{dep_id}**: {dep_task['name']}")
            lines.append("")

        lines.append("## Definition of Done")
        lines.append("")
        lines.append("- [ ] All acceptance criteria met")
        lines.append("- [ ] All tests passing")
        lines.append("- [ ] Code reviewed and approved")
        lines.append("- [ ] Documentation updated")
        lines.append("- [ ] No linting errors")
        lines.append("- [ ] Security scan passed")
        lines.append("")

        lines.append("---")
        lines.append(f"*Generated by spec-generator-skill | {task['id']} | {task.get('component', 'Unknown')}*")

        return "\n".join(lines)

    def _generate_spec_index(
        self,
        project_name: str,
        tasks: List[Dict],
        component_folders: Dict[str, str],
        implementation_order: List[str],
        metadata: Dict
    ) -> str:
        """Generate the specification index file."""
        lines = []

        lines.append(f"# {project_name} - Specification Index")
        lines.append("")
        lines.append(f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"**Total Tasks**: {len(tasks)}")
        lines.append("")

        lines.append("## Overview")
        lines.append("")
        lines.append(f"This specification contains {len(tasks)} detailed task specifications ")
        lines.append(f"organized by {len(component_folders)} components.")
        lines.append("")

        lines.append("## Component Structure")
        lines.append("")
        for folder, component in sorted(component_folders.items()):
            component_tasks = [t for t in tasks if t.get('component') == component]
            lines.append(f"### {component}")
            lines.append("")
            lines.append(f"**Location**: `./{folder}/`")
            lines.append(f"**Tasks**: {len(component_tasks)}")
            lines.append("")
            lines.append("| Task ID | Name | Priority | Effort |")
            lines.append("|---------|------|----------|--------|")
            for t in sorted(component_tasks, key=lambda x: x['id']):
                lines.append(f"| {t['id']} | {t['name']} | {t.get('priority', 'Medium')} | {t.get('effort', 'Medium')} |")
            lines.append("")

        lines.append("## Implementation Order")
        lines.append("")
        lines.append("Recommended order for implementation (respects dependencies):")
        lines.append("")
        for i, task_id in enumerate(implementation_order, 1):
            task = next((t for t in tasks if t['id'] == task_id), None)
            if task:
                lines.append(f"{i}. **{task_id}** - {task['name']} ({task.get('component', 'Unknown')})")
        lines.append("")

        lines.append("## Quick Reference")
        lines.append("")
        lines.append("| Folder | Component | Tasks |")
        lines.append("|--------|-----------|-------|")
        for folder, component in sorted(component_folders.items()):
            count = len([t for t in tasks if t.get('component') == component])
            lines.append(f"| `{folder}/` | {component} | {count} |")
        lines.append("")

        lines.append("## Usage")
        lines.append("")
        lines.append("1. Review the component structure above")
        lines.append("2. Start with infrastructure tasks (T1, T2)")
        lines.append("3. Follow the implementation order")
        lines.append("4. Each task folder contains detailed specifications")
        lines.append("")

        lines.append("---")
        lines.append("*Generated by spec-generator-skill v1.0.0*")

        return "\n".join(lines)

    def write_agent_skill_format(
        self,
        task_breakdown: Dict,
        output_dir: str,
        project_name: str = "Feature"
    ) -> List[str]:
        """
        Write task breakdown in agent-skill-creator compatible format.

        Args:
            task_breakdown: Task breakdown data
            output_dir: Directory to write individual task specs
            project_name: Name of the project

        Returns:
            List of written file paths
        """
        tasks = task_breakdown.get('tasks', [])
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        written_files = []

        for task in tasks:
            spec_content = self._generate_agent_skill_spec(task, project_name)
            file_name = f"{task['id']}_{task['name'].lower().replace(' ', '_')}.md"
            file_path = output_path / file_name
            file_path.write_text(spec_content, encoding='utf-8')
            written_files.append(str(file_path))

        return written_files

    def _generate_agent_skill_spec(self, task: Dict, project_name: str) -> str:
        """
        Generate agent-skill-creator compatible specification.

        Args:
            task: Task dictionary
            project_name: Project name

        Returns:
            Markdown specification string
        """
        lines = []

        lines.append(f"# Task: {task['name']}")
        lines.append("")
        lines.append(f"**Project**: {project_name}")
        lines.append(f"**Task ID**: {task['id']}")
        lines.append(f"**Priority**: {task.get('priority', 'Medium')}")
        lines.append(f"**Effort**: {task.get('effort', 'Medium')}")
        lines.append(f"**Component**: {task.get('component', 'Unknown')}")
        lines.append("")

        if task.get('dependencies'):
            lines.append(f"**Dependencies**: {', '.join(task['dependencies'])}")
            lines.append("")

        lines.append("## Description")
        lines.append("")
        lines.append(task.get('description', ''))
        lines.append("")

        lines.append("## Requirements")
        lines.append("")
        for note in task.get('implementation_notes', []):
            lines.append(f"- {note}")
        lines.append("")

        files = task.get('files_to_create', [])
        if files:
            lines.append("## Files to Create")
            lines.append("")
            for f in files:
                lines.append(f"- `{f}`")
            lines.append("")

        testing = task.get('testing_requirements', [])
        if testing:
            lines.append("## Testing")
            lines.append("")
            for t in testing:
                lines.append(f"- {t}")
            lines.append("")

        return "\n".join(lines)


def main():
    """Main function for command-line usage."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate markdown specification from task breakdown"
    )
    parser.add_argument(
        '--tasks', '-t',
        required=True,
        help='Task breakdown JSON file from task_breakdown.py'
    )
    parser.add_argument(
        '--output', '-o',
        default='.specs/feature',
        help='Output markdown file or directory (default: .specs/<feature_name>/)'
    )
    parser.add_argument(
        '--project-name', '-p',
        default='Project',
        help='Project name for the specification'
    )
    parser.add_argument(
        '--source',
        default='User requirements',
        help='Description of requirements source'
    )
    parser.add_argument(
        '--detailed',
        '-d',
        action='store_true',
        help='Generate detailed separate .md files in component folders'
    )
    parser.add_argument(
        '--agent-format',
        action='store_true',
        help='Also generate agent-skill-creator format'
    )
    parser.add_argument(
        '--config',
        help='Configuration file (JSON)'
    )

    args = parser.parse_args()

    config = {}
    if args.config:
        config = json.loads(Path(args.config).read_text())

    task_breakdown = json.loads(Path(args.tasks).read_text())

    writer = SpecificationWriter(config)

    if args.detailed:
        output_dir = args.output if args.output.endswith('/') or '.' in args.output.split('/')[-1] else args.output
        result = writer.write_detailed_specs(task_breakdown, output_dir, args.project_name)
        print(f"Detailed specifications written to: {output_dir}")
        for folder, files in result.items():
            print(f"\n{folder}/")
            for f in files:
                print(f"  - {Path(f).name}")
    else:
        output_path = writer.write(
            task_breakdown,
            args.output,
            args.project_name,
            args.source
        )
        print(f"Specification written to: {output_path}")

    if args.agent_format:
        agent_dir = Path(args.output).parent / "agent_specs"
        files = writer.write_agent_skill_format(task_breakdown, str(agent_dir), args.project_name)
        print(f"Agent skill specs written to: {agent_dir}")
        for f in files:
            print(f"  - {f}")


if __name__ == "__main__":
    main()
