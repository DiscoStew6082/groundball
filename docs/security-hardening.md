# Security hardening, 2026-10-10

The Codex Security Cloud repository scan reviewed source commit `bb70ff995aaa8b2e80594d6a6274dd547cb594da`. It reported ten findings. The cookie-independent admission repair was already published in public release `8761730`. The remaining repairs cover the interfaces below.

| Finding | Enforcement boundary |
| --- | --- |
| Rotatable visitor cookie | Stable deployment identity, independent of visitor cookies; existing admission regression checks |
| Request body buffered before size check | Public POST stream stops above 16 KiB; ten-second receive timeout |
| Stale or mismatched pregame fixture | Fresh retained normalized evidence must match displayed fixture fields |
| Export ceilings enforced too late | Query execution suppresses over-limit rows before Python materialization; bounded public export rendering |
| Unauthenticated, unbounded HTTP MCP | Loopback transport and bounded Statcast work |
| Catalog paths escape release roots | Canonical relative paths and containment checks before asset access |
| Runtime accepts an unapproved bundle | Independent expected digest and verified snapshot used by runtime consumers |
| Unexpected Retrosheet ZIP entries overwrite governed files | Exact known member allowlists and staged extraction |
| Unbounded downloads and ZIP expansion | Download, member, expansion, ratio and row budgets with staged installation |
| Unbounded model and research envelopes | Byte, structure and collection budgets at injected interfaces |

## Integration requirements

Hosting remains outside public source. The deployment initializer must supply the approved source commit and bundle digest independently of the bundle being checked. Compute and approve these values during release publication; reading an expected digest from an untrusted replacement at startup defeats the pin.

Pregame adapters must retain `source.record.normalized` with the fixture identity, team IDs, start, status and optional venue that drive the answer. The source record fingerprint covers this retained record. Observation age is at most ten minutes, with sixty seconds of future clock skew. Existing current-leader and probable-pitcher evidence keeps its same normalized-record contract.

The optional MCP HTTP server is for local use. Remote service requires a separately authenticated gateway with ingress and rate controls. HTTP requests must use a loopback Host and, when present, a loopback Origin to prevent browser DNS rebinding. Native clients may omit Origin. CORS is not authentication.

Offline ingestion needs exclusive access. Each installed file uses atomic replacement, and installation errors restore the previous file set. This is not a multi-file transaction for concurrent readers or machine power loss.

## Verification and limits

Regression checks use the existing HTTP, Query Run, release readiness, interpretation, ResearchSources, ingestion and MCP interfaces. They cover the reported attack paths without pinning editorial prose or copying implementation inventories.

Final local validation passed 772 fast Python tests, five release-proof tests, 99 MCP tests and all 26 query evaluation cases. Web tests, web build, packaged assets, Ruff, mypy, Coverage Report validation and package neutrality passed. Independent review found no remaining blocking issues.

Application checks cannot prevent an injected adapter from allocating an oversized object before returning it. Adapters and host processes must also enforce their own network and memory limits. Public validation rejects oversized materialized results before copying, searching or serializing them.

Public exports keep the existing 3,000-row and response-byte ceilings. Query execution enforces the row ceiling before Python materialization, and rendering stops at its byte budget. Public/release DuckDB execution uses 256 MiB, four threads and no disk spilling. The default POSIX child uses a 1 GiB address-space limit where supported. macOS rejects the available process-limit calls on the validation host; an injected deployment runner must supply whole-process memory isolation there. These checks do not establish a hard macOS resident-memory ceiling.

On the validation host, a real 3,000-row export used 216,498,176 bytes of peak resident memory. Refusing a 3,613-row export used 216,203,264 bytes. These are observations for those requests, not fixed memory guarantees. Linux address-space enforcement was not exercised in this macOS session.

Release snapshots admit only the fixed bundle payload, at most 64 MiB per file and 128 MiB total. The snapshot is private to the process owner and read-only by filesystem permissions; it is not isolation from another process running as that same owner.

Raw ingestion allows at most 256 MiB compressed, 1 GiB per member, 2 GiB expanded per archive, 512 members, a 2 MiB ZIP directory, compression ratio 200 and ten million CSV rows. These bounds admit the existing 681 MB Retrosheet batting member. Ordinary raw archives allow only their expected CSV. Official biodata admits its seven known CSV names and extracts only `biofile0.csv`. ZIP64, duplicate entries, symlinks and unexpected members are refused. Event archives use tighter 64 MiB compressed, 16 MiB per member and 256 MiB expanded budgets.

MCP tools share one active-call slot and sixty calls per rolling minute. Statcast requests allow seven inclusive days, at most forty players, twenty thousand frame rows, 128 columns and 16 MiB before conversion. Responses stop at 1 MiB. HTTP bodies stop at 64 KiB or five seconds; eight concurrent connections is the transport ceiling. See the [MCP guide](../src/mlb_api_mcp/README.md) for operation and upstream-allocation limits.

Public source validation and a regenerated Release Bundle do not establish live deployment or close Cloud scan records. Publication, private runtime integration and live verification are separate steps.
