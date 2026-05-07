"""Tests for player biography retrieval + generation path in CLI."""

from unittest.mock import patch

from baseball_rag.cli import answer
from baseball_rag.corpus.player_bios import PlayerCandidate, PlayerResolution
from baseball_rag.retrieval.chroma_store import RetrievedChunk


class TestPlayerBioQuery:
    """Test the player_biography intent handling in cli.answer()."""

    def test_player_biography_intent_routes_correctly(self):
        """A question routed as player_biography should use bio retrieval path."""
        # Mock the route to return player_biography
        mock_chunk = RetrievedChunk(
            text=(
                "Wally Pipp was a first baseman who played for "
                "the Chicago Cubs and New York Yankees."
            ),
            source="/path/to/pipp.md",
            title="Wally Pipp",
            score=0.95,
        )

        with (
            patch("baseball_rag.service.route") as mock_route,
            patch("baseball_rag.service.retrieve_grounded_chunks") as mock_retrieve,
            patch("baseball_rag.service.get_duckdb"),
            patch("baseball_rag.corpus.player_bios.resolve_player_by_name") as mock_resolve,
            patch("baseball_rag.service.init_db"),
        ):
            from baseball_rag.routing import RouteResult

            mock_route.return_value = RouteResult(
                intent="player_biography",
                stat=None,
                time_period=None,
                position=None,
                player_name="Wally Pipp",
                raw_question="who was Wally Pipp",
            )
            mock_retrieve.return_value = [mock_chunk]
            mock_resolve.return_value = PlayerResolution(
                query="Wally Pipp",
                candidates=[PlayerCandidate("pippwa01", "Wally Pipp", "1913-06-29", "1928-09-30")],
            )

            answer("who was Wally Pipp")

            request = mock_retrieve.call_args.args[0]
            assert request.question == "who was Wally Pipp"
            assert request.intent == "player_biography"
            assert request.player_name == "Wally Pipp"
            assert request.player_id == "pippwa01"

    def test_player_biography_can_use_semantic_strategy_without_metadata_filter(self):
        """Strategy selection should let evals compare semantic-only retrieval."""
        mock_chunk = RetrievedChunk(
            text="Wally Pipp was a first baseman.",
            source="/path/to/pipp.md",
            title="Wally Pipp",
            score=0.95,
        )

        with (
            patch("baseball_rag.service.route") as mock_route,
            patch("baseball_rag.service.retrieve_grounded_chunks") as mock_retrieve,
            patch("baseball_rag.service.get_duckdb"),
            patch("baseball_rag.corpus.player_bios.resolve_player_by_name") as mock_resolve,
            patch("baseball_rag.service.init_db"),
        ):
            from baseball_rag.routing import RouteResult
            from baseball_rag.service import answer as structured_answer

            mock_route.return_value = RouteResult(
                intent="player_biography",
                stat=None,
                time_period=None,
                position=None,
                player_name="Wally Pipp",
                raw_question="who was Wally Pipp",
            )
            mock_retrieve.return_value = [mock_chunk]
            mock_resolve.return_value = PlayerResolution(
                query="Wally Pipp",
                candidates=[PlayerCandidate("pippwa01", "Wally Pipp", "1913-06-29", "1928-09-30")],
            )

            structured_answer("who was Wally Pipp", retrieval_strategy="semantic_chroma")

            request = mock_retrieve.call_args.args[0]
            assert request.question == "who was Wally Pipp"
            assert request.player_name == "Wally Pipp"
            assert request.retrieval_strategy == "semantic_chroma"

    def test_player_biography_uses_bio_prompt(self):
        """Player biography path should use build_player_bio_prompt, not explanation prompt."""
        mock_chunk = RetrievedChunk(
            text="Rogers Hornsby was a Hall of Fame second baseman.",
            source="/path/to/hornsby.md",
            title="Rogers Hornsby",
            score=0.9,
        )

        with (
            patch("baseball_rag.service.route") as mock_route,
            patch("baseball_rag.service.retrieve_grounded_chunks") as mock_retrieve,
            patch("baseball_rag.service.get_duckdb"),
            patch("baseball_rag.corpus.player_bios.resolve_player_by_name") as mock_resolve,
            patch("baseball_rag.service.init_db"),
            patch("baseball_rag.generation.prompt.build_player_bio_prompt") as mock_prompt_builder,
        ):
            from baseball_rag.routing import RouteResult

            mock_route.return_value = RouteResult(
                intent="player_biography",
                stat=None,
                time_period=None,
                position=None,
                player_name="Rogers Hornsby",
                raw_question="tell me about Rogers Hornsby",
            )
            mock_retrieve.return_value = [mock_chunk]
            mock_resolve.return_value = PlayerResolution(
                query="Rogers Hornsby",
                candidates=[
                    PlayerCandidate("hornsro01", "Rogers Hornsby", "1915-09-10", "1937-07-20")
                ],
            )
            mock_prompt_builder.return_value = "fake prompt"

            answer("tell me about Rogers Hornsby")

            # The bio path should use build_player_bio_prompt
            assert mock_prompt_builder.called, (
                "player_biography intent should use build_player_bio_prompt"
            )

    def test_player_biography_connection_error_fallback(self):
        """If LM Studio is down during player biography query, show docs instead."""
        mock_chunk = RetrievedChunk(
            text="Mickey Mantle was a switch-hitting outfielder for the New York Yankees.",
            source="/path/to/mantle.md",
            title="Mickey Mantle",
            score=0.95,
        )

        with (
            patch("baseball_rag.service.route") as mock_route,
            patch("baseball_rag.service.retrieve_grounded_chunks") as mock_retrieve,
            patch("baseball_rag.service.get_duckdb"),
            patch("baseball_rag.corpus.player_bios.resolve_player_by_name") as mock_resolve,
            patch("baseball_rag.service.init_db"),
            patch("baseball_rag.generation.llm.make_request") as mock_llm,
        ):
            from baseball_rag.routing import RouteResult

            mock_route.return_value = RouteResult(
                intent="player_biography",
                stat=None,
                time_period=None,
                position=None,
                player_name="Mickey Mantle",
                raw_question="who was Mickey Mantle",
            )
            mock_retrieve.return_value = [mock_chunk]
            mock_resolve.return_value = PlayerResolution(
                query="Mickey Mantle",
                candidates=[
                    PlayerCandidate("mantlmi01", "Mickey Mantle", "1951-04-17", "1968-09-28")
                ],
            )
            # Simulate LM Studio being down
            mock_llm.side_effect = ConnectionError("LM Studio not running")

            result = answer("who was Mickey Mantle")

            assert (
                "LM Studio not running" in result or "showing relevant documents" in result.lower()
            )
            # Should show the chunk content as fallback
            assert "Mickey Mantle" in result

    def test_generated_player_bio_source_includes_data_manifest(self):
        """Generated player profiles should carry source dataset provenance."""
        mock_chunk = RetrievedChunk(
            text="Babe Ruth generated profile.",
            source="ruthba01.md",
            title="Babe Ruth",
            score=0.95,
            player_id="ruthba01",
            doc_kind="generated_player_profile",
        )

        with (
            patch("baseball_rag.service.route") as mock_route,
            patch("baseball_rag.service.retrieve_grounded_chunks") as mock_retrieve,
            patch("baseball_rag.service.get_duckdb"),
            patch("baseball_rag.corpus.player_bios.resolve_player_by_name") as mock_resolve,
            patch("baseball_rag.service.init_db"),
            patch("baseball_rag.generation.llm.make_request") as mock_llm,
        ):
            from baseball_rag.routing import RouteResult
            from baseball_rag.service import answer as structured_answer

            mock_route.return_value = RouteResult(
                intent="player_biography",
                stat=None,
                time_period=None,
                position=None,
                player_name="Babe Ruth",
                raw_question="who was Babe Ruth",
            )
            mock_retrieve.return_value = [mock_chunk]
            mock_resolve.return_value = PlayerResolution(
                query="Babe Ruth",
                candidates=[PlayerCandidate("ruthba01", "Babe Ruth", "1914-07-11", "1935-05-30")],
            )
            mock_llm.side_effect = ConnectionError("LM Studio not running")

            result = structured_answer("who was Babe Ruth")

            assert result.sources[0].data_manifest is not None
            assert result.sources[0].data_manifest["dataset"]["name"] == "NeuML/baseballdata"

    def test_player_biography_no_chunks_returns_helpful_message(self):
        """If no bio chunks found, return a helpful message."""
        with (
            patch("baseball_rag.service.route") as mock_route,
            patch("baseball_rag.service.retrieve_grounded_chunks") as mock_retrieve,
            patch("baseball_rag.service.get_duckdb"),
            patch("baseball_rag.corpus.player_bios.resolve_player_by_name") as mock_resolve,
            patch("baseball_rag.service.init_db"),
        ):
            from baseball_rag.routing import RouteResult

            mock_route.return_value = RouteResult(
                intent="player_biography",
                stat=None,
                time_period=None,
                position=None,
                player_name="Unknown Player",
                raw_question="who was Unknown Player",
            )
            mock_retrieve.return_value = []  # No results
            mock_resolve.return_value = PlayerResolution(query="Unknown Player", candidates=[])

            result = answer("who was Unknown Player")

            assert "No player biography found" in result or "not in the dataset" in result.lower()

    def test_player_biography_not_found_error_shows_ingest_message(self):
        """If ChromaDB raises NotFoundError, suggest running ingest."""
        with (
            patch("baseball_rag.service.route") as mock_route,
            patch("baseball_rag.service.retrieve_grounded_chunks") as mock_retrieve,
            patch("baseball_rag.service.get_duckdb"),
            patch("baseball_rag.corpus.player_bios.resolve_player_by_name") as mock_resolve,
            patch("baseball_rag.service.init_db"),
        ):
            from baseball_rag.routing import RouteResult

            mock_route.return_value = RouteResult(
                intent="player_biography",
                stat=None,
                time_period=None,
                position=None,
                player_name="Some Player",
                raw_question="who was Some Player",
            )
            mock_resolve.return_value = PlayerResolution(
                query="Some Player",
                candidates=[PlayerCandidate("some01", "Some Player", None, None)],
            )
            # Simulate ChromaDB not found error
            mock_retrieve.side_effect = Exception("NotFoundError: collection not found")

            result = answer("who was Some Player")

            assert "ingest" in result.lower() or "indexed" in result.lower()

    def test_ambiguous_player_name_returns_unsupported_without_retrieval(self):
        """Ambiguous names should not silently retrieve a random biography."""
        with (
            patch("baseball_rag.service.route") as mock_route,
            patch("baseball_rag.service.retrieve_grounded_chunks") as mock_retrieve,
            patch("baseball_rag.service.get_duckdb"),
            patch("baseball_rag.corpus.player_bios.resolve_player_by_name") as mock_resolve,
            patch("baseball_rag.service.init_db"),
        ):
            from baseball_rag.routing import RouteResult

            mock_route.return_value = RouteResult(
                intent="player_biography",
                stat=None,
                time_period=None,
                position=None,
                player_name="Johnson",
                raw_question="who was Johnson",
            )
            mock_resolve.return_value = PlayerResolution(
                query="Johnson",
                candidates=[
                    PlayerCandidate("johns01", "Walter Johnson", "1907-08-02", "1927-09-30"),
                    PlayerCandidate("johns02", "Randy Johnson", "1988-09-15", "2009-10-04"),
                ],
            )

            result = answer("who was Johnson")

            assert "ambiguous" in result.lower()
            mock_retrieve.assert_not_called()
