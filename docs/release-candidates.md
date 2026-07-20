# Release candidate operations

Ground Ball release candidates are identified by artifacts, never by a branch label. The pure tooling in `baseball_rag.release_candidate` does not inspect Git, Docker, GitHub, a provider, or credentials. Callers discover exact values and pass them in.

## Artifact meanings

- **Release Manifest digest**: SHA-256 of the canonical provider-neutral `release/bundle/release-manifest.json`. The manifest never contains an image digest.
- **Candidate identity**: binds one scope, 40-hex source commit, distinct 40-hex bundle artifact commit, manifest digest, image digest and measured size, runtime and Public Admission Policy digests, and path-free evidence identities. `MAX_CANDIDATE_IMAGE_SIZE_BYTES` authoritatively limits every scope to 1,073,741,824 bytes (exactly 1 GiB). Its `candidate_id` hashes the canonical document without the `candidate_id` field.
- **Gate report**: contains the fixed Release Gate inventory. Status is exactly `pass`, `fail`, or `blocked`; a pass must reference candidate evidence. Eligibility requires every gate to pass for the same candidate.
- **Deployment Attestation**: remains outside the Release Bundle. Wave 6 emits only a local template stating that no provider deployment exists. The actual Ground Ball Hobby report is blocked because provider-measured peak memory requires Observability Plus, which Hobby cannot enable; `provider_metric_unavailable_on_hobby` is not substitutable evidence and that report cannot emit an attestation. The reusable strict builder and validator still require and accept an exact eligible all-pass report with complete genuine provider observations. A Vercel deployment identity is exactly `dpl_` plus the provider's current 28-character case-sensitive base62 suffix; tooling preserves and compares those bytes without lowercasing, aliasing, truncation, or substitution.
- **Local Docker image identity**: `docker image inspect .Id` is a local content-addressed image ID. `docker image inspect .Size` is a local preliminary byte measurement. Neither is a provider OCI digest/size.

The canonical generated Public Admission Policy is `release/config/public-admission-policy.json`. It is derived from constants the server, coordinator, state codec, and Blob configuration enforce. `release/config/local-ci-runtime.json` is explicitly non-provider, network-disabled, and ephemeral; it cannot represent protected-preview or production proof.

## Freeze and topology

The candidate uses the existing non-circular two-commit model:

1. Commit source, tests, workflows, documentation, and generated non-bundle configuration.
2. Use that exact source commit as `release-manifest.json.source_commit`.
3. Reassemble `release/bundle` deterministically.
4. Commit only `release/bundle/**`; this artifact commit must have the source commit as its direct parent.
5. Keep the PR head at the artifact commit. Any source correction requires a new source commit and another bundle assembly.

The candidate workflow checks full history, the manifest source, the artifact parent, and every changed path. It does not trust a branch name. Automatic PR proof is triggered only when the canonical `release/bundle/release-manifest.json` changes, so ordinary source, dependency, configuration, workflow, and test PRs remain the responsibility of ordinary CI. `workflow_dispatch` remains available for an operator-selected candidate ref.

## Reproducible local assembly

From the repository root, after the source commit exists:

```bash
SOURCE_COMMIT="$(git rev-parse HEAD)"
rm -rf release/bundle.next
uv run python -m baseball_rag.public_release_config --check
uv run python -m baseball_rag.release_bundle assemble . release/bundle.next \
  --source-commit "$SOURCE_COMMIT"
uv run python -m baseball_rag.release_bundle check release/bundle.next \
  --expected-source-commit "$SOURCE_COMMIT"
rm -rf release/bundle
mv release/bundle.next release/bundle
git add release/bundle
git commit -m "Assemble Wave 6 release bundle"
```

After that artifact-only commit, Docker values feed the pure candidate tooling:

```bash
ARTIFACT_COMMIT="$(git rev-parse HEAD)"
ARTIFACT_PARENT_COMMIT="$(git rev-parse HEAD^)"
git diff --name-only "$SOURCE_COMMIT" "$ARTIFACT_COMMIT" > candidate-artifacts/artifact-changed-paths.txt

docker build -f Dockerfile.vercel \
  -t "groundball-candidate:$ARTIFACT_COMMIT" .
IMAGE_DIGEST="$(docker image inspect "groundball-candidate:$ARTIFACT_COMMIT" --format '{{.Id}}')"
IMAGE_SIZE_BYTES="$(docker image inspect "groundball-candidate:$ARTIFACT_COMMIT" --format '{{.Size}}')"
test "$IMAGE_SIZE_BYTES" -le 1073741824

uv run python -m baseball_rag.release_candidate assemble \
  --scope local_ci \
  --source-commit "$SOURCE_COMMIT" \
  --artifact-commit "$ARTIFACT_COMMIT" \
  --artifact-parent-commit "$ARTIFACT_PARENT_COMMIT" \
  --artifact-changed-paths candidate-artifacts/artifact-changed-paths.txt \
  --bundle-root release/bundle \
  --image-digest "$IMAGE_DIGEST" \
  --image-size-bytes "$IMAGE_SIZE_BYTES" \
  --image-size-measurement-kind docker-image-inspect-size-bytes \
  --runtime-config release/config/local-ci-runtime.json \
  --admission-policy release/config/public-admission-policy.json \
  --evidence-spec candidate-artifacts/evidence-spec.json \
  --gate-results candidate-artifacts/gate-results.json \
  --output candidate-artifacts/candidate-identity.json \
  --gate-report-output candidate-artifacts/gate-report.json \
  --attestation-output candidate-artifacts/deployment-attestation-template.json

# Aggregate assembly validates all three records before writing any of them.
uv run python -m baseball_rag.release_candidate validate attestation \
  --candidate candidate-artifacts/candidate-identity.json \
  --gate-report candidate-artifacts/gate-report.json \
  --attestation candidate-artifacts/deployment-attestation-template.json
```

`evidence-spec.json` is a canonical local input whose entries contain `logical_id`, `path`, `media_type`, and `schema_identity`. Machine-local paths are consumed only to hash files and never appear in candidate output. `gate-results.json` must contain exactly every ID exported as `REQUIRED_GATE_IDS`; prepare both canonical inputs before the aggregate command.

The authoritative CI implementation is `.github/workflows/candidate-proof.yml`. It supplies `GROUNDBALL_SOURCE_COMMIT` at `docker run`, not through an undocumented provider build argument, and boots every image probe with `--network none`. It validates the full canonical provider-cache worker payload with exact JSON scalar types, proves missing/empty/foreign runtime configuration and a hidden cache remain failed without reconstruction, and distinguishes absent prohibited surfaces from retained construction routines that require effective UID 0 at every direct mutation entry point. Its network-disabled UID 10001 image probe directly calls the image builder, cache builder, materializer, database copier, lock, removal, write, and fsync routines; every call must raise before input reads or side effects, with zero files created, removed, or modified, an unchanged immutable cache, and no new DuckDB under `/tmp`. The workflow also enforces the same 1,073,741,824-byte (exactly 1 GiB) domain ceiling and uploads all three records even though protected/provider gates remain blocked. `Dockerfile.vercel` validates the copied bundle against its own canonical Release Manifest during build; runtime still fails closed unless the externally declared source commit exactly matches that immutable manifest.

Wave 7 protected-provider commands, request-scoped OIDC rules, immutable workload/Browser manifests, proof-only namespace rules, evidence derivation, and cleanup boundaries are recorded in `docs/public-release-implementation-ledger.md`. Repository fixtures validate tooling only. Genuine provider-reported memory evidence uses the same strict schema and can support an all-pass candidate, but the actual Ground Ball no-cost run has only the exact Hobby-unavailable variant. Hermes may collect all authorized free evidence, must produce that blocked report, and must stop before attestation or Wave 8.

## Proof boundary

Wave 6 proves repository identity, bundle integrity, deterministic packaged behavior, prohibited-surface absence, local image size, and canonical runtime/admission binding. It creates no Blob state, credential, preview, deployment, provider attestation, protected Browser evidence, cold/warm provider timings, provider memory observation, restart/scale-to-zero evidence, or provider accounting evidence. Missing external evidence is `blocked`, so the local/CI gate report is ineligible by design. Wave 7 can collect no-cost provider evidence, but provider peak memory remains blocked for the actual Hobby run and no attestation can be emitted from its report. This run-specific block does not remove the general all-pass attestation contract.
