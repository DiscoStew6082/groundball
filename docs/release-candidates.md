# Release candidate operations

Ground Ball release candidates are identified by artifacts, never by a branch label. The pure tooling in `baseball_rag.release_candidate` does not inspect Git, Docker, GitHub, a provider, or credentials. Callers discover exact values and pass them in.

## Artifact meanings

- **Release Manifest digest**: SHA-256 of the canonical provider-neutral `release/bundle/release-manifest.json`. The manifest never contains an image digest.
- **Candidate identity**: binds one scope, 40-hex source commit, distinct 40-hex bundle artifact commit, manifest digest, image digest and measured size, runtime and Public Admission Policy digests, and path-free evidence identities. Its `candidate_id` hashes the canonical document without the `candidate_id` field.
- **Gate report**: contains the fixed Release Gate inventory. Status is exactly `pass`, `fail`, or `blocked`; a pass must reference candidate evidence. Eligibility requires every gate to pass for the same candidate.
- **Deployment Attestation**: remains outside the Release Bundle. Wave 6 emits only a local template stating that no provider deployment exists. A protected or production attestation requires exact provider identity, OCI digest/size, config and gate bindings, observations, and external evidence.
- **Local Docker image identity**: `docker image inspect .Id` is a local content-addressed image ID. `docker image inspect .Size` is a local preliminary byte measurement. Neither is a provider OCI digest/size.

The canonical generated Public Admission Policy is `release/config/public-admission-policy.json`. It is derived from constants the server, coordinator, state codec, and Blob configuration enforce. `release/config/local-ci-runtime.json` is explicitly non-provider, network-disabled, and ephemeral; it cannot represent protected-preview or production proof.

## Freeze and topology

The candidate uses the existing non-circular two-commit model:

1. Commit source, tests, workflows, documentation, and generated non-bundle configuration.
2. Use that exact source commit as `release-manifest.json.source_commit`.
3. Reassemble `release/bundle` deterministically.
4. Commit only `release/bundle/**`; this artifact commit must have the source commit as its direct parent.
5. Keep the PR head at the artifact commit. Any source correction requires a new source commit and another bundle assembly.

The candidate workflow checks full history, the manifest source, the artifact parent, and every changed path. It does not trust a branch name.

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
  --build-arg GROUNDBALL_SOURCE_COMMIT="$SOURCE_COMMIT" \
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

The authoritative CI implementation is `.github/workflows/candidate-proof.yml`. It supplies those inputs, boots the image with `--network none`, runs the Wave 5 packaged probe, checks prohibited surfaces, enforces the preliminary 1 GB local ceiling, and uploads all three records even though protected/provider gates remain blocked.

## Proof boundary

Wave 6 proves repository identity, bundle integrity, deterministic packaged behavior, prohibited-surface absence, local image size, and canonical runtime/admission binding. It creates no Blob state, credential, preview, deployment, provider attestation, protected Browser evidence, cold/warm provider timings, provider memory observation, restart/scale-to-zero evidence, or provider accounting evidence. Missing external evidence is `blocked`, so the local/CI gate report is ineligible by design. Those gates belong to a separately authorized Wave 7 protected-provider exercise.
