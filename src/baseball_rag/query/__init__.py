"""Published catalog-driven query interfaces."""

from baseball_rag.query.contracts import (
    Compare,
    ExecutionFailed,
    ExecutionUnavailable,
    NeedsClarification,
    NoData,
    QueryEvidence,
    QueryPlanV1,
    QueryRecipe,
    RankSpec,
    Ready,
    Rejected,
    Rows,
    SortSpec,
    SourceEvidence,
)
from baseball_rag.query.registry import (
    PublishedSourceView,
    RawField,
    discover_fields,
    published_sources,
)
from baseball_rag.query.service import execute, prepare

__all__ = [
    "Compare",
    "ExecutionFailed",
    "ExecutionUnavailable",
    "NeedsClarification",
    "NoData",
    "PublishedSourceView",
    "QueryEvidence",
    "QueryPlanV1",
    "QueryRecipe",
    "RankSpec",
    "RawField",
    "Ready",
    "Rejected",
    "Rows",
    "SortSpec",
    "SourceEvidence",
    "discover_fields",
    "execute",
    "prepare",
    "published_sources",
]
