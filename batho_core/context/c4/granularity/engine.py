"""
Granularity decision engine for adaptive C4 model generation.
"""

from enum import Enum
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass

from batho_core.utils.logging import get_logger
from .analyzer import RepositoryMetrics

logger = get_logger(__name__, component="granularity_engine")


class GranularityLevel(Enum):
    """Granularity levels for C4 model generation."""
    FINE = "fine"       # Show all components
    MEDIUM = "medium"   # Group related components
    COARSE = "coarse"   # High-level containers only
    ADAPTIVE = "adaptive"  # Dynamic based on characteristics


@dataclass
class GranularityDecision:
    """Result of granularity decision process."""
    level: GranularityLevel
    reasoning: str
    confidence: float  # 0-1
    settings: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "level": self.level.value,
            "reasoning": self.reasoning,
            "confidence": self.confidence,
            "settings": self.settings
        }


class GranularityDecisionEngine:
    """Decides appropriate granularity based on repository metrics."""
    
    def __init__(self, enable_ml: bool = False):
        self.logger = get_logger(self.__class__.__name__, component="granularity_engine")
        self.enable_ml = enable_ml
        self.ml_model = None  # Placeholder for future ML model
        
        # Decision matrix weights
        self.weights = {
            "entity_count": 0.4,
            "complexity": 0.3,
            "coupling": 0.15,
            "domains": 0.15
        }
    
    def decide_granularity(
        self,
        metrics: RepositoryMetrics,
        override: Optional[GranularityLevel] = None
    ) -> GranularityDecision:
        """
        Decide granularity level based on repository metrics.
        
        Args:
            metrics: Repository analysis metrics
            override: Manual override of granularity level
            
        Returns:
            GranularityDecision with level and reasoning
        """
        if override:
            return GranularityDecision(
                level=override,
                reasoning=f"Manual override to {override.value}",
                confidence=1.0,
                settings=self._get_settings_for_level(override, metrics)
            )
        
        # Try ML prediction if available
        if self.enable_ml and self.ml_model:
            try:
                return self._predict_with_ml(metrics)
            except Exception as e:
                self.logger.warning("ML prediction failed, falling back to rules", error=str(e))
        
        # Use rule-based decision
        return self._decide_with_rules(metrics)
    
    def _decide_with_rules(self, metrics: RepositoryMetrics) -> GranularityDecision:
        """Make decision using rule-based approach."""
        # Primary decision based on entity count
        entity_count = metrics.entity_count
        
        # Adjust based on other factors
        complexity_factor = metrics.complexity_score
        coupling_factor = metrics.coupling_score
        domain_factor = min(1.0, metrics.domain_count / 10)  # Normalize domains
        
        # Calculate decision score
        decision_score = (
            entity_count * self.weights["entity_count"] +
            complexity_factor * 1000 * self.weights["complexity"] +
            coupling_factor * 500 * self.weights["coupling"] +
            domain_factor * 200 * self.weights["domains"]
        )
        
        # Determine level based on score
        if decision_score < 100:
            level = GranularityLevel.FINE
            reasoning = f"Small repository ({entity_count} entities) with low complexity"
            confidence = 0.9
        elif decision_score < 1000:
            level = GranularityLevel.MEDIUM
            reasoning = f"Medium repository ({entity_count} entities) requires grouping"
            confidence = 0.8
        elif decision_score < 5000:
            level = GranularityLevel.COARSE
            reasoning = f"Large repository ({entity_count} entities) needs high-level view"
            confidence = 0.85
        else:
            level = GranularityLevel.ADAPTIVE
            reasoning = f"Massive repository ({entity_count} entities) needs adaptive approach"
            confidence = 0.75
        
        # Adjust confidence based on complexity
        if complexity_factor > 0.8:
            confidence -= 0.1  # Less confident with very complex repos
        
        settings = self._get_settings_for_level(level, metrics)
        
        return GranularityDecision(
            level=level,
            reasoning=reasoning,
            confidence=max(0.5, confidence),
            settings=settings
        )
    
    def _predict_with_ml(self, metrics: RepositoryMetrics) -> GranularityDecision:
        """Predict granularity using ML model (placeholder)."""
        # TODO: Implement ML-based prediction
        # For now, fall back to rules
        self.logger.info("ML prediction not yet implemented, using rules")
        return self._decide_with_rules(metrics)
    
    def _get_settings_for_level(
        self,
        level: GranularityLevel,
        metrics: RepositoryMetrics
    ) -> Dict[str, Any]:
        """Get settings specific to granularity level."""
        base_settings = {
            "include_components": True,
            "include_relationships": True,
            "group_components": False,
            "filter_by_importance": False,
            "importance_threshold": 0.0
        }
        
        if level == GranularityLevel.FINE:
            return {
                **base_settings,
                "max_components": None,  # No limit
                "group_components": False,
                "filter_by_importance": False,
                "generate_detail_views": True
            }
        
        elif level == GranularityLevel.MEDIUM:
            return {
                **base_settings,
                "max_components": 500,
                "group_components": True,
                "grouping_strategy": "domain",
                "filter_by_importance": True,
                "importance_threshold": 0.3,
                "generate_detail_views": True
            }
        
        elif level == GranularityLevel.COARSE:
            return {
                **base_settings,
                "include_components": False,  # Containers only
                "max_containers": 50,
                "filter_by_importance": True,
                "importance_threshold": 0.5,
                "generate_detail_views": False
            }
        
        elif level == GranularityLevel.ADAPTIVE:
            # Adaptive settings based on metrics
            settings = base_settings.copy()
            
            if metrics.entity_count > 10000:
                settings.update({
                    "include_components": False,
                    "max_containers": 100
                })
            elif metrics.entity_count > 1000:
                settings.update({
                    "max_components": 1000,
                    "group_components": True,
                    "grouping_strategy": "hybrid",
                    "filter_by_importance": True,
                    "importance_threshold": 0.4
                })
            else:
                settings.update({
                    "max_components": None,
                    "group_components": True,
                    "grouping_strategy": "domain",
                    "filter_by_importance": True,
                    "importance_threshold": 0.2
                })
            
            return settings
        
        return base_settings
    
    def should_use_streaming(self, metrics: RepositoryMetrics) -> bool:
        """Determine if streaming should be used for processing."""
        return metrics.entity_count > 10000 or metrics.max_file_size > 100000
    
    def should_use_parallel(self, metrics: RepositoryMetrics) -> bool:
        """Determine if parallel processing should be used."""
        return metrics.entity_count > 1000 and metrics.complexity_score > 0.5
    
    def get_memory_estimate(self, metrics: RepositoryMetrics) -> int:
        """Estimate memory usage in MB."""
        base_memory = 50  # Base overhead
        entity_memory = metrics.entity_count * 0.1  # 0.1MB per entity
        relationship_memory = metrics.relationship_count * 0.05  # 0.05MB per relationship
        
        total = base_memory + entity_memory + relationship_memory
        
        # Add complexity overhead
        total *= (1 + metrics.complexity_score)
        
        return int(total)
    
    def validate_decision(self, decision: GranularityDecision) -> bool:
        """Validate that a decision is reasonable."""
        # Check confidence
        if decision.confidence < 0.5:
            self.logger.warning("Low confidence in granularity decision", confidence=decision.confidence)
        
        # Check settings consistency
        settings = decision.settings
        
        if decision.level == GranularityLevel.COARSE and settings.get("include_components"):
            self.logger.error("Inconsistent decision: coarse granularity with components")
            return False
        
        if decision.level == GranularityLevel.FINE and settings.get("group_components"):
            self.logger.warning("Unexpected: fine granularity with grouping enabled")
        
        return True
