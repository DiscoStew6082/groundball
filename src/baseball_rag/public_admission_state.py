"""Strict schema-versioned codec for shared public admission state."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

from baseball_rag.public_admission import (
    MONTHLY_START_LIMIT,
    AdmissionState,
    CoordinationStateError,
    MonthlyBudget,
    RunLease,
)

SCHEMA_VERSION = 1
MAX_STATE_BYTES = 65_536
MAX_RUNNING_LEASES = 4
MAX_VISITORS = 256
MAX_STARTS_PER_VISITOR = 12
MAX_TOTAL_STARTS = 512
_VISITOR_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_PERIOD_PATTERN = re.compile(r"^(?:[1-9]\d{3})-(?:0[1-9]|1[0-2])$")
_TIMESTAMP_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class AdmissionStateCodecError(CoordinationStateError):
    """Provider state is unsafe to use for an admission decision."""


class _DuplicateJsonKeyError(ValueError):
    pass


def encode_admission_state(state: AdmissionState) -> bytes:
    """Encode schema v1 using canonical compact JSON and UTC timestamps."""
    document = {
        "schema_version": SCHEMA_VERSION,
        "monthly_budget": (
            None
            if state.monthly_budget is None
            else {
                "period": state.monthly_budget.period,
                "charged_starts": state.monthly_budget.charged_starts,
            }
        ),
        "running": [
            {
                "visitor": lease.visitor,
                "run_id": lease.run_id,
                "expires_at": _format_timestamp(lease.expires_at),
            }
            for lease in sorted(state.running, key=lambda item: (item.visitor, item.run_id))
        ],
        "starts_by_visitor": [
            {
                "visitor": visitor,
                "starts": [_format_timestamp(start) for start in sorted(starts)],
            }
            for visitor, starts in sorted(state.starts_by_visitor)
        ],
    }
    try:
        encoded = json.dumps(
            document,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError) as exc:
        raise AdmissionStateCodecError("Admission state is invalid.") from exc
    # Decode once so locally produced state obeys exactly the provider-read contract.
    decode_admission_state(encoded)
    return encoded


def decode_admission_state(payload: bytes) -> AdmissionState:
    """Decode only the bounded, exact schema-v1 state shape."""
    if not isinstance(payload, bytes) or len(payload) > MAX_STATE_BYTES:
        raise AdmissionStateCodecError("Admission state exceeds the size limit.")
    try:
        document = json.loads(payload, object_pairs_hook=_object_without_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError, _DuplicateJsonKeyError) as exc:
        raise AdmissionStateCodecError("Admission state is malformed.") from exc
    if not isinstance(document, dict) or set(document) != {
        "schema_version",
        "monthly_budget",
        "running",
        "starts_by_visitor",
    }:
        raise AdmissionStateCodecError("Admission state has an invalid shape.")
    if type(document["schema_version"]) is not int or document["schema_version"] != SCHEMA_VERSION:
        raise AdmissionStateCodecError("Admission state schema version is unsupported.")

    budget = _decode_budget(document["monthly_budget"])
    running = _decode_running(document["running"])
    starts_by_visitor = _decode_starts(document["starts_by_visitor"])
    if budget is not None:
        starts_in_budget_period = sum(
            1
            for _, starts in starts_by_visitor
            for start in starts
            if start.strftime("%Y-%m") == budget.period
        )
        if starts_in_budget_period > budget.charged_starts:
            raise AdmissionStateCodecError("Admission state is contradictory.")
    return AdmissionState(
        running=running,
        starts_by_visitor=starts_by_visitor,
        monthly_budget=budget,
    )


def _object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    document: dict[str, Any] = {}
    for key, value in pairs:
        if key in document:
            raise _DuplicateJsonKeyError
        document[key] = value
    return document


def _decode_budget(value: Any) -> MonthlyBudget | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {"period", "charged_starts"}:
        raise AdmissionStateCodecError("Monthly budget has an invalid shape.")
    period = value["period"]
    charged_starts = value["charged_starts"]
    if not isinstance(period, str) or _PERIOD_PATTERN.fullmatch(period) is None:
        raise AdmissionStateCodecError("Monthly budget period is invalid.")
    if type(charged_starts) is not int or not 0 <= charged_starts <= MONTHLY_START_LIMIT:
        raise AdmissionStateCodecError("Monthly budget count is invalid.")
    return MonthlyBudget(period=period, charged_starts=charged_starts)


def _decode_running(value: Any) -> tuple[RunLease, ...]:
    if not isinstance(value, list) or len(value) > MAX_RUNNING_LEASES:
        raise AdmissionStateCodecError("Running leases have invalid cardinality.")
    leases: list[RunLease] = []
    visitors: set[str] = set()
    run_ids: set[str] = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {"visitor", "run_id", "expires_at"}:
            raise AdmissionStateCodecError("Running lease has an invalid shape.")
        visitor = _decode_visitor(item["visitor"])
        run_id = item["run_id"]
        if not isinstance(run_id, str) or _RUN_ID_PATTERN.fullmatch(run_id) is None:
            raise AdmissionStateCodecError("Run identifier is invalid.")
        if visitor in visitors or run_id in run_ids:
            raise AdmissionStateCodecError("Running leases are contradictory.")
        visitors.add(visitor)
        run_ids.add(run_id)
        leases.append(
            RunLease(
                visitor=visitor,
                run_id=run_id,
                expires_at=_decode_timestamp(item["expires_at"]),
            )
        )
    return tuple(sorted(leases, key=lambda item: (item.visitor, item.run_id)))


def _decode_starts(value: Any) -> tuple[tuple[str, tuple[datetime, ...]], ...]:
    if not isinstance(value, list) or len(value) > MAX_VISITORS:
        raise AdmissionStateCodecError("Visitor histories have invalid cardinality.")
    histories: list[tuple[str, tuple[datetime, ...]]] = []
    visitors: set[str] = set()
    total_starts = 0
    for item in value:
        if not isinstance(item, dict) or set(item) != {"visitor", "starts"}:
            raise AdmissionStateCodecError("Visitor history has an invalid shape.")
        visitor = _decode_visitor(item["visitor"])
        starts_value = item["starts"]
        if (
            visitor in visitors
            or not isinstance(starts_value, list)
            or not 1 <= len(starts_value) <= MAX_STARTS_PER_VISITOR
        ):
            raise AdmissionStateCodecError("Visitor history is contradictory.")
        starts = tuple(_decode_timestamp(start) for start in starts_value)
        if tuple(sorted(starts)) != starts:
            raise AdmissionStateCodecError("Visitor history timestamps are not ordered.")
        visitors.add(visitor)
        total_starts += len(starts)
        if total_starts > MAX_TOTAL_STARTS:
            raise AdmissionStateCodecError("Visitor histories have invalid cardinality.")
        histories.append((visitor, starts))
    return tuple(sorted(histories))


def _decode_visitor(value: Any) -> str:
    if not isinstance(value, str) or _VISITOR_PATTERN.fullmatch(value) is None:
        raise AdmissionStateCodecError("Visitor digest is invalid.")
    return value


def _decode_timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or _TIMESTAMP_PATTERN.fullmatch(value) is None:
        raise AdmissionStateCodecError("UTC timestamp is invalid.")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise AdmissionStateCodecError("UTC timestamp is invalid.") from exc
    return parsed


def _format_timestamp(value: datetime) -> str:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise AdmissionStateCodecError("UTC timestamp is invalid.")
    utc_value = value.astimezone(UTC)
    if utc_value.microsecond:
        raise AdmissionStateCodecError("UTC timestamp precision is invalid.")
    return utc_value.strftime("%Y-%m-%dT%H:%M:%SZ")
