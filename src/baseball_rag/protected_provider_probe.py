"""Guarded protected HTTP probe with injected transport, clocks, and sleep."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Mapping, Protocol
from urllib.parse import urlsplit

from baseball_rag.protected_provider_proof import (
    EVIDENCE_SCHEMAS,
    ProviderProofError,
    load_warm_manifest,
    validate_provider_evidence,
    validate_provider_identity,
)
from baseball_rag.public_release_config import canonical_json_bytes

_MAX_RESPONSE_BYTES = 4_000_000
_ALLOWED_PATHS = frozenset(
    {
        "/api/architecture",
        "/api/capabilities",
        "/api/generate",
        "/api/query",
        "/api/query-runs",
        "/api/release-readiness",
        "/api/retrosheet/queries",
    }
)
_FORBIDDEN_PUBLIC_ROUTES = ("/api/architecture", "/api/generate", "/api/query")


class ProtectedProbeError(ValueError):
    """A guarded live probe input or response is unsafe or invalid."""


@dataclass(frozen=True)
class ProbeResponse:
    status_code: int
    body: bytes


class ProtectedHttpTransport(Protocol):
    def request(
        self,
        *,
        origin: str,
        path: str,
        method: str,
        payload: bytes | None,
        headers: dict[str, str],
        timeout: float,
        workload_case: str,
    ) -> ProbeResponse: ...


class UrllibProtectedHttpTransport:
    """Bounded, no-redirect transport restricted to one validated origin."""

    def request(
        self,
        *,
        origin: str,
        path: str,
        method: str,
        payload: bytes | None,
        headers: dict[str, str],
        timeout: float,
        workload_case: str,
    ) -> ProbeResponse:
        del workload_case
        if not _https_origin(origin) or path not in _ALLOWED_PATHS:
            raise ProtectedProbeError("Protected HTTP destination is not approved.")
        request = urllib.request.Request(
            origin + path,
            data=payload,
            headers=headers,
            method=method,
        )
        opener = urllib.request.build_opener(_NoRedirect)
        try:
            response = opener.open(request, timeout=timeout)
        except urllib.error.HTTPError as exc:
            response = exc
        except (OSError, urllib.error.URLError) as exc:
            raise ProtectedProbeError("Protected HTTP request failed.") from exc
        with response:
            body = response.read(_MAX_RESPONSE_BYTES + 1)
            if len(body) > _MAX_RESPONSE_BYTES:
                raise ProtectedProbeError("Protected HTTP response exceeds the proof bound.")
            return ProbeResponse(status_code=int(response.status), body=body)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        del req, fp, code, msg, headers, newurl
        return None


def run_protected_http_probe(
    identity: Mapping[str, object],
    origin: str,
    idle_period_seconds: int,
    *,
    transport: ProtectedHttpTransport,
    monotonic: Callable[[], float],
    sleep: Callable[[float], None],
    bypass_secret: str | None = None,
    utc_now: Callable[[], datetime] | None = None,
) -> dict[str, object]:
    """Run the exact corpus once; no request is retried or substituted."""
    validate_provider_identity(identity)
    if not _https_origin(origin):
        raise ProtectedProbeError("Protected preview must be one exact HTTPS origin.")
    if type(idle_period_seconds) is not int or idle_period_seconds < 30:
        raise ProtectedProbeError(
            "Each cold sample requires a documented idle period of at least 30 seconds."
        )
    if bypass_secret is not None and (
        not isinstance(bypass_secret, str)
        or not bypass_secret
        or any(character.isspace() for character in bypass_secret)
    ):
        raise ProtectedProbeError("Automation bypass configuration is invalid.")
    now = utc_now or (lambda: datetime.now(UTC))
    observed_at = _utc_text(now())
    headers = {} if bypass_secret is None else {"x-vercel-protection-bypass": bypass_secret}

    readiness = _json_request(
        transport, origin, "/api/release-readiness", "GET", None, headers, "release_readiness"
    )
    _validate_readiness(readiness, identity)
    capabilities = _json_request(
        transport, origin, "/api/capabilities", "GET", None, headers, "public_capabilities"
    )
    _validate_capabilities(capabilities)
    initial_tommy = _request_case(transport, origin, "tommy_davis_natural", headers, None)
    if not initial_tommy["passed"]:
        raise ProtectedProbeError("Named protected HTTP corpus preflight failed.")

    cold_samples: list[dict[str, object]] = []
    for index in range(1, 6):
        sleep(float(idle_period_seconds))
        shell_started = monotonic()
        cold_readiness = _json_request(
            transport,
            origin,
            "/api/release-readiness",
            "GET",
            None,
            headers,
            f"cold_{index}_readiness",
        )
        _validate_readiness(cold_readiness, identity)
        cold_capabilities = _json_request(
            transport,
            origin,
            "/api/capabilities",
            "GET",
            None,
            headers,
            f"cold_{index}_capabilities",
        )
        _validate_capabilities(cold_capabilities)
        shell_elapsed = _elapsed_ms(shell_started, monotonic())
        query_started = monotonic()
        query = _request_case(transport, origin, "tommy_davis_natural", headers, None)
        query_elapsed = _elapsed_ms(query_started, monotonic())
        instance_id = _runtime_instance_id(cold_readiness)
        passed = shell_elapsed <= 5000 and query_elapsed <= 10000 and query["passed"] is True
        cold_samples.append(
            {
                "first_query_elapsed_ms": query_elapsed,
                "full_body": query["full_body"],
                "runtime_instance_id": instance_id,
                "sample_id": f"cold-{index:02d}",
                "shell_capabilities_elapsed_ms": shell_elapsed,
                "status": "pass" if passed else "fail",
            }
        )

    manifest = load_warm_manifest()
    warm_results: list[dict[str, object]] = []
    previous_recipe: dict[str, object] | None = None
    manifest_workloads = manifest.get("workloads")
    assert isinstance(manifest_workloads, list)
    for workload in manifest_workloads:
        assert isinstance(workload, dict)
        case = str(workload["corpus_case_id"])
        started = monotonic()
        measured = _request_case(transport, origin, case, headers, previous_recipe)
        elapsed = _elapsed_ms(started, monotonic())
        measured_document = measured.get("document")
        if case == "ohtani_first_turn" and isinstance(measured_document, dict):
            recipe = measured_document.get("recipe")
            if isinstance(recipe, dict):
                previous_recipe = recipe
        passed = measured["passed"] is True and elapsed <= 3000
        warm_results.append(
            {
                "elapsed_ms": elapsed,
                "fingerprint": measured["fingerprint"],
                "full_body": measured["full_body"],
                "http_status": measured["http_status"],
                "outcome": "pass" if passed else "fail",
                "workload_id": workload["workload_id"],
            }
        )

    common = {"identity": dict(identity), "observed_at": observed_at}
    cold = {
        **common,
        "observation": {
            "idle_period_seconds": idle_period_seconds,
            "samples": cold_samples,
        },
        "schema_version": EVIDENCE_SCHEMAS["cold_wakes"],
        "status": "pass" if all(item["status"] == "pass" for item in cold_samples) else "fail",
    }
    warm = {
        **common,
        "observation": {
            "manifest_digest": hashlib.sha256(canonical_json_bytes(manifest)).hexdigest(),
            "results": warm_results,
        },
        "schema_version": EVIDENCE_SCHEMAS["warm_results"],
        "status": "pass" if all(item["outcome"] == "pass" for item in warm_results) else "fail",
    }
    validate_provider_evidence(cold)
    validate_provider_evidence(warm)
    return {"cold_wakes": cold, "warm_results": warm}


def build_lifecycle_evidence(
    identity: Mapping[str, object],
    *,
    replacement_deployment_id: str,
    runtime_instance_transitions: list[str],
    restart_observed: bool,
    scale_to_zero_provider_reported: bool,
    state_persisted: bool,
    observed_at: datetime,
) -> dict[str, object]:
    """Bind externally observed lifecycle facts without claiming sleep is scale-to-zero."""
    document: dict[str, object] = {
        "identity": dict(identity),
        "observation": {
            "initial_deployment_id": identity.get("deployment_id"),
            "replacement_deployment_id": replacement_deployment_id,
            "restart_observed": restart_observed,
            "runtime_instance_transitions": runtime_instance_transitions,
            "scale_to_zero_provider_reported": scale_to_zero_provider_reported,
            "state_persisted": state_persisted,
        },
        "observed_at": _utc_text(observed_at),
        "schema_version": EVIDENCE_SCHEMAS["lifecycle"],
        "status": (
            "pass"
            if restart_observed and scale_to_zero_provider_reported and state_persisted
            else "fail"
        ),
    }
    validate_provider_evidence(document)
    return document


def run_security_route_probe(
    identity: Mapping[str, object],
    origin: str,
    *,
    transport: ProtectedHttpTransport,
    provider_coordination_destinations: list[str],
    egress_provider_reported: bool,
    bypass_secret: str | None = None,
    utc_now: Callable[[], datetime] | None = None,
) -> dict[str, object]:
    """Probe only the fixed public route inventory; egress remains provider-sourced."""
    validate_provider_identity(identity)
    if not _https_origin(origin):
        raise ProtectedProbeError("Security proof requires one exact HTTPS origin.")
    if type(egress_provider_reported) is not bool:
        raise ProtectedProbeError("Security proof egress source is invalid.")
    headers = {} if bypass_secret is None else {"x-vercel-protection-bypass": bypass_secret}
    capabilities = _json_request(
        transport,
        origin,
        "/api/capabilities",
        "GET",
        None,
        headers,
        "security_public_capabilities",
    )
    _validate_capabilities(capabilities)
    oversized_malformed = b"{" + b"x" * 16_385
    statuses: dict[str, int] = {}
    secret_exposure = False
    for route in _FORBIDDEN_PUBLIC_ROUTES:
        response = transport.request(
            origin=origin,
            path=route,
            method="POST",
            payload=oversized_malformed,
            headers={**headers, "Content-Type": "application/json"},
            timeout=15.0,
            workload_case=f"forbidden_{route.rsplit('/', 1)[1]}",
        )
        statuses[route] = response.status_code
        lowered = response.body.lower()
        secret_exposure = secret_exposure or any(
            marker in lowered
            for marker in (b"bearer ", b"-----begin ", b"/app/", b"/users/", b"cookie=")
        )
    routes_pass = all(status in {404, 405} for status in statuses.values())
    now = utc_now or (lambda: datetime.now(UTC))
    document: dict[str, object] = {
        "identity": dict(identity),
        "observation": {
            "browser_network_destinations": [origin],
            "egress_provider_reported": egress_provider_reported,
            "forbidden_routes_before_body": statuses,
            "provider_coordination_destinations": provider_coordination_destinations,
            "public_route_inventory_valid": routes_pass,
            "secret_exposure_detected": secret_exposure,
            "unexpected_egress_destinations": [],
        },
        "observed_at": _utc_text(now()),
        "schema_version": EVIDENCE_SCHEMAS["network_security"],
        "status": (
            "pass" if routes_pass and egress_provider_reported and not secret_exposure else "fail"
        ),
    }
    validate_provider_evidence(document)
    return document


def _request_case(
    transport: ProtectedHttpTransport,
    origin: str,
    case: str,
    headers: dict[str, str],
    previous_recipe: dict[str, object] | None,
) -> dict[str, object]:
    manifest = load_warm_manifest()
    manifest_workloads = manifest.get("workloads")
    assert isinstance(manifest_workloads, list)
    workload = next(
        (
            item
            for item in manifest_workloads
            if isinstance(item, dict) and item.get("corpus_case_id") == case
        ),
        None,
    )
    if not isinstance(workload, dict):
        if case != "tommy_davis_natural":
            raise ProtectedProbeError("Protected HTTP workload is not in the immutable manifest.")
        workload = {
            "corpus_case_id": case,
            "expected_http_status": 200,
            "expected_outcome": "rows",
            "method": "POST",
            "path": "/api/query-runs",
        }
    payload = _case_payload(case, previous_recipe)
    response = transport.request(
        origin=origin,
        path=str(workload["path"]),
        method=str(workload["method"]),
        payload=payload,
        headers={
            **headers,
            **({"Content-Type": "application/json"} if payload is not None else {}),
        },
        timeout=15.0,
        workload_case=case,
    )
    full_body = False
    document: object = None
    try:
        document = json.loads(response.body.decode("utf-8"))
        full_body = isinstance(document, dict)
    except (UnicodeError, json.JSONDecodeError):
        pass
    passed = (
        full_body
        and response.status_code == workload["expected_http_status"]
        and _case_result_matches(case, str(workload["expected_outcome"]), document)
    )
    return {
        "document": document,
        "fingerprint": hashlib.sha256(response.body).hexdigest(),
        "full_body": full_body,
        "http_status": response.status_code,
        "passed": passed,
    }


def _case_payload(case: str, previous_recipe: dict[str, object] | None) -> bytes | None:
    questions = {
        "tommy_davis_natural": "who had the most RBIs in 1962",
        "ohtani_natural": (
            "how many home runs did ohtani hit in the year he had the most wins as a pitcher"
        ),
        "ohtani_first_turn": "how many RBIs did Shohei Ohtani have in 2022",
        "retrosheet_count": "how many times did Nolan Ryan strike out the side in his career",
        "retrosheet_game_log": "when did Nolan Ryan strike out the side in 1973",
        "retrosheet_leaders": (
            "which pitchers have the most strike out the side games in their careers"
        ),
        "retrosheet_unbundled_refusal": "what is the longest stolen base streak in MLB history",
    }
    if case == "public_capabilities":
        return None
    if case == "ohtani_follow_up":
        return canonical_json_bytes(
            {
                "previous_recipe": previous_recipe or {},
                "question": "what about his home runs in 2022?",
            }
        )
    if case == "ohtani_structured":
        return canonical_json_bytes({"recipe": _ohtani_recipe()})
    if case.startswith("page_"):
        size = int(case.rsplit("_", 1)[1])
        recipe = _ohtani_recipe()
        recipe["output"] = {"kind": "interactive_page", "offset": 0, "size": size}
        return canonical_json_bytes({"recipe": recipe})
    if case in {"complete_json_export", "complete_csv_export"}:
        recipe = _ohtani_recipe()
        recipe["output"] = {"format": case.split("_")[1], "kind": "export"}
        return canonical_json_bytes({"recipe": recipe})
    if case == "question_limit":
        return canonical_json_bytes({"question": "x" * 501})
    if case == "body_limit":
        return b'{"question":"' + b"x" * 16_385 + b'"}'
    if case == "malformed_json":
        return b'{"question":'
    if case == "sql_like_bound_value":
        return canonical_json_bytes(
            {"question": "show players named Robert'); DROP TABLE People; --"}
        )
    if case == "nonfinite_refusal":
        return b'{"recipe":{"output":{"offset":NaN}}}'
    question = questions.get(case, questions.get("tommy_davis_natural"))
    return canonical_json_bytes({"question": question})


def _ohtani_recipe() -> dict[str, object]:
    return {
        "grain": "player-season",
        "output": {"kind": "interactive_page", "offset": 0, "size": 25},
        "predicate": {
            "kind": "compare",
            "literal": "Shohei Ohtani",
            "operator": "equals",
            "value": "player.name",
        },
        "ranking": {
            "count": 1,
            "direction": "highest",
            "tie_policy": "include_ties",
            "value": "pitching.W",
            "within": [],
        },
        "selections": ["player.name", "season", "batting.HR", "pitching.W"],
        "source": "Batting",
    }


def _case_result_matches(case: str, expected: str, document: object) -> bool:
    if not isinstance(document, dict):
        return False
    if case == "public_capabilities":
        try:
            _validate_capabilities(document)
        except ProtectedProbeError:
            return False
        return True
    if case == "tommy_davis_natural":
        return document.get("rows") == [
            {"batting.RBI": 153, "player.name": "Tommy Davis", "season": 1962}
        ]
    if case in {"ohtani_natural", "ohtani_structured"}:
        return document.get("rows") == [
            {"batting.HR": 34, "pitching.W": 15, "player.name": "Shohei Ohtani", "season": 2022}
        ]
    if case == "ohtani_follow_up":
        rows = document.get("rows")
        return isinstance(rows, list) and bool(rows) and rows[0].get("batting.HR") == 34
    if case.startswith("retrosheet_") and case != "retrosheet_unbundled_refusal":
        return document.get("kind") == "rows" and bool(document.get("rows"))
    if expected in {"rejected", "unsupported"}:
        return "rows" not in document and document.get("kind") not in {"rows", "exported"}
    return document.get("kind") == expected or (expected == "rows" and bool(document.get("rows")))


def _json_request(
    transport: ProtectedHttpTransport,
    origin: str,
    path: str,
    method: str,
    payload: bytes | None,
    headers: dict[str, str],
    workload_case: str,
) -> dict[str, object]:
    response = transport.request(
        origin=origin,
        path=path,
        method=method,
        payload=payload,
        headers=headers,
        timeout=15.0,
        workload_case=workload_case,
    )
    if response.status_code != 200:
        raise ProtectedProbeError("Protected identity request failed.")
    try:
        document = json.loads(response.body.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ProtectedProbeError("Protected identity response is malformed.") from exc
    if not isinstance(document, dict):
        raise ProtectedProbeError("Protected identity response is malformed.")
    return document


def _validate_readiness(document: Mapping[str, object], identity: Mapping[str, object]) -> None:
    runtime = document.get("runtime_configuration")
    if (
        document.get("source_commit") != identity.get("source_commit")
        or document.get("release_bundle_digest") != identity.get("bundle_digest")
        or not isinstance(runtime, dict)
        or runtime.get("digest") != identity.get("runtime_configuration_digest")
        or runtime.get("provider_deployment") is not True
        or runtime.get("scope") not in {"protected_preview", "production"}
    ):
        raise ProtectedProbeError("Protected readiness identity is foreign or incomplete.")
    _runtime_instance_id(document)


def _runtime_instance_id(document: Mapping[str, object]) -> str:
    hosting = document.get("hosting")
    value = hosting.get("runtime_instance_id") if isinstance(hosting, dict) else None
    if (
        not isinstance(value, str)
        or len(value) != 32
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ProtectedProbeError("Protected readiness lacks a safe runtime instance marker.")
    return value


def _validate_capabilities(document: Mapping[str, object]) -> None:
    capabilities = document.get("retrosheet_capabilities")
    if (
        document.get("mode") != "public"
        or not isinstance(capabilities, list)
        or [item.get("capability_id") for item in capabilities if isinstance(item, dict)]
        != ["pitcher_strikeout_side"]
    ):
        raise ProtectedProbeError("Protected public capabilities are invalid.")


def _elapsed_ms(started: float, finished: float) -> int:
    elapsed = finished - started
    if not isinstance(elapsed, float) or elapsed < 0:
        raise ProtectedProbeError("Monotonic probe clock moved backwards.")
    return round(elapsed * 1000)


def _utc_text(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ProtectedProbeError("UTC observation clock is invalid.")
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _https_origin(value: object) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlsplit(value)
    return (
        parsed.scheme == "https"
        and bool(parsed.hostname)
        and parsed.username is None
        and parsed.password is None
        and parsed.port in {None, 443}
        and parsed.path == ""
        and not parsed.query
        and not parsed.fragment
        and value == f"https://{parsed.hostname}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--origin", required=True)
    parser.add_argument("--idle-period-seconds", type=int, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--artifact-commit", required=True)
    parser.add_argument("--bundle-digest", required=True)
    parser.add_argument("--runtime-configuration-digest", required=True)
    parser.add_argument("--admission-policy-digest", required=True)
    parser.add_argument("--deployment-id", required=True)
    parser.add_argument("--provider-image-digest", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    if not args.live:
        parser.error("Provider contact requires the explicit --live guard.")
    identity = {
        "admission_policy_digest": args.admission_policy_digest,
        "artifact_commit": args.artifact_commit,
        "bundle_digest": args.bundle_digest,
        "deployment_id": args.deployment_id,
        "provider_image_digest": args.provider_image_digest,
        "runtime_configuration_digest": args.runtime_configuration_digest,
        "source_commit": args.source_commit,
    }
    try:
        result = run_protected_http_probe(
            identity,
            args.origin,
            args.idle_period_seconds,
            transport=UrllibProtectedHttpTransport(),
            monotonic=time.monotonic,
            sleep=time.sleep,
            bypass_secret=os.environ.get("VERCEL_AUTOMATION_BYPASS_SECRET"),
        )
    except (ProtectedProbeError, ProviderProofError) as exc:
        parser.error(str(exc))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, document in result.items():
        (args.output_dir / f"{name}.json").write_bytes(canonical_json_bytes(document))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
