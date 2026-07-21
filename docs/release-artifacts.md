# Release Artifact operations

Ground Ball release artifacts are identified by content and exact Git topology, never by a branch label.

## Artifact meanings

- **Release Bundle digest**: SHA-256 of canonical `release/bundle/release-manifest.json`.
- **Public Admission Policy digest**: SHA-256 of canonical `release/config/public-admission-policy.json`.
- **Coverage Report digest**: SHA-256 of the exact checked-in JSON proof copied into the bundle.
- **Release container proof digest**: SHA-256 of canonical output from the network-disabled packaged HTTP probe.
- **Release Artifact ID**: `ground-ball-release-artifact-v1` identity binding those digests, the public interface revision, and exact source/artifact commits.

## Source-to-artifact topology

1. Commit source, tests, workflows, documentation, locks, generated catalog data, Coverage Report, and packaged web assets.
2. Record the full source commit SHA.
3. Assemble `release/bundle` from that exact source tree.
4. Commit only `release/bundle/**` as the source commit's direct child.
5. Validate that the manifest source SHA equals the parent and that every artifact-commit path is under `release/bundle/`.

Any source correction requires a new source commit and a newly assembled artifact-only child.

## Deterministic assembly

The four primary CSVs are normally ignored local inputs. For release regeneration, copy the exact checked bundle inputs into `data/`, remove only those four temporary copies on exit, run the source generators, and verify each generated contract before committing source.

After the source commit exists:

```bash
source_sha="$(git rev-parse HEAD)"
rm -rf release/bundle.next
uv run python -m baseball_rag.public_release_config --check
uv run python -m baseball_rag.release_bundle assemble . release/bundle.next \
  --source-commit "$source_sha"
uv run python -m baseball_rag.release_bundle check release/bundle.next \
  --expected-source-commit "$source_sha"
rm -rf release/bundle
mv release/bundle.next release/bundle
git add release/bundle
git commit -m "build: assemble provider-neutral release bundle"
```

The artifact commit is checked with:

```bash
artifact_sha="$(git rev-parse HEAD)"
test "$(git rev-parse HEAD^)" = "$source_sha"
git diff-tree --no-commit-id --name-only -r "$artifact_sha"
uv run python -m baseball_rag.release_bundle check release/bundle \
  --expected-source-commit "$source_sha"
```

`baseball_rag.release_artifact.build_release_artifact` accepts caller-supplied Git identities and digests. It does not inspect Git, build a container, read credentials, contact a service, or deploy. Store machine-local proof records outside the public repository unless a checked-in public contract explicitly requires one.

## Public proof boundary

Public CI may build the generic `Dockerfile`, start it with networking disabled, and run `baseball_rag.release_container_probe` through loopback inside the container. This proves bundle startup, public admission policy, deterministic query parity and envelope behavior, package synchronization, and prohibited-surface absence. It does not prove any external runtime, account, domain, or deployment state.
