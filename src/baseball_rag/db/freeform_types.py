"""Shared types and constants for freeform query handling."""

from dataclasses import dataclass, field

from baseball_rag.db.stat_registry import StatTable

MAX_ROWS = 1000
SCHEMA_TIMEOUT_MS = 5000


@dataclass
class FreeformResult:
    """Result of a freeform natural language query."""

    sql: str
    rows: list[tuple]
    columns: list[str]
    row_count: int
    truncated: bool
    params: list[object] = field(default_factory=list)
    source_label: str = "LLM-backed typed grounded database query"
    source_detail: str = (
        "LLM extracted a typed intent; Python assembled constrained SQL deterministically."
    )
    unsupported_reason: str | None = None


@dataclass(frozen=True)
class TeamIdentity:
    """Resolved historical team identity for a specific season."""

    nickname: str
    year: int
    team_id: str


@dataclass(frozen=True)
class QuerySpec:
    """Structured intent extracted from a natural language question."""

    stat_tables: list[StatTable] = field(default_factory=list)
    team_name_pattern: str | None = None
    year_value: int | None = None
    leader_stats: list[str] = field(default_factory=list)
    team_identity: TeamIdentity | None = None


QueryIntent = QuerySpec


@dataclass(frozen=True)
class AssembledSQL:
    sql: str
    params: list[object] = field(default_factory=list)
    unsupported_reason: str | None = None


@dataclass(frozen=True)
class PlannedFreeformQuery:
    """Executable grounded database query plan with provenance."""

    assembled: AssembledSQL
    planning_path: str
    source_label: str
    source_detail: str
    query_spec: QuerySpec | None = None

    @property
    def sql(self) -> str:
        return self.assembled.sql

    @property
    def params(self) -> list[object]:
        return self.assembled.params

    @property
    def unsupported_reason(self) -> str | None:
        return self.assembled.unsupported_reason
