"""Rendering-neutral architecture registry and tracing primitives."""

from baseball_rag.arch.components import (
    DiagramComponent,
    Layer,
    TestStatus,
    get_components_by_layer,
    get_registry,
    get_source_snippet,
)
from baseball_rag.arch.tracing import PipelineStage, PipelineTrace

__all__ = [
    "DiagramComponent",
    "Layer",
    "PipelineStage",
    "PipelineTrace",
    "TestStatus",
    "get_registry",
    "get_components_by_layer",
    "get_source_snippet",
]
