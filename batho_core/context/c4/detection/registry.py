"""
Registry for managing pattern detectors.
"""

from typing import Any, Dict, List, Optional, Type
from pathlib import Path

from batho_core.utils.logging import get_logger
from .base import PatternDetector, DetectionResult


class DetectorRegistry:
    """Registry for managing and executing pattern detectors."""
    
    def __init__(self):
        self.detectors: Dict[str, PatternDetector] = {}
        self.logger = get_logger(__name__, component="detector_registry")
    
    def register(self, detector: PatternDetector) -> None:
        """Register a detector."""
        self.detectors[detector.name] = detector
        self.logger.debug(f"Registered detector: {detector.name}")
    
    def unregister(self, name: str) -> None:
        """Unregister a detector."""
        if name in self.detectors:
            del self.detectors[name]
            self.logger.debug(f"Unregistered detector: {name}")
    
    def get_detector(self, name: str) -> Optional[PatternDetector]:
        """Get a detector by name."""
        return self.detectors.get(name)
    
    def list_detectors(self) -> List[str]:
        """List all registered detector names."""
        return list(self.detectors.keys())
    
    def detect_all(
        self,
        graph: Dict[str, Any],
        repomap: Dict[str, Any],
        rules: Optional[Dict[str, Any]] = None,
        detector_names: Optional[List[str]] = None
    ) -> Dict[str, List[DetectionResult]]:
        """
        Run all registered detectors (or specified ones).
        
        Args:
            graph: Code graph data.
            repomap: Repository map data.
            rules: Optional rule data.
            detector_names: Specific detectors to run (default: all).
            
        Returns:
            Dictionary mapping detector names to their results.
        """
        results = {}
        
        detectors_to_run = detector_names or list(self.detectors.keys())
        
        for name in detectors_to_run:
            if name not in self.detectors:
                self.logger.warning(f"Detector not found: {name}")
                continue
            
            detector = self.detectors[name]
            
            try:
                self.logger.debug(f"Running detector: {name}")
                detection_results = detector.detect(graph, repomap, rules)
                
                # Filter results by minimum confidence
                filtered_results = [
                    r for r in detection_results
                    if r.confidence >= detector.min_confidence
                ]
                
                results[name] = filtered_results
                self.logger.info(
                    f"Detector {name} completed",
                    results=len(filtered_results),
                    confidence_threshold=detector.min_confidence
                )
                
            except Exception as e:
                self.logger.error(
                    f"Detector {name} failed",
                    error=str(e),
                    exc_info=True
                )
                results[name] = []
        
        return results
    
    def get_summary(self, results: Dict[str, List[DetectionResult]]) -> Dict[str, Any]:
        """Get a summary of detection results."""
        summary = {
            "total_patterns": 0,
            "detectors_used": list(results.keys()),
            "patterns_by_type": {},
            "high_confidence_patterns": 0,
            "average_confidence": 0.0
        }
        
        all_confidences = []
        
        for detector_name, detection_results in results.items():
            summary["patterns_by_type"][detector_name] = len(detection_results)
            summary["total_patterns"] += len(detection_results)
            
            for result in detection_results:
                all_confidences.append(result.confidence)
                if result.confidence >= 0.8:
                    summary["high_confidence_patterns"] += 1
        
        if all_confidences:
            summary["average_confidence"] = sum(all_confidences) / len(all_confidences)
        
        return summary


# Global registry instance
_registry = DetectorRegistry()


def get_registry() -> DetectorRegistry:
    """Get the global detector registry."""
    return _registry


def register_detector(detector: PatternDetector) -> None:
    """Register a detector with the global registry."""
    _registry.register(detector)


def auto_register_detectors() -> None:
    """Auto-register all detector classes."""
    from .microservices import MicroserviceDetector
    from .event_driven import EventDrivenDetector
    from .cloud_native import CloudNativeDetector
    from .data_patterns import DataPatternDetector
    
    # Register all detectors
    register_detector(MicroserviceDetector())
    register_detector(EventDrivenDetector())
    register_detector(CloudNativeDetector())
    register_detector(DataPatternDetector())
