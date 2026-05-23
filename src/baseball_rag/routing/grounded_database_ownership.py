"""Routing ownership rules for deterministic grounded database questions."""


def deterministic_grounded_database_owns(
    question: str,
    *,
    competing_stat: str | None = None,
) -> bool:
    """Return whether deterministic grounded database planning should own this route."""
    from baseball_rag.db.freeform_runtime import (
        can_plan_deterministically,
        should_route_deterministic_grounded_database,
    )

    return can_plan_deterministically(question) and should_route_deterministic_grounded_database(
        question,
        competing_stat=competing_stat,
    )
