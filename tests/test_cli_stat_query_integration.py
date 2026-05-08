"""End-to-end tests for stat-query pipeline — routes through router → cli → DB.

These are integration tests that exercise the full stack: routing, time-period
resolution in cli.py, DuckDB queries, and output formatting. They use real DB
data as ground truth so they test the system, not model knowledge.
"""

from baseball_rag.cli import answer


class TestStatQueryPipeline:
    """Full-pipeline integration tests for stat leaderboard queries."""

    def test_full_pipeline_seventies_hr_leader(self):
        """CLI returns Willie Stargell as 1970s HR leader via full pipeline."""
        result = answer("who hit the most homers in the seventies")
        assert "Stargell" in result
        assert "296" in result

    def test_full_pipeline_decade_rbi_query(self):
        """CLI handles decade RBI query through full pipeline."""
        result = answer("most RBIs in the eighties")
        # Just verify it produces structured-looking output with a number
        assert any(c.isdigit() for c in result)

    def test_full_pipeline_explicit_range(self):
        """CLI handles explicit year range through full pipeline."""
        result = answer("who led MLB in HR between 1960-1980")
        # Should return some names, not an error
        assert len(result) > 50

    def test_career_hr_leaders_still_works(self):
        """No time filter falls back to career leaders."""
        result = answer("career home run leaders")
        assert "Ruth" in result or "Babe" in result

    def test_fielding_putouts_query_uses_normal_stat_answer_path(self):
        """Fielding PO leaders should answer through the normal stat query path."""
        result = answer("outfield putouts leaders in 1983")

        assert "Top PO leaders (1983-1983):" in result
        assert "1. Manning, Rick: 471 PO" in result
        assert "Dawson, Andre" in result

    def test_specific_outfield_putouts_query_uses_supported_dataset_position(self):
        result = answer("center field putouts leaders in 1983")

        assert "Top PO leaders (1983-1983):" in result
        assert "1. Manning, Rick: 471 PO" in result


class TestTimePeriodResolution:
    """Unit tests for decade/range resolution logic extracted from cli.py."""

    def test_decade_seventies_resolves_to_1970_1979(self):
        """decade=70 → (1970, 1979)."""
        start, end = _resolve(70, "decade")
        assert start == 1970
        assert end == 1979

    def test_decade_eighties_resolves_to_1980_1989(self):
        """decade=80 → (1980, 1989)."""
        start, end = _resolve(80, "decade")
        assert start == 1980
        assert end == 1989

    def test_range_passes_through(self):
        """RANGE type passes [1960, 1980] through unchanged."""
        start, end = _resolve([1960, 1980], "range")
        assert start == 1960
        assert end == 1980


# Mirror the resolution logic from cli.py so tests stay stable if it moves
def _resolve(value, period_type: str):
    if period_type == "decade":
        start = 1900 + value  # value IS the decade digit (70 → 1970), not digit*10
        return start, start + 9
    elif period_type == "range":
        return value[0], value[-1]
    else:
        raise ValueError(f"Unsupported type for this test: {period_type}")
