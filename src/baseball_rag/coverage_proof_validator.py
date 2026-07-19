"""Validate the checked-in query coverage proof without regenerating it."""

from __future__ import annotations

from baseball_rag.query import coverage


def validate_checked_in_coverage_proof() -> dict[str, object]:
    """Return the current passing proof when both checked-in forms are exact."""
    report = coverage.load_passing_coverage_report()
    expected_markdown = coverage.render_coverage_markdown(report)
    try:
        checked_in_markdown = coverage.COVERAGE_MARKDOWN_PATH.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise coverage.CoverageProofUnavailableError(
            "Coverage Report markdown is unavailable."
        ) from exc
    if checked_in_markdown != expected_markdown:
        raise coverage.CoverageProofUnavailableError(
            "Coverage Report markdown does not match the canonical proof."
        )
    return report


def main() -> None:
    """Validate the checked-in proof for CI and local fast checks."""
    try:
        validate_checked_in_coverage_proof()
    except coverage.CoverageProofUnavailableError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
