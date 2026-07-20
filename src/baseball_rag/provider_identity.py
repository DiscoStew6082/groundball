"""Exact provider-owned identity validation without normalization."""

from __future__ import annotations

import re

# Every checked-in first-party Vercel deployment ID has the provider's fixed
# 28-character base62 suffix. Keep this exact so malformed or substituted IDs
# cannot enter evidence while preserving valid provider bytes unchanged.
VERCEL_DEPLOYMENT_ID_PATTERN = re.compile(r"dpl_[A-Za-z0-9]{28}", re.ASCII)


def is_exact_vercel_deployment_id(value: object) -> bool:
    """Return whether value is one exact current Vercel deployment ID."""
    return isinstance(value, str) and VERCEL_DEPLOYMENT_ID_PATTERN.fullmatch(value) is not None
