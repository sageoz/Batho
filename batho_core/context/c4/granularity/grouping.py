"""
Component grouping system for virtual organization in views.
"""

from enum import Enum
from typing import Dict, List, Any, Optional, Set, Tuple
from dataclasses import dataclass
from collections import defaultdict, Counter
from pathlib import Path

from batho_core.utils.logging import get_logger
from .analyzer import RepositoryMetrics

logger = get_logger(__name__, component="granularity_grouping")


class GroupingStrategy(Enum):
    """Strategies for grouping components."""
    DOMAIN = "domain"           # Group by package/domain boundaries
    FUNCTIONAL = "functional"   # Group by functional cohesion
    DATA_FLOW = "data_flow"     # Group by data flow patterns
    TEAM = "team"              # Group by team ownership
    CUSTOM = "custom"          # User-defined grouping rules
    HYBRID = "hybrid"          # Multiple strategies combined


@dataclass
class ComponentGroup:
    """Represents a virtual group of components."""
    id: str
    name: str
    description: str
    component_ids: List[str]
    strategy: GroupingStrategy
    metadata: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "componentIds": self.component_ids,
            "strategy": self.strategy.value,
            "metadata": self.metadata
        }


class ComponentGroupingManager:
    """Manages virtual component grouping for views."""
    
    def __init__(self):
        self.logger = get_logger(self.__class__.__name__, component="granularity_grouping")
        self.custom_rules: List[Dict[str, Any]] = []
    
    def add_custom_rule(self, rule: Dict[str, Any]) -> None:
        """
        Add a custom grouping rule.
        
        Args:
            rule: Dictionary with rule definition
        """
        self.custom_rules.append(rule)
        self.logger.info("Added custom grouping rule", rule_count=len(self.custom_rules))
    
    def group_components(
        self,
        components: List[Dict[str, Any]],
        strategy: GroupingStrategy,
        graph: Dict[str, Any],
        repomap: Dict[str, Any],
        metrics: Optional[RepositoryMetrics] = None
    ) -> List[ComponentGroup]:
        """
        Group components using specified strategy.
        
        Args:
            components: List of component dictionaries
            strategy: Grouping strategy to use
            graph: Repository graph
            repomap: Repository map
            metrics: Repository metrics (optional)
            
        Returns:
            List of ComponentGroup objects
        """
        self.logger.info("Grouping components", strategy=strategy.value, component_count=len(components))
        
        if strategy == GroupingStrategy.DOMAIN:
            return self._group_by_domain(components, graph, repomap)
        elif strategy == GroupingStrategy.FUNCTIONAL:
            return self._group_by_functional_cohesion(components, graph, repomap)
        elif strategy == GroupingStrategy.DATA_FLOW:
            return self._group_by_data_flow(components, graph, repomap)
        elif strategy == GroupingStrategy.TEAM:
            return self._group_by_team_ownership(components, graph, repomap)
        elif strategy == GroupingStrategy.CUSTOM:
            return self._group_by_custom_rules(components, graph, repomap)
        elif strategy == GroupingStrategy.HYBRID:
            return self._group_hybrid(components, graph, repomap, metrics)
        else:
            self.logger.warning("Unknown grouping strategy", strategy=strategy)
            return []
    
    def _group_by_domain(
        self,
        components: List[Dict[str, Any]],
        graph: Dict[str, Any],
        repomap: Dict[str, Any]
    ) -> List[ComponentGroup]:
        """Group components by domain/package boundaries."""
        domain_groups = defaultdict(list)
        
        for component in components:
            file_path = component.get("properties", {}).get("file", "")
            if file_path:
                # Extract domain from package structure
                parts = Path(file_path).parts
                if len(parts) > 1:
                    domain = parts[0]
                else:
                    domain = "default"
            else:
                domain = "unknown"
            
            domain_groups[domain].append(component)
        
        groups = []
        for domain, domain_components in domain_groups.items():
            group = ComponentGroup(
                id=f"group-domain-{domain}",
                name=f"{domain.title()} Domain",
                description=f"Components in the {domain} domain",
                component_ids=[c["id"] for c in domain_components],
                strategy=GroupingStrategy.DOMAIN,
                metadata={
                    "domain": domain,
                    "component_count": len(domain_components)
                }
            )
            groups.append(group)
        
        return groups
    
    def _group_by_functional_cohesion(
        self,
        components: List[Dict[str, Any]],
        graph: Dict[str, Any],
        repomap: Dict[str, Any]
    ) -> List[ComponentGroup]:
        """Group components by functional cohesion."""
        # Identify functional patterns based on naming and relationships
        functional_groups = defaultdict(list)
        
        # Common functional patterns
        patterns = {
            "controller": ["controller", "handler", "endpoint", "api"],
            "service": ["service", "business", "logic", "usecase"],
            "repository": ["repository", "dao", "storage", "persistence"],
            "model": ["model", "entity", "dto", "vo"],
            "utility": ["util", "helper", "common", "shared"],
            "config": ["config", "setting", "property", "constant"]
        }
        
        for component in components:
            name = component.get("name", "").lower()
            file_path = component.get("properties", {}).get("file", "").lower()
            
            # Find best matching pattern
            best_match = None
            best_score = 0
            
            for group_name, keywords in patterns.items():
                score = sum(1 for kw in keywords if kw in name or kw in file_path)
                if score > best_score:
                    best_score = score
                    best_match = group_name
            
            if best_match and best_score > 0:
                functional_groups[best_match].append(component)
            else:
                functional_groups["other"].append(component)
        
        groups = []
        for func_type, func_components in functional_groups.items():
            if not func_components:
                continue
                
            group = ComponentGroup(
                id=f"group-functional-{func_type}",
                name=f"{func_type.title()} Components",
                description=f"Components with {func_type} responsibilities",
                component_ids=[c["id"] for c in func_components],
                strategy=GroupingStrategy.FUNCTIONAL,
                metadata={
                    "function": func_type,
                    "component_count": len(func_components)
                }
            )
            groups.append(group)
        
        return groups
    
    def _group_by_data_flow(
        self,
        components: List[Dict[str, Any]],
        graph: Dict[str, Any],
        repomap: Dict[str, Any]
    ) -> List[ComponentGroup]:
        """Group components by data flow patterns."""
        # Build data flow graph
        data_flow = defaultdict(set)
        entity_to_component = {}
        
        # Map entities to components
        for component in components:
            entity_id = component.get("properties", {}).get("entityId")
            if entity_id:
                entity_to_component[entity_id] = component["id"]
        
        # Analyze relationships for data flow
        relationships = graph.get("relationships", [])
        for rel in relationships:
            if rel.get("type") in ["USES", "WRITES", "READS", "FLOWS"]:
                source = rel.get("source")
                target = rel.get("target")
                if source in entity_to_component and target in entity_to_component:
                    data_flow[entity_to_component[source]].add(entity_to_component[target])
        
        # Find connected components
        visited = set()
        groups = []
        
        for component in components:
            comp_id = component["id"]
            if comp_id in visited:
                continue
            
            # Find all connected components
            connected = self._find_connected_components(comp_id, data_flow, visited)
            
            if len(connected) > 1:  # Only group if there are connections
                group = ComponentGroup(
                    id=f"group-dataflow-{len(groups)}",
                    name=f"Data Flow Group {len(groups) + 1}",
                    description="Components connected by data flow",
                    component_ids=list(connected),
                    strategy=GroupingStrategy.DATA_FLOW,
                    metadata={
                        "flow_count": sum(len(data_flow[c]) for c in connected),
                        "component_count": len(connected)
                    }
                )
                groups.append(group)
        
        return groups
    
    def _find_connected_components(
        self,
        start: str,
        graph: Dict[str, Set[str]],
        visited: Set[str]
    ) -> Set[str]:
        """Find all components connected via data flow."""
        if start in visited:
            return set()
        
        visited.add(start)
        connected = {start}
        
        for neighbor in graph.get(start, set()):
            if neighbor not in visited:
                connected.update(self._find_connected_components(neighbor, graph, visited))
        
        return connected
    
    def _group_by_team_ownership(
        self,
        components: List[Dict[str, Any]],
        graph: Dict[str, Any],
        repomap: Dict[str, Any]
    ) -> List[ComponentGroup]:
        """Group components by team ownership."""
        # This is a simplified implementation
        # In a real scenario, this would analyze git history or CODEOWNERS files
        
        team_groups = defaultdict(list)
        
        for component in components:
            file_path = component.get("properties", {}).get("file", "")
            
            # Simple heuristic: infer team from directory structure
            if file_path:
                parts = Path(file_path).parts
                if len(parts) > 2:
                    # Look for team indicators in path
                    team_indicators = ["team", "squad", "guild", "chapter"]
                    team = "default"
                    
                    for part in parts:
                        if any(indicator in part.lower() for indicator in team_indicators):
                            team = part
                            break
                    
                    team_groups[team].append(component)
                else:
                    team_groups["default"].append(component)
            else:
                team_groups["unassigned"].append(component)
        
        groups = []
        for team, team_components in team_groups.items():
            group = ComponentGroup(
                id=f"group-team-{team}",
                name=f"{team.title()} Team",
                description=f"Components owned by {team} team",
                component_ids=[c["id"] for c in team_components],
                strategy=GroupingStrategy.TEAM,
                metadata={
                    "team": team,
                    "component_count": len(team_components)
                }
            )
            groups.append(group)
        
        return groups
    
    def _group_by_custom_rules(
        self,
        components: List[Dict[str, Any]],
        graph: Dict[str, Any],
        repomap: Dict[str, Any]
    ) -> List[ComponentGroup]:
        """Group components using custom rules."""
        groups = []
        
        for rule in self.custom_rules:
            rule_name = rule.get("name", "custom")
            rule_conditions = rule.get("conditions", [])
            
            matching_components = []
            
            for component in components:
                if self._matches_rule(component, rule_conditions):
                    matching_components.append(component)
            
            if matching_components:
                group = ComponentGroup(
                    id=f"group-custom-{rule_name}",
                    name=rule.get("display_name", rule_name.title()),
                    description=rule.get("description", f"Custom group: {rule_name}"),
                    component_ids=[c["id"] for c in matching_components],
                    strategy=GroupingStrategy.CUSTOM,
                    metadata={
                        "rule": rule_name,
                        "component_count": len(matching_components)
                    }
                )
                groups.append(group)
        
        return groups
    
    def _matches_rule(self, component: Dict[str, Any], conditions: List[Dict[str, Any]]) -> bool:
        """Check if component matches custom rule conditions."""
        for condition in conditions:
            field = condition.get("field")
            operator = condition.get("operator", "contains")
            value = condition.get("value", "")
            
            component_value = str(self._get_nested_value(component, field)).lower()
            
            if operator == "contains":
                if value.lower() not in component_value:
                    return False
            elif operator == "equals":
                if component_value != value.lower():
                    return False
            elif operator == "regex":
                import re
                if not re.search(value, component_value):
                    return False
        
        return True
    
    def _get_nested_value(self, obj: Dict[str, Any], path: str) -> Any:
        """Get nested value from dictionary using dot notation."""
        keys = path.split(".")
        current = obj
        
        for key in keys:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return None
        
        return current
    
    def _group_hybrid(
        self,
        components: List[Dict[str, Any]],
        graph: Dict[str, Any],
        repomap: Dict[str, Any],
        metrics: Optional[RepositoryMetrics] = None
    ) -> List[ComponentGroup]:
        """Group using multiple strategies based on repository characteristics."""
        all_groups = []
        
        # Always try domain grouping first
        domain_groups = self._group_by_domain(components, graph, repomap)
        all_groups.extend(domain_groups)
        
        # Add functional grouping for large domains
        if metrics and metrics.domain_count < 10:
            for group in domain_groups:
                if group.metadata["component_count"] > 20:
                    # Get components for this domain
                    domain_components = [
                        c for c in components 
                        if c["id"] in group.component_ids
                    ]
                    
                    # Apply functional grouping within domain
                    func_groups = self._group_by_functional_cohesion(domain_components, graph, repomap)
                    
                    # Update group IDs to avoid conflicts
                    for func_group in func_groups:
                        func_group.id = f"{group.id}-{func_group.id}"
                        func_group.name = f"{group.name} - {func_group.name}"
                        func_group.metadata["parent_group"] = group.id
                    
                    all_groups.extend(func_groups)
        
        return all_groups
