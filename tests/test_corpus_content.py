"""Tests for corpus content existence."""

from urllib.parse import urlsplit

from baseball_rag.corpus import get_stat_defs


class TestCorpusContent:
    """Verify corpus files exist and are parseable."""

    def test_stat_definitions_exist(self):
        """At least 10 stat definition documents exist."""
        paths = get_stat_defs()
        assert len(paths) >= 10, f"Expected ≥10 stat defs, got {len(paths)}: {paths}"

    def test_stat_definitions_have_frontmatter(self):
        """Each stat definition has valid YAML frontmatter with required fields."""
        from baseball_rag.corpus.frontmatter import parse_frontmatter

        for path in get_stat_defs():
            content = path.read_text()
            result = parse_frontmatter(content)
            assert "metadata" in result, f"{path.name} missing metadata"
            meta = result["metadata"]
            assert "title" in meta, f"{path.name} missing title in frontmatter"
            assert "category" in meta, f"{path.name} missing category"
            assert meta["category"] == "stat_definition"

    def test_stat_definitions_have_body(self):
        """Each stat definition has non-empty body text."""
        from baseball_rag.corpus.frontmatter import parse_frontmatter

        for path in get_stat_defs():
            result = parse_frontmatter(path.read_text())
            assert len(result["body"].strip()) > 50, f"{path.name} body too short"

    def test_stat_definitions_retain_individual_primary_source_links(self):
        """Reviewed definitions expose distinct MLB glossary references for citations."""
        from baseball_rag.corpus.frontmatter import parse_frontmatter

        urls = []
        for path in get_stat_defs():
            metadata = parse_frontmatter(path.read_text())["metadata"]
            source_url = metadata.get("source_url", "")
            parsed = urlsplit(source_url)
            assert parsed.scheme == "https", f"{path.name} needs an HTTPS source"
            assert parsed.netloc == "www.mlb.com", f"{path.name} needs a primary source"
            assert parsed.path.startswith("/glossary/standard-stats/")
            assert parsed.path.removeprefix("/glossary/standard-stats/").strip("/")
            urls.append(source_url)
        assert len(set(urls)) == len(urls), "Definitions must cite their own glossary entries"
