# Ground Ball Context

This is the canonical current architecture and domain context. Historical implementation notes are not current interfaces.

## Product contract

- Ground Ball is a local-first historical MLB query engine.
- Every loaded primary Lahman field and row is discoverable and reachable through filtering, stable pagination, or export. The synthesized TeamReference source has the same guarantee.
- The Published Query Catalog is the only structured-query capability authority.
- A Query Recipe is the visible, editable request. Query Plan v1 is its closed, deterministic, serializable meaning and contains no user SQL or executable code.
- The compiler owns identifiers and emits parameterized DuckDB SQL. User values are bound data.
- QueryEvidence binds factual outcomes to the plan, catalog revision, data release, SQL, bound values, immutable result fingerprint, and source fingerprints.
- Factual adapter results are available only when the checked-in Coverage Report passes and matches the runtime exactly.
- Retrosheet event queries are separately governed. Biography generation and open explanation remain auxiliary.

## Public composition

`baseball_rag.public_app.create_app` is the public composition boundary. Local construction needs no bindings. Public construction accepts only injected `PublicAppBindings`: a deployment-shared CAS store, stable digest key, initializer, and hard-stop execution runner. Missing or unsafe bindings fail closed. The public repository contains no concrete hosting adapter or environment-driven hosting construction.

The direct-import `baseball_rag.api.server.app` remains available for local use and offline release proof. Its local-CI runtime configuration is network-disabled and cannot claim shared deployment authority.

## Release model

- `release/bundle/` is the immutable deterministic payload.
- `baseball_rag.release_bundle` assembles and verifies the bundle against an exact source commit.
- `baseball_rag.release_artifact` binds the source commit, artifact-only child commit, bundle, Public Admission Policy, Coverage Report, public interface revision, and offline container proof.
- Source changes are committed first. The next commit may change only `release/bundle/**`, and its direct parent must be the source commit.
- Public CI proves the same source-to-artifact topology without deployment or external runtime evidence.

## Current modules

- `src/baseball_rag/query/`: catalog-backed planning, compilation, execution, evidence, and coverage.
- `src/baseball_rag/public_admission.py`: opaque CAS state, admission, leases, rates, and monthly budget.
- `src/baseball_rag/public_app.py`: injected public application bindings and fail-closed initialization.
- `src/baseball_rag/public_execution.py`: isolated child-process execution with a ten-second hard stop.
- `src/baseball_rag/public_results.py`: bounded public pages and complete-or-refused exports.
- `src/baseball_rag/public_release_config.py`: Public Admission Policy and strict local release configuration.
- `src/baseball_rag/release_bundle.py`: deterministic Release Bundle assembly and verification.
- `src/baseball_rag/release_runtime.py`: offline startup and readiness checks.
- `src/baseball_rag/release_artifact.py`: canonical public Release Artifact identity.
- `src/baseball_rag/release_container_probe.py`: network-disabled packaged HTTP contract proof.

## Frozen seams

- Preserve the Query contracts and exact Coverage Report.
- Preserve one Svelte/FastAPI application for local and public composition.
- Preserve a ten-second execution deadline, lease accounting, fail-closed public mode, immutable runtime caching, and UID/GID 10001 in the generic release image.
- Do not add a second query interface, hidden retry, local machine fallback, or public hosting implementation.

## Baseline checks

```bash
uv run python -m baseball_rag.query.generate_catalog_compatibility --check
uv run python -m baseball_rag.query.generate_raw_inventory --check
uv run python -m baseball_rag.query.generate_coverage_report --check
uv run python -m baseball_rag.query.eval_matrix
uv run python scripts/check_provider_neutrality.py --root .
uv run pytest tests/ -m 'not release_proof' -q
npm --prefix web test
npm --prefix web run build
npm --prefix web run package:check
```
