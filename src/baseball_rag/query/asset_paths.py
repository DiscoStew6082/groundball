"""Canonical paths for catalog-owned immutable assets."""

from pathlib import Path


def canonical_asset_name(value: object) -> str:
    """Reject ambiguous, absolute and traversing names before filesystem access."""
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or "\0" in value
        or ":" in value
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        raise ValueError("Unsafe catalog asset path.")
    return value


def contained_asset_path(root: Path, name: object) -> Path:
    """Resolve only canonical paths with no symlink component beneath the root."""
    relative = canonical_asset_name(name)
    if root.is_symlink():
        raise ValueError("Unsafe catalog asset root.")
    resolved_root = root.resolve()
    candidate = resolved_root
    for part in relative.split("/"):
        candidate = candidate / part
        if candidate.is_symlink():
            raise ValueError("Unsafe catalog asset symlink.")
    resolved = candidate.resolve()
    if not resolved.is_relative_to(resolved_root):
        raise ValueError("Unsafe catalog asset escape.")
    return resolved
