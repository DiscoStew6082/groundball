"""Routing ownership rules for deterministic freeform questions."""


def deterministic_freeform_owns(
    question: str,
    *,
    competing_stat: str | None = None,
) -> bool:
    """Return whether deterministic freeform should own this route."""
    from baseball_rag.db.freeform_runtime import (
        can_plan_deterministically,
        should_route_deterministic_freeform,
    )

    return can_plan_deterministically(question) and should_route_deterministic_freeform(
        question,
        competing_stat=competing_stat,
    )
