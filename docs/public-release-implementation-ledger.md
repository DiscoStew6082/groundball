# Public Release implementation ledger

This ledger records the current public repository contract. Concrete hosting implementation, account configuration, and external runtime evidence are intentionally outside the public tree.

## Delivered foundations

1. **Immutable Release Bundle** — deterministic Lahman, catalog, coverage, compact Retrosheet, provenance, and legal payload with exact source identity.
2. **Public Admission Policy** — fail-closed CAS admission, stable visitor digest, bounded rates, monthly allowance, concurrency limits, fifteen-second leases, and ten-second hard-stop execution.
3. **Portable public composition** — `PublicAppBindings` injects the deployment-shared store, digest material, initializer, and runner. Missing or unsafe bindings fail closed.
4. **Public result envelope** — bounded 25/50/100 pages, complete-or-refused export, and immutable completed-run state.
5. **Deterministic parity** — natural, structured, and bounded follow-up paths share one Query Recipe, Query Plan, result, and evidence contract.
6. **Release Artifact identity** — canonical `ground-ball-release-artifact-v1` binds source/artifact topology, Release Bundle, Public Admission Policy, Coverage Report, public interface revision, and offline container proof.
7. **Package parity** — the built Svelte application is byte-synchronized with `src/baseball_rag/web_dist/`.
8. **Dependency hygiene** — root and nested locks, warning policy, dependency audits, and pre-commit revisions are explicit CI contracts.

## Public neutrality closure

The public tree has one portable composition seam and no concrete hosting adapter, hosting configuration, external-runtime probe, release-environment record, credential requirement, or private package dependency. Default CORS origins are localhost and loopback only. Public source never imports private application packages.

`scripts/check_provider_neutrality.py` scans the tracked source plus explicitly supplied build artifacts. It rejects personal absolute paths, unknown hidden configuration, sensitive assignments, resource identifier assignments, non-approved URL hosts, malformed deny policy, and caller-supplied exact/glob deny rules. Findings and reports are canonical and redact matched content.

Ordinary CI invokes the scanner directly. Release Artifact Proof scans source and produced package, bundle, workflow, and generic container-context artifacts. Private release verification may add an unchanged external deny policy without changing public scanner behavior.

## Release Artifact proof

The proof workflow must establish:

- the artifact commit's direct parent equals the Release Manifest source commit;
- the artifact commit changes only `release/bundle/**`;
- Release Bundle and Public Admission Policy identities are exact;
- catalog compatibility, raw inventory, Coverage Report, and deterministic eval parity pass;
- the web build equals the packaged fallback byte-for-byte;
- wheel, source distribution, Release Bundle, uploaded proof material, and generic container context scan clean;
- a generic local container starts with networking disabled and passes `release_container_probe`;
- the canonical Release Artifact record binds the actual source, artifact, policy, coverage, interface, bundle, and offline proof digests.

The workflow contains no deployment command, external runtime checkout, protected environment, provider observation, or secret requirement.

## Source and artifact regeneration

The source-artifact commit contains generated catalog compatibility, raw inventory, Coverage Report JSON/Markdown, packaged web assets, and any required lock updates. Temporary primary CSV copies are removed before commit.

The direct child artifact commit contains only a deterministic reassembly of `release/bundle/**` from the exact source commit. See [release-artifacts.md](release-artifacts.md) for the command contract.

## Preserved invariants

- Published Query Catalog remains the sole structured-query authority.
- Query Recipe, Query Plan v1, Query Run, QueryEvidence, and Coverage Report remain unchanged.
- Local direct-import ASGI behavior remains available.
- Public mode fails closed without safe bindings.
- Execution deadline remains ten seconds and leases remain fifteen seconds.
- Runtime installation remains one-shot and immutable within a process.
- The generic release image runs as UID/GID 10001.
- The accepted dark responsive Svelte UI and public result controls remain unchanged.
