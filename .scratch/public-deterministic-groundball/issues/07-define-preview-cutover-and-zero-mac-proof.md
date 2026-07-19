# Define preview cutover and zero-Mac proof

Type: `grilling`
Status: resolved
Blocked by: [Prototype the website-framed hosted Ground Ball experience](03-prototype-groundball-app-interior.md), [Define parity and release gates](06-define-parity-and-release-gates.md)

## Question

What Vercel Hobby preview-to-public topology, website integration switch, previously verified hosted rollback mechanism, confirmation that the disabled Mac LaunchAgents and tunnel remain unused, and external verification evidence are sufficient to prove the clean-cutover Svelte/FastAPI application works with zero route to Stewart's Mac, and what exact failed acceptance criterion requires aborting promotion or reopening the hosting decision?

## Answer

Use the website launcher as the final public switch. First freeze and validate one Vercel Release Candidate under the all-or-nothing Release Gates defined by [Define parity and release gates](06-define-parity-and-release-gates.md). A promoted Preview is not assumed to retain its Preview identity or evidence: the final production-built deployment must receive its own Deployment Attestation and pass every applicable gate before the website changes. Preview, production, and website evidence must identify the same source commit, Release Bundle and Release Manifest digest, container image, runtime configuration, Public Admission Policy configuration, and final deployment identity.

The website owns only the launch and surrounding frame. Its cutover is one reversible target change from the prelaunch state to the verified Vercel application; it must not add another query Interface, hosted-only application surface, proxy, or execution Adapter. Before that switch, Codex sends Stewart the final candidate link. External acceptance is exactly Stewart opening that link and reporting whether it works. Stewart's approval is required but does not replace the machine Release Gates.

The zero-Mac claim belongs to the hosted artifact and public route, not to an operational test performed on Stewart's Mac. There has never been a Vercel tunnel. Release evidence must show that the deployed source, container, runtime configuration, environment, and Deployment Attestation contain no Mac address or hostname, tunnel endpoint, origin proxy, Mac credential, LM Studio credential, LLM route, or alternate fallback, and that the hosted runtime contacts only Vercel and the approved Vercel coordination store. Do not inspect, disconnect, stop, reconfigure, or otherwise change Stewart's Mac, its network access, LaunchAgents, or any tunnel state as part of this proof.

For the first public launch, rollback means reverting the website launcher to its prelaunch state, leaving no Mac-backed or alternate-host fallback. For later releases, Vercel rollback may return only to the immediately previous production deployment after its identity and previously passing evidence have been confirmed. If no such verified production release exists, the safe rollback remains the website's prelaunch or unavailable state.

Promotion aborts immediately if any Release Gate fails, candidate identities disagree, the website points anywhere other than the attested Vercel deployment, the launched application does not match the approved dark Svelte/FastAPI shell, the post-switch route fails, or Stewart reports that the candidate link does not work. A failed application candidate is fixed and retested on Vercel; a transient provider failure also blocks that candidate rather than silently becoming acceptance.

Reopen the hosting decision only when root-cause evidence shows that Vercel Hobby cannot satisfy a required gate without weakening the approved product, exceeding the $0 personal non-commercial budget, or violating the zero-Mac boundary. A Ground Ball defect, missing evidence, candidate mismatch, or transient failure does not by itself activate Cloudflare or any other host. Cloudflare Containers remain a fresh, separately approved effort if and only if that Vercel-specific threshold is reached.

This decision authorizes no deployment, promotion, website change, domain change, secret change, paid plan, Mac operation, or production mutation. It completes the planning route; implementation and release execution require a separate handoff and Stewart's explicit approval.
