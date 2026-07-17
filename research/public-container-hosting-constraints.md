# Public container hosting constraints for Ground Ball

Verified 2026-07-17 from official provider documentation and the authenticated Hugging Face account API.

## Vercel Hobby

- Hobby costs $0 and is restricted to personal, non-commercial use.
- Included monthly usage is 4 active CPU-hours, 360 GB-hours of provisioned memory, and 1,000,000 function invocations. Hobby cannot buy on-demand overages; projects pause after the included allowance is exhausted.
- Vercel Functions on Hobby use 1 vCPU and 2 GB of memory and have a five-minute maximum request duration with Fluid Compute.
- OCI-compatible container images can be deployed from `Dockerfile.vercel`. Vercel builds the image into its Container Registry, routes HTTP traffic to the container, and scales an idle production container down after five minutes.
- Container functions are stateless and inherit Vercel Function size, memory, duration, and pricing limits. Existing Gradio queue, event, session, and concurrent-visitor behavior therefore requires a real preview proof rather than a paper assumption.
- Hobby currently includes 10 GB of Vercel Container Registry image storage.

Official sources:

- <https://vercel.com/docs/plans/hobby>
- <https://vercel.com/pricing>
- <https://vercel.com/kb/guide/does-vercel-support-docker-deployments>
- <https://vercel.com/docs/functions/limitations>

## Cloudflare Containers fallback

- Containers require the Workers Paid plan, with a $5 monthly account minimum.
- The included monthly Container allowance is 25 GiB-hours of memory, 375 vCPU-minutes, and 200 GB-hours of disk. Charges begin only after a request starts a container and stop after it sleeps.
- A low-traffic, aggressively sleeping Ground Ball container is expected to remain near the $5 minimum, but the proof must measure the actual image, memory, disk, CPU, and active-hour shape before this fallback is activated.
- Workers Paid also supplies the site's existing Worker, service-binding, logging, and request-control surfaces, making Cloudflare the integration-first fallback rather than the zero-cost first target.

Official sources:

- <https://developers.cloudflare.com/workers/platform/pricing/>
- <https://developers.cloudflare.com/containers/pricing/>

## Hugging Face

- The personal PRO subscription is currently $9 per month, not $20.
- CPU Basic is listed as free hardware, but current pricing makes creation of Gradio and Docker Spaces a PRO feature.
- The authenticated `DiscoStew` API rejected a Docker Space upload with HTTP 402 and stated that hosting Gradio and Docker Spaces on free `cpu-basic` requires PRO. Git metadata updates remain possible, but the empty Space is not an approved deployment dependency.

Official sources:

- <https://huggingface.co/pricing>
- <https://huggingface.co/docs/hub/main/spaces-overview>

## Decision boundary

Use Vercel Hobby for the first private proof because its personal, non-commercial terms fit this demo and its hard free cap prevents an overage bill. Use Cloudflare Containers only if the Vercel proof records a failed acceptance criterion. Do not activate paid Hugging Face, Vercel PRO, Google Cloud, or another unbounded pay-as-you-go host under this map.
