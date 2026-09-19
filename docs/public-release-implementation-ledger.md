# Public Release implementation ledger

This ledger records the current public repository contract. Concrete hosting implementation, account configuration, and external runtime evidence are intentionally outside the public tree.

## Delivered foundations

1. **Immutable Release Bundle** — deterministic Lahman, catalog, coverage, compact Retrosheet, provenance, and legal payload with exact source identity.
2. **Public Admission Policy** — fail-closed CAS admission, stable visitor digest, bounded rates, monthly allowance, concurrency limits, fifteen-second leases, and ten-second hard-stop execution.
3. **Portable public composition** — `PublicAppBindings` injects the deployment-shared store, digest material, initializer, and runner. Missing or unsafe bindings fail closed.
4. **Public result envelope** — bounded 25/50/100 pages, complete-or-refused export, and immutable completed-run state.
5. **Deterministic parity** — natural, structured, and bounded follow-up paths share one Query Recipe, Query Plan, result, and evidence contract.
6. **Release Artifact identity** — canonical `ground-ball-release-artifact-v2` binds source/artifact topology, Release Bundle, Public Admission Policy, Coverage Report, and public interface revision.
7. **Package parity** — the built Svelte application is byte-synchronized with `src/baseball_rag/web_dist/`.
8. **Dependency hygiene** — root and nested locks, warning policy, dependency audits, and pre-commit revisions are explicit CI contracts.
9. **Sourced assistant** — the same chat accepts bounded research answers with citations, complete source records, browser-local JSON export, and visible attribution. Public source owns interpretation prompts/schema and factual construction; optional transport and source I/O are injected.

## Assistant and dependency completion, 2026-09-18

The assistant is implemented, including typed statistics extraction, shared player resolution, bounded two- or three-step composition, reference-only follow-ups, and contracts for current batting leaders and probable pitchers. Wider catalog capabilities retain direct Query Recipes. Explicit research identities and scope checks preserve definition and World Series follow-ups. Model output selects operations; public code constructs facts from verified results and retained source records.

Implementation anchors are `74910a9`, `49aab9b`, `733d1cb`, `e0b169c`, `e034e0d`, `3a953f5`, and `3a6e548`. The dependency update is `aac74e3`; its direct-child artifact is `99a46c8`. Validation at that release included 699 fast Python tests, 80 nested-project tests, 37 UI tests and two packaging tests, all 26 query-matrix cases, generated-contract checks, lint/types, package parity and provider neutrality. These finite checks do not establish that every natural-language request is understood.

The public CI, Release Proof and Release Artifact Proof completed successfully for `99a46c8`. Runtime integration and operational evidence remain outside this repository. [Assistant scope](assistant.md) and [source attribution](source-attribution.md) define the supported behavior and required credits.

## Public neutrality closure

The public tree has one portable composition seam and no concrete hosting adapter, hosting configuration, external-runtime probe, release-environment record, credential requirement, or private package dependency. Default CORS origins are localhost and loopback only. Public source never imports private application packages.

`scripts/check_provider_neutrality.py` scans the tracked source plus explicitly supplied build artifacts. It rejects personal absolute paths, unknown hidden configuration, sensitive assignments, resource identifier assignments, non-approved URL hosts, malformed deny policy, and caller-supplied exact/glob deny rules. Findings and reports are canonical and redact matched content.

Ordinary CI invokes the scanner directly. Release Artifact Proof scans source and produced package, bundle, workflow, and proof artifacts. Private release verification may add an unchanged external deny policy without changing public scanner behavior.

## Release Artifact proof

The proof workflow must establish:

- the artifact commit's direct parent equals the Release Manifest source commit;
- the artifact commit changes only `release/bundle/**`;
- Release Bundle and Public Admission Policy identities are exact;
- catalog compatibility, raw inventory, Coverage Report, and deterministic eval parity pass;
- the web build equals the packaged fallback byte-for-byte;
- wheel, source distribution, Release Bundle, and uploaded proof material scan clean;
- the canonical Release Artifact record binds the actual source, artifact, policy, coverage, interface, and bundle digests.

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
- The dark responsive Svelte layout and existing query controls are preserved; assistant answers use their own evidence and JSON download controls in the same chat.
