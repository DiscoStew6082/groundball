# Cloudflare Tunnel Deployment

Groundball's website integration keeps `https://discostew.dev` on Cloudflare
Pages and exposes only the local FastAPI origin through a separate Tunnel
hostname:

```text
https://discostew.dev/groundball/
  -> browser UI on the static blog
  -> same-origin Cloudflare Pages Function at /groundball/query
  -> https://groundball.discostew.dev/query with optional Access service token
  -> Cloudflare Tunnel
  -> http://127.0.0.1:8001/query on the local Mac
  -> local DuckDB data and local LM Studio
```

Do not route the apex `discostew.dev` hostname to the Tunnel. The blog remains
the Cloudflare Pages project `discostew-blog`; Groundball uses the subdomain
`groundball.discostew.dev`.

## Local Origin

Start LM Studio's OpenAI-compatible server first. The hosted profile uses Gemma
4 12B:

```bash
export LMSTUDIO_BASE_URL=http://localhost:1234/v1
export LMSTUDIO_MODEL=unsloth/gemma-4-12b-it
export GROUNDBALL_CORS_ORIGINS=https://discostew.dev,http://localhost:4321,http://127.0.0.1:4321
export GROUNDBALL_ORIGIN_PROXY_TOKEN=<shared Pages Function secret>

uv run uvicorn baseball_rag.api.server:app --host 127.0.0.1 --port 8001
```

The local model endpoint currently also lists `google/gemma-4-12b`; keep the
instruct-tuned model above for browser-facing prose mode unless you intentionally
want the base model.

## Tunnel

Create a Cloudflare Tunnel from the Zero Trust dashboard or `cloudflared`. The
public hostname should be:

```text
groundball.discostew.dev -> http://127.0.0.1:8001
```

For a persistent Mac setup, install `cloudflared` as a service using the
dashboard-generated command for the Tunnel token. Do not commit the token or
credentials file to this repository.

Protect the Tunnel hostname with Cloudflare Access Service Auth while the demo
is private. Create a Cloudflare Access service token and add the generated
client ID and client secret to the `discostew-blog` Pages project as encrypted
variables:

```text
GROUNDBALL_API_ORIGIN=https://groundball.discostew.dev
GROUNDBALL_VISITOR_TOKEN=<private mobile session token>
GROUNDBALL_ORIGIN_PROXY_TOKEN=<shared local API proxy token>
GROUNDBALL_ACCESS_CLIENT_ID=<service token client id>
GROUNDBALL_ACCESS_CLIENT_SECRET=<service token client secret>
```

The browser should not authenticate to `groundball.discostew.dev` directly.
The blog calls same-origin `/groundball/query`; the Pages Function forwards the
request and adds the Access service-token headers server-side. LM Studio stays
local and is never routed through Cloudflare.

If the Cloudflare API token available on the machine cannot manage Access
applications, use `GROUNDBALL_ORIGIN_PROXY_TOKEN` as the private origin guard.
Set the same high-entropy value in the local API LaunchAgent and the Pages
Function secrets. Direct Tunnel callers without `X-Groundball-Proxy-Token`
receive `403`, while the blog remains automatic because the Pages Function adds
the header server-side.

`GROUNDBALL_VISITOR_TOKEN` is required. If it is empty, `/groundball/*` returns
a noindex `404` instead of serving the UI or forwarding queries, so the
automatic browser path does not quietly become public.

### CORS Boundary

The production website path is same-origin, so it does not need browser CORS or
an Access sign-in link. Keep FastAPI's CORS allowance as a local/direct-review
fallback only, and keep it limited to `POST /query`. Operator endpoints such as
`/evals/*` and `/review-queue` remain local/server surfaces.

## Smoke Checks

Local origin:

```bash
curl -sS http://127.0.0.1:8001/health

curl -i -X OPTIONS http://127.0.0.1:8001/query \
  -H 'Origin: https://discostew.dev' \
  -H 'Access-Control-Request-Method: POST' \
  -H 'Access-Control-Request-Headers: content-type'

curl -sS http://127.0.0.1:8001/query \
  -H "X-Groundball-Proxy-Token: $GROUNDBALL_ORIGIN_PROXY_TOKEN" \
  -H 'content-type: application/json' \
  -H 'Origin: https://discostew.dev' \
  -d '{"question":"who had the most RBIs in 1962","answer_mode":"stats_only"}'
```

Direct Tunnel check with Access Service Auth:

```bash
curl -sS https://groundball.discostew.dev/query \
  -H "CF-Access-Client-Id: $GROUNDBALL_ACCESS_CLIENT_ID" \
  -H "CF-Access-Client-Secret: $GROUNDBALL_ACCESS_CLIENT_SECRET" \
  -H "X-Groundball-Proxy-Token: $GROUNDBALL_ORIGIN_PROXY_TOKEN" \
  -H 'content-type: application/json' \
  -d '{"question":"who had the most RBIs in 1962","answer_mode":"stats_only"}'
```

Direct Tunnel check without the origin proxy token:

```bash
curl -i https://groundball.discostew.dev/query \
  -H "CF-Access-Client-Id: $GROUNDBALL_ACCESS_CLIENT_ID" \
  -H "CF-Access-Client-Secret: $GROUNDBALL_ACCESS_CLIENT_SECRET" \
  -H 'content-type: application/json' \
  -d '{"question":"who had the most RBIs in 1962","answer_mode":"stats_only"}'
```

When `GROUNDBALL_ORIGIN_PROXY_TOKEN` is configured locally, expect `403` with
`{"error":"groundball_origin_proxy_token_required"}`.

Private website route:

```text
https://discostew.dev/groundball/?groundball_token=<private mobile session token>
```

The first request sets an `HttpOnly` `groundball_session` cookie scoped to
`/groundball` and redirects to `https://discostew.dev/groundball/`. Use a
URL-safe token such as `openssl rand -hex 32`, or URL-encode the token when
building the private link.

Create a curl cookie jar from the private link before running same-origin query
checks:

```bash
curl -sS -i -c cookies.txt 'https://discostew.dev/groundball/?groundball_token=<private mobile session token>'
```

Private same-origin function check:

```bash
curl -sS -b cookies.txt https://discostew.dev/groundball/query \
  -H 'content-type: application/json' \
  -d '{"question":"who had the most RBIs in 1962","answer_mode":"stats_only"}'
```

Without a valid `groundball_session` cookie, expect a noindex `404` and no
upstream fetch.

Unsupported method check:

```bash
curl -i -b cookies.txt https://discostew.dev/groundball/query
```

With a valid cookie, expect `405` with `{"error":"method_not_allowed"}`.
Without a valid cookie, expect the private noindex `404` instead.

The page should return an answer, rows, provenance JSON, and SQL for the default
question. If the browser reports `local almanac is not ready`, check Tunnel
health, the Pages Function variables/secrets, the local FastAPI process, and LM
Studio.

## Public Readiness

Before opening this beyond Stewart:

- keep `/evals/*`, `/review-queue`, and other operator endpoints behind Access
- keep `/groundball/*` behind the visitor-token middleware while the demo is
  private
- add Cloudflare rate limiting or WAF rules for `/groundball/query`
- set a request-size/question-length policy
- keep the Pages Function limited to the public query route
- confirm dataset attribution and provenance remain visible in the page

Cloudflare references:

- Cloudflare Tunnel: https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/
- Self-hosted applications with Access: https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/self-hosted-public-app/
- Access service tokens: https://developers.cloudflare.com/cloudflare-one/access-controls/service-credentials/service-tokens/
- Pages Functions: https://developers.cloudflare.com/pages/functions/
