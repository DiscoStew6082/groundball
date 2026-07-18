# Confirm current public container hosting constraints

Type: `research`
Status: resolved
Blocked by: none

## Question

What do current official sources and live account checks establish about the price, hard limits, container support, scale-to-zero behavior, and relevant use restrictions of Vercel Hobby, Cloudflare Containers, and Hugging Face Spaces for the deterministic Ground Ball application?

## Answer

[Public container hosting constraints for Ground Ball](../../../research/public-container-hosting-constraints.md) records the current facts. Vercel Hobby is the $0 first proof target for this personal, non-commercial demo and hard-pauses rather than billing overages. Its new OCI-container support is stateless and bounded, so the existing Gradio application requires a real compatibility proof. Cloudflare Containers require the $5 Workers Paid plan and remain the approved fallback. Hugging Face requires a $9 PRO subscription for the relevant Gradio/Docker hosting path and is not approved.
