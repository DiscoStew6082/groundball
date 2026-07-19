# Choose the packaged deterministic data release

Type: `grilling`
Status: resolved
Blocked by: [Prove the stateless Svelte/FastAPI Vercel fit](12-prove-stateless-svelte-fastapi-vercel-fit.md)

## Question

Which artifacts from the merged Published Lahman Source Registry, Published Query Catalog, generated raw-field inventory, compact governed Retrosheet projections, DuckDB data, licenses, checksums, provenance, and coverage proof should ship in the immutable hosted release so every published deterministic capability works without runtime downloads while the complete image remains comfortably inside Vercel Hobby's limits?

## Answer

Ship one provider-neutral **Release Bundle**: a preassembled, immutable, self-contained set of data, catalog, proof, provenance, and license artifacts copied verbatim into the application image. A final Release Bundle must be buildable and runnable without network acquisition. Upstream downloads may produce disposable inputs before assembly, but neither the container build nor runtime may fetch bytes that become part of the identified bundle.

The currently governed payload is approximately 30.53 MB, so these artifacts are not the material image-size risk. The retained 132.84 MB Vercel image was measured before the merged Queryable Ground Ball cutover and is not current release evidence. The later parity work must rebuild the selected source commit, record the actual image size and resource behavior, and verify Vercel limits rather than inheriting the older measurement.

### Required contents

The Release Bundle contains exactly the release-bearing artifacts needed by the initial public deterministic surface:

- the four primary Lahman CSVs for People, Batting, Pitching, and Fielding, plus their release-scoped source manifest;
- the Published Lahman Source Registry, Published Query Catalog root and promoted definitions, generated raw-field inventory, and all compatibility bindings;
- the Lahman and Retrosheet season-aware team-reference CSVs with their manifests;
- the canonical machine-readable Coverage Report for the exact catalog, data release, compiler, Adapter, and source revision;
- the compact pitcher strikeout-side Retrosheet projection and a projection-only manifest that describes only artifacts actually present;
- the Ground Ball license and explicit Lahman/NeuML and Retrosheet license, copyright, attribution, source, and disclaimer material; and
- one Release Manifest enumerating the complete payload and defining the bundle identity.

Do not ship the full Retrosheet batting, pitching, fielding, or biodata archives; persistent DuckDB files; local caches; downloader tooling; or duplicate generated human reports. Ground Ball materializes its query relations from the immutable CSVs in memory. Human coverage and attribution pages render from the canonical machine records rather than becoming parallel authorities.

### Initial Retrosheet boundary

A **Published Retrosheet Capability** exists only when its reviewed compact projection and matching proof are present in the Release Bundle. The initial hosted release therefore publishes only the three template families backed by the existing strikeout-side projection:

- named-pitcher career or season strikeout-side counts, including the supported opponent filter;
- named-pitcher strikeout-side game logs, including the supported year and opponent filters; and
- the career strikeout-side leaderboard.

The batting-stat streak, player batting game-log, and pitcher daily strikeout game-log templates remain unavailable and unadvertised until each gains a compact governed projection and proof. They must not match publicly and then fail against a missing table. Shipping raw Retrosheet archives to make those templates incidentally work is not an acceptable substitute.

### Identity and provider portability

The **Release Manifest** is the provider-neutral machine identity. It records every payload-member path, byte size, row count where applicable, SHA-256 digest, schema and year coverage, upstream source and release, data-release identity, catalog, registry, inventory, and Coverage Report revisions, source commit, and applicable license or notice. The manifest does not list or hash itself; the SHA-256 of its canonical bytes is the Release Bundle digest.

A separate **Deployment Attestation** records the manifest digest and binds that unchanged Release Bundle to one provider's container-image digest, deployment identity, runtime configuration, and verified hosting evidence. The container digest stays outside the Release Manifest to avoid a circular self-hash. Moving the same bundle from Vercel to an OCI-compatible provider such as Cloudflare Containers changes the deployment Adapter and attestation, not the data release. A non-container rewrite such as Workers plus D1 is a new implementation effort rather than a hosting migration.

### Freeze rule

Development may assemble disposable candidate payloads. A payload becomes an immutable Release Bundle only when all of these artifact conditions hold for one fixed source commit:

- catalog compatibility and the regenerated Coverage Report pass for the exact payload contents and source revision;
- the strikeout-side projection passes its row, checksum, manifest, and provenance proof;
- licenses and third-party notices are present and render from the canonical records;
- an offline cold boot succeeds with no data or catalog downloads; and
- recomputing every declared payload checksum and the canonical manifest digest reproduces the Release Bundle identity.

Application admission remains owned by [Define parity and release gates](06-define-parity-and-release-gates.md). Its mandatory inputs include the exact Ohtani cross-discipline question returning 2022, 34 home runs, and 15 pitching wins; the composed player-name regression; and proof that only bundle-backed Retrosheet capabilities are advertised and executable. A bundle that fails those checks cannot receive a Deployment Attestation eligible for promotion or cutover.

Hosting performance, public request and export ceilings, abuse controls, provider-specific security, deployment verification, and cutover remain owned by their later Wayfinder tickets. This decision does not authorize bundle construction or deployment.
