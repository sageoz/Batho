"""
C4 Enhanced Detection System.

This module provides architectural pattern detection capabilities
for microservices, event-driven architectures, cloud-native systems,
and data patterns.
"""

from .base import PatternDetector
from .registry import DetectorRegistry
from .microservices import MicroserviceDetector
from .event_driven import EventDrivenDetector
from .cloud_native import CloudNativeDetector
from .data_patterns import DataPatternDetector

__all__ = [
    "PatternDetector",
    "DetectorRegistry",
    "MicroserviceDetector",
    "EventDrivenDetector",
    "CloudNativeDetector",
    "DataPatternDetector",
]
