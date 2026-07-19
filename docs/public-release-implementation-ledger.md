# Public Release Implementation Ledger

## Current slice: Release Bundle and offline container

Status: implemented; final artifact assembly, review, and release evidence are recorded by the
implementation branch history and CI.

- `baseball_rag.release_bundle` owns the exact 25-member payload, projection-only Retrosheet
  manifest, canonical Release Manifest bytes, Release Bundle digest, and fail-closed checker.
- `GROUNDBALL_RELEASE_BUNDLE` binds data, Published Query Catalog assets, the Coverage Report,
  and the compact Retrosheet projection to one checked bundle root.
- Release startup verifies the bundle, materializes the approved relations in an in-memory
  DuckDB, and requires the exact passing Coverage Report before serving.
- Public capability advertisement and execution expose only the three strikeout-side template
  families backed by the bundled projection.
- `Dockerfile.vercel` copies `release/bundle` verbatim and performs no data or catalog
  acquisition during build or runtime.

The manifest's `source_commit` is the reviewed implementation commit. The following
artifact-only commit adds the assembled bundle because a Git commit cannot contain a manifest
that names its own commit hash. CI requires that source commit to be the artifact commit's
immediate parent and requires the artifact commit's entire diff to remain under
`release/bundle/`. The container build must pass that same immediate-parent hash as
`GROUNDBALL_SOURCE_COMMIT`; the image checker and startup readiness seam reject any other value.

## Next slice: Public Admission Policy

Integrate one server-owned Public Admission Policy immediately before the existing Query Run
Adapter. Keep the policy behind its compare-and-swap store abstraction and implement the
approved Visitor, concurrency, rate, lease, refusal, and 100-start UTC-month rules. Use an
in-memory store for behavior proof only. Do not provision Vercel Blob, create secrets, deploy,
promote, change domains, activate paid services, or add a Mac, tunnel, LLM, or alternate-host
fallback without Stewart's explicit authorization.
