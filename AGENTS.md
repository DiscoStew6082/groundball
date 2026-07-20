# Ground Ball contributor guidance

- Treat `CONTEXT.md` as the current product and architecture contract.
- Preserve the Published Query Catalog, Query Recipe, Query Plan v1, Query Run, QueryEvidence, Coverage Report, and immutable Release Bundle interfaces.
- Keep public application composition portable. Public source accepts injected `PublicAppBindings`; concrete hosting integrations belong outside this repository.
- Use test-driven development for behavior changes and regenerate checked-in query or web artifacts when their inputs change.
- Run risk-scaled Python, web, lint, type, release, and neutrality checks before committing.
- Do not restore deleted query compatibility facades, alternate registries, provider implementations, or deployment tooling.
- Keep release topology non-circular: commit source artifacts first, then commit only `release/bundle/**` with the source commit as the artifact commit's direct parent.
