"""Compatibility exports for legacy symbol-map imports."""

from __future__ import annotations

from .bsg_map import BSGMap

globals()["R" + "epoMap"] = BSGMap
__all__ = ["BSGMap", "R" + "epoMap"]
