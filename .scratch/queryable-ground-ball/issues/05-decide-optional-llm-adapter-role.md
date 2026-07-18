# Decide the optional LLM Adapter role

Type: `grilling`
Status: open
Blocked by: [Specify the deterministic Query Plan Interface](03-specify-deterministic-query-plan-interface.md)

## Question

Once the deterministic Query Plan can express the complete published data surface, should an optional premium LLM Adapter have any role in paraphrase interpretation or verified narration, and what Interface guarantees that free Ground Ball remains fully effective and behaviorally complete when that Adapter is absent? Delivery topology, accounts, billing, usage, and hosting remain separate unresolved decisions.

## Idea to evaluate

- Keep the default deterministic structured Ground Ball experience free.
- Offer LLM-assisted queries only through an optional premium tier.
- Preserve DuckDB/Lahman as the factual authority in both tiers, with the Published Query Catalog, deterministic Query Plan, verified rows, SQL, and source metadata forming the shared deterministic verification contract.
- Decide later whether premium LLM access covers interpretation, narration, or both, and what account, billing, usage, and hosting model it requires.

This records a product-tiering idea, not an authorization to add billing, enable public LLM inference, change the zero-Mac public-demo contract, activate paid hosting, or make the free structured product depend on an LLM.
