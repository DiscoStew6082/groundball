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

    def test_player_biography_no_chunks_and_llm_unavailable_returns_helpful_message(self):
        """If no bio chunks or LLM fallback are available, return a helpful message."""
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
                player_name="Unknown Player",
                raw_question="who was Unknown Player",
            )
            mock_retrieve.return_value = []  # No results
            mock_resolve.return_value = PlayerResolution(query="Unknown Player", candidates=[])
            mock_llm.side_effect = ConnectionError("LM Studio not running")

            result = answer("who was Unknown Player")

            assert "No player biography found" in result
            assert "LM Studio was unavailable" in result

    def test_missing_player_biography_uses_labeled_llm_memory_fallback(self):
        """If no corpus bio is found, answer from LLM memory with clear provenance."""
        with (
            patch("baseball_rag.service.route") as mock_route,
            patch("baseball_rag.service.retrieve_grounded_chunks") as mock_retrieve,
            patch("baseball_rag.service.get_duckdb"),
            patch("baseball_rag.corpus.player_bios.resolve_player_by_name") as mock_resolve,
            patch("baseball_rag.service.init_db"),
            patch("baseball_rag.generation.llm.make_request") as mock_llm,
        ):
            from baseball_rag.generation.llm import LLMResponse
            from baseball_rag.routing import RouteResult
            from baseball_rag.service import answer as structured_answer

            mock_route.return_value = RouteResult(
                intent="player_biography",
                stat=None,
                time_period=None,
                position=None,
                player_name="Dale Murphy",
                raw_question="who was Dale Murphy?",
            )
            mock_retrieve.return_value = []
            mock_resolve.return_value = PlayerResolution(query="Dale Murphy", candidates=[])
            mock_llm.return_value = LLMResponse(
                content="Dale Murphy was a star outfielder for Atlanta.",
                model="test-model",
                done=True,
            )

            result = structured_answer("who was Dale Murphy?")

            assert "Dale Murphy was a star outfielder" in result.answer
            assert "LLM memory" in result.answer
            assert result.warnings == [
                "No local corpus biography was found; the answer came from LLM memory."
            ]
            assert result.sources[0].type == "system"
            assert result.sources[0].label == "LLM memory"
            assert result.unsupported is False

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

    def test_ambiguous_player_bio_does_not_anchor_pronoun_context(self):
        """Unsupported direct bios should not become the active player referent."""
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

            result = structured_answer("who was Johnson")

            assert result.unsupported is True
            assert "context_player_name" not in result.metadata
            mock_retrieve.assert_not_called()

        prior_turns = [{"question": "who was Johnson", "answer": result.to_dict()}]
        with (
            patch("baseball_rag.service.route") as mock_route,
            patch("baseball_rag.service.init_db"),
        ):
            from baseball_rag.routing import RouteResult
            from baseball_rag.service import answer as structured_answer

            mock_route.return_value = RouteResult(
                intent="player_biography",
                stat=None,
                time_period=None,
                player_name=None,
                raw_question="what teams did he play for?",
            )

            structured_answer("what teams did he play for?", conversation=prior_turns)

            mock_route.assert_called_once_with("what teams did he play for?")

    def test_followup_player_bio_uses_prior_data_row_as_context(self):
        """A follow-up can refer to a player returned by the previous data-backed turn."""
        mock_chunk = RetrievedChunk(
            text="Hank Aaron was a Hall of Fame right fielder.",
            source="/path/to/aaron.md",
            title="Hank Aaron",
            score=0.95,
        )
        prior_turns = [
            {
                "question": "career home run leaders",
                "answer": {
                    "answer": "All-time career HR leaders",
                    "intent": "stat_query",
                    "sources": [
                        {
                            "type": "duckdb",
                            "label": "Career HR leaders",
                            "rows": [
                                {"name": "Bonds, Barry", "stat_value": 762},
                                {"name": "Aaron, Hank", "stat_value": 755},
                            ],
                        }
                    ],
                },
            }
        ]

        with (
            patch("baseball_rag.service.route") as mock_route,
            patch("baseball_rag.service.retrieve_grounded_chunks") as mock_retrieve,
            patch("baseball_rag.service.get_duckdb"),
            patch("baseball_rag.corpus.player_bios.resolve_player_by_name") as mock_resolve,
            patch("baseball_rag.service.init_db"),
            patch("baseball_rag.generation.llm.make_request") as mock_llm,
        ):
            from baseball_rag.generation.llm import LLMResponse
            from baseball_rag.routing import RouteResult
            from baseball_rag.service import answer as structured_answer

            mock_route.return_value = RouteResult(
                intent="player_biography",
                stat=None,
                time_period=None,
                player_name="Hank Aaron",
                raw_question="tell me about Hank Aaron",
            )
            mock_retrieve.return_value = [mock_chunk]
            mock_resolve.return_value = PlayerResolution(
                query="Hank Aaron",
                candidates=[PlayerCandidate("aaronha01", "Hank Aaron", "1954-04-13", "1976-10-03")],
            )
            mock_llm.return_value = LLMResponse(
                content="Hank Aaron was a Hall of Fame right fielder.",
                model="test-model",
                done=True,
            )

            result = structured_answer(
                "tell me about the second player",
                conversation=prior_turns,
            )

            mock_route.assert_called_once_with("tell me about Hank Aaron")
            request = mock_retrieve.call_args.args[0]
            assert request.player_name == "Hank Aaron"
            assert request.player_id == "aaronha01"
            assert result.metadata["context_question"] == "tell me about Hank Aaron"
            assert result.metadata["context_source"] == "career home run leaders"
            assert result.metadata["context_player_name"] == "Hank Aaron"

    def test_pronoun_followup_uses_most_recent_resolved_player_context(self):
        """Pronouns after a resolved follow-up should stay anchored to that player."""
        prior_turns = [
            {
                "question": "career home run leaders",
                "answer": {
                    "answer": "All-time career HR leaders",
                    "intent": "stat_query",
                    "sources": [
                        {
                            "type": "duckdb",
                            "label": "Career HR leaders",
                            "rows": [
                                {"name": "Bonds, Barry", "stat_value": 762},
                                {"name": "Aaron, Hank", "stat_value": 755},
                            ],
                        }
                    ],
                },
            },
            {
                "question": "tell me about the second player",
                "answer": {
                    "answer": "Hank Aaron bio",
                    "intent": "player_biography",
                    "metadata": {
                        "context_question": "tell me about Hank Aaron",
                        "context_player_name": "Hank Aaron",
                    },
                    "sources": [{"type": "system", "label": "LLM memory", "rows": []}],
                },
            },
        ]

        with (
            patch("baseball_rag.service.route") as mock_route,
            patch("baseball_rag.service.retrieve_grounded_chunks") as mock_retrieve,
            patch("baseball_rag.service.get_duckdb"),
            patch("baseball_rag.corpus.player_bios.resolve_player_by_name") as mock_resolve,
            patch("baseball_rag.service.init_db"),
            patch("baseball_rag.generation.llm.make_request") as mock_llm,
        ):
            from baseball_rag.generation.llm import LLMResponse
            from baseball_rag.routing import RouteResult
            from baseball_rag.service import answer as structured_answer

            mock_route.return_value = RouteResult(
                intent="player_biography",
                stat=None,
                time_period=None,
                player_name="Hank Aaron",
                raw_question="what teams did Hank Aaron play for?",
            )
            mock_retrieve.return_value = [
                RetrievedChunk(
                    text="Hank Aaron played for Milwaukee, Atlanta, and Milwaukee again.",
                    source="/path/to/aaron.md",
                    title="Hank Aaron",
                    score=0.95,
                )
            ]
            mock_resolve.return_value = PlayerResolution(
                query="Hank Aaron",
                candidates=[PlayerCandidate("aaronha01", "Hank Aaron", "1954-04-13", "1976-10-03")],
            )
            mock_llm.return_value = LLMResponse(
                content="Hank Aaron played for the Braves and Brewers.",
                model="test-model",
                done=True,
            )

            result = structured_answer("what teams did he play for?", conversation=prior_turns)

            mock_route.assert_called_once_with("what teams did Hank Aaron play for?")
            request = mock_retrieve.call_args.args[0]
            assert request.player_name == "Hank Aaron"
            assert result.metadata["context_player_name"] == "Hank Aaron"

    def test_possessive_pronoun_followup_preserves_possessive_player_name(self):
        """Possessive pronouns should rewrite to a possessive player name."""
        prior_turns = [
            {
                "question": "tell me about Hank Aaron",
                "answer": {
                    "answer": "Hank Aaron bio",
                    "intent": "player_biography",
                    "metadata": {"context_player_name": "Hank Aaron"},
                    "sources": [],
                },
            }
        ]

        with (
            patch("baseball_rag.service.route") as mock_route,
            patch("baseball_rag.stat_query.execute_stat_query") as mock_execute_stat_query,
            patch("baseball_rag.stat_query.get_duckdb"),
            patch("baseball_rag.service.init_db"),
        ):
            from baseball_rag.db.queries import StatQueryResult
            from baseball_rag.routing import RouteResult
            from baseball_rag.routing.query_router import TimePeriod, TimePeriodType
            from baseball_rag.service import answer as structured_answer

            mock_route.return_value = RouteResult(
                intent="stat_query",
                stat="HR",
                time_period=TimePeriod(type=TimePeriodType.SINGLE, value=1974),
                player_name="Hank Aaron",
                raw_question="what were Hank Aaron's HRs in 1974?",
            )
            mock_execute_stat_query.return_value = StatQueryResult(
                stat="HR",
                label="Hank Aaron HR in 1974",
                tables=["batting"],
                rows=[{"name": "Aaron, Hank", "team": "ATL", "year": 1974, "stat_value": 20}],
                sql="select 1",
                executed_sql="select 1",
                params=[],
            )

            structured_answer("what were his HRs in 1974?", conversation=prior_turns)

            mock_route.assert_called_once_with("what were Hank Aaron's HRs in 1974?")

    def test_pronoun_followup_preserves_non_reference_ordinal_words(self):
        """Pronoun rewrites should not replace baseball ordinal words as row references."""
        prior_turns = [
            {
                "question": "tell me about Hank Aaron",
                "answer": {
                    "answer": "Hank Aaron bio",
                    "intent": "player_biography",
                    "metadata": {"context_player_name": "Hank Aaron"},
                    "sources": [],
                },
            }
        ]

        with (
            patch("baseball_rag.service.route") as mock_route,
            patch("baseball_rag.service.retrieve_grounded_chunks") as mock_retrieve,
            patch("baseball_rag.service.get_duckdb"),
            patch("baseball_rag.corpus.player_bios.resolve_player_by_name") as mock_resolve,
            patch("baseball_rag.service.init_db"),
            patch("baseball_rag.generation.llm.make_request") as mock_llm,
        ):
            from baseball_rag.generation.llm import LLMResponse
            from baseball_rag.routing import RouteResult
            from baseball_rag.service import answer as structured_answer

            mock_route.return_value = RouteResult(
                intent="player_biography",
                stat=None,
                time_period=None,
                player_name="Hank Aaron",
                raw_question="what was Hank Aaron's first team?",
            )
            mock_retrieve.return_value = [
                RetrievedChunk(
                    text="Hank Aaron debuted with Milwaukee.",
                    source="/path/to/aaron.md",
                    title="Hank Aaron",
                    score=0.95,
                )
            ]
            mock_resolve.return_value = PlayerResolution(
                query="Hank Aaron",
                candidates=[PlayerCandidate("aaronha01", "Hank Aaron", "1954-04-13", "1976-10-03")],
            )
            mock_llm.return_value = LLMResponse(
                content="Hank Aaron debuted with Milwaukee.",
                model="test-model",
                done=True,
            )

            structured_answer("what was his first team?", conversation=prior_turns)

            mock_route.assert_called_once_with("what was Hank Aaron's first team?")

    def test_explicit_ordinal_reference_wins_over_pronoun_context(self):
        """An explicit row reference should not be overridden by the active pronoun player."""
        prior_turns = [
            {
                "question": "career home run leaders",
                "answer": {
                    "answer": "All-time career HR leaders",
                    "intent": "stat_query",
                    "sources": [
                        {
                            "type": "duckdb",
                            "label": "Career HR leaders",
                            "rows": [
                                {"name": "Bonds, Barry", "stat_value": 762},
                                {"name": "Aaron, Hank", "stat_value": 755},
                            ],
                        }
                    ],
                },
            },
            {
                "question": "tell me about the second player",
                "answer": {
                    "answer": "Hank Aaron bio",
                    "intent": "player_biography",
                    "metadata": {"context_player_name": "Hank Aaron"},
                    "sources": [],
                },
            },
        ]

        with (
            patch("baseball_rag.service.route") as mock_route,
            patch("baseball_rag.service.retrieve_grounded_chunks") as mock_retrieve,
            patch("baseball_rag.service.get_duckdb"),
            patch("baseball_rag.corpus.player_bios.resolve_player_by_name") as mock_resolve,
            patch("baseball_rag.service.init_db"),
            patch("baseball_rag.generation.llm.make_request") as mock_llm,
        ):
            from baseball_rag.generation.llm import LLMResponse
            from baseball_rag.routing import RouteResult
            from baseball_rag.service import answer as structured_answer

            mock_route.return_value = RouteResult(
                intent="player_biography",
                stat=None,
                time_period=None,
                player_name="Barry Bonds",
                raw_question="what about Barry Bonds, did he play for the Giants?",
            )
            mock_retrieve.return_value = [
                RetrievedChunk(
                    text="Barry Bonds played for the Giants.",
                    source="/path/to/bonds.md",
                    title="Barry Bonds",
                    score=0.95,
                )
            ]
            mock_resolve.return_value = PlayerResolution(
                query="Barry Bonds",
                candidates=[
                    PlayerCandidate("bondsba01", "Barry Bonds", "1986-05-30", "2007-09-26")
                ],
            )
            mock_llm.return_value = LLMResponse(
                content="Barry Bonds played for the Giants.",
                model="test-model",
                done=True,
            )

            structured_answer(
                "what about the first player, did he play for the Giants?",
                conversation=prior_turns,
            )

            mock_route.assert_called_once_with(
                "what about Barry Bonds, did he play for the Giants?"
            )

    def test_explicit_ordinal_rewrite_only_replaces_row_reference(self):
        """Ordinal row rewriting should not replace other ordinal words in the question."""
        prior_turns = [
            {
                "question": "career home run leaders",
                "answer": {
                    "answer": "All-time career HR leaders",
                    "intent": "stat_query",
                    "sources": [
                        {
                            "type": "duckdb",
                            "label": "Career HR leaders",
                            "rows": [
                                {"name": "Bonds, Barry", "stat_value": 762},
                                {"name": "Aaron, Hank", "stat_value": 755},
                            ],
                        }
                    ],
                },
            }
        ]

        with (
            patch("baseball_rag.service.route") as mock_route,
            patch("baseball_rag.service.retrieve_grounded_chunks") as mock_retrieve,
            patch("baseball_rag.service.get_duckdb"),
            patch("baseball_rag.corpus.player_bios.resolve_player_by_name") as mock_resolve,
            patch("baseball_rag.service.init_db"),
            patch("baseball_rag.generation.llm.make_request") as mock_llm,
        ):
            from baseball_rag.generation.llm import LLMResponse
            from baseball_rag.routing import RouteResult
            from baseball_rag.service import answer as structured_answer

            mock_route.return_value = RouteResult(
                intent="player_biography",
                stat=None,
                time_period=None,
                player_name="Barry Bonds",
                raw_question="what about Barry Bonds, was he first in HR?",
            )
            mock_retrieve.return_value = [
                RetrievedChunk(
                    text="Barry Bonds is the career home run leader.",
                    source="/path/to/bonds.md",
                    title="Barry Bonds",
                    score=0.95,
                )
            ]
            mock_resolve.return_value = PlayerResolution(
                query="Barry Bonds",
                candidates=[
                    PlayerCandidate("bondsba01", "Barry Bonds", "1986-05-30", "2007-09-26")
                ],
            )
            mock_llm.return_value = LLMResponse(
                content="Barry Bonds is the career home run leader.",
                model="test-model",
                done=True,
            )

            structured_answer(
                "what about the first player, was he first in HR?", conversation=prior_turns
            )

            mock_route.assert_called_once_with("what about Barry Bonds, was he first in HR?")

    def test_explicit_ordinal_rewrite_only_replaces_matched_row_reference(self):
        """Mixed ordinal words should leave non-reference ordinals alone."""
        prior_turns = [
            {
                "question": "career home run leaders",
                "answer": {
                    "answer": "All-time career HR leaders",
                    "intent": "stat_query",
                    "sources": [
                        {
                            "type": "duckdb",
                            "label": "Career HR leaders",
                            "rows": [
                                {"name": "Bonds, Barry", "stat_value": 762},
                                {"name": "Aaron, Hank", "stat_value": 755},
                            ],
                        }
                    ],
                },
            }
        ]

        with (
            patch("baseball_rag.service.route") as mock_route,
            patch("baseball_rag.service.retrieve_grounded_chunks") as mock_retrieve,
            patch("baseball_rag.service.get_duckdb"),
            patch("baseball_rag.corpus.player_bios.resolve_player_by_name") as mock_resolve,
            patch("baseball_rag.service.init_db"),
            patch("baseball_rag.generation.llm.make_request") as mock_llm,
        ):
            from baseball_rag.generation.llm import LLMResponse
            from baseball_rag.routing import RouteResult
            from baseball_rag.service import answer as structured_answer

            mock_route.return_value = RouteResult(
                intent="player_biography",
                stat=None,
                time_period=None,
                player_name="Hank Aaron",
                raw_question="was first base relevant for Hank Aaron?",
            )
            mock_retrieve.return_value = [
                RetrievedChunk(
                    text="Hank Aaron was a right fielder.",
                    source="/path/to/aaron.md",
                    title="Hank Aaron",
                    score=0.95,
                )
            ]
            mock_resolve.return_value = PlayerResolution(
                query="Hank Aaron",
                candidates=[PlayerCandidate("aaronha01", "Hank Aaron", "1954-04-13", "1976-10-03")],
            )
            mock_llm.return_value = LLMResponse(
                content="Hank Aaron was a right fielder.",
                model="test-model",
                done=True,
            )

            structured_answer(
                "was first base relevant for the second player?", conversation=prior_turns
            )

            mock_route.assert_called_once_with("was first base relevant for Hank Aaron?")

    def test_ordinal_phrase_with_achievement_clause_is_not_treated_as_row_reference(self):
        """Achievement questions should not use prior rows as conversational references."""
        prior_turns = [
            {
                "question": "career home run leaders",
                "answer": {
                    "answer": "All-time career HR leaders",
                    "intent": "stat_query",
                    "sources": [
                        {
                            "type": "duckdb",
                            "label": "Career HR leaders",
                            "rows": [
                                {"name": "Bonds, Barry", "stat_value": 762},
                                {"name": "Aaron, Hank", "stat_value": 755},
                            ],
                        }
                    ],
                },
            }
        ]

        with (
            patch("baseball_rag.service.route") as mock_route,
            patch("baseball_rag.service.init_db"),
        ):
            from baseball_rag.routing import RouteResult
            from baseball_rag.service import answer as structured_answer

            mock_route.return_value = RouteResult(
                intent="freeform_query",
                stat=None,
                time_period=None,
                player_name=None,
                raw_question="who was the second player ever to reach 3000 hits?",
            )

            structured_answer(
                "who was the second player ever to reach 3000 hits?",
                conversation=prior_turns,
            )

            mock_route.assert_called_once_with("who was the second player ever to reach 3000 hits?")

    def test_bare_ordinal_achievement_clause_is_not_treated_as_row_reference(self):
        """Standalone questions like 'second ever to...' should not use prior rows."""
        prior_turns = [
            {
                "question": "career home run leaders",
                "answer": {
                    "answer": "All-time career HR leaders",
                    "intent": "stat_query",
                    "sources": [
                        {
                            "type": "duckdb",
                            "label": "Career HR leaders",
                            "rows": [
                                {"name": "Bonds, Barry", "stat_value": 762},
                                {"name": "Aaron, Hank", "stat_value": 755},
                            ],
                        }
                    ],
                },
            }
        ]

        with (
            patch("baseball_rag.service.route") as mock_route,
            patch("baseball_rag.service.init_db"),
        ):
            from baseball_rag.routing import RouteResult
            from baseball_rag.service import answer as structured_answer

            mock_route.return_value = RouteResult(
                intent="freeform_query",
                stat=None,
                time_period=None,
                player_name=None,
                raw_question="who was the second ever to reach 3000 hits?",
            )

            structured_answer(
                "who was the second ever to reach 3000 hits?", conversation=prior_turns
            )

            mock_route.assert_called_once_with("who was the second ever to reach 3000 hits?")

    def test_ordinal_player_with_clause_is_not_treated_as_row_reference(self):
        """Achievement phrasing with 'with' should not use prior rows."""
        prior_turns = [
            {
                "question": "career home run leaders",
                "answer": {
                    "answer": "All-time career HR leaders",
                    "intent": "stat_query",
                    "sources": [
                        {
                            "type": "duckdb",
                            "label": "Career HR leaders",
                            "rows": [
                                {"name": "Bonds, Barry", "stat_value": 762},
                                {"name": "Aaron, Hank", "stat_value": 755},
                            ],
                        }
                    ],
                },
            }
        ]

        with (
            patch("baseball_rag.service.route") as mock_route,
            patch("baseball_rag.service.init_db"),
        ):
            from baseball_rag.routing import RouteResult
            from baseball_rag.service import answer as structured_answer

            mock_route.return_value = RouteResult(
                intent="freeform_query",
                stat=None,
                time_period=None,
                player_name=None,
                raw_question="who was the second player with 3000 hits?",
            )

            structured_answer("who was the second player with 3000 hits?", conversation=prior_turns)

            mock_route.assert_called_once_with("who was the second player with 3000 hits?")

    def test_ordinal_followup_with_non_achievement_clause_still_uses_prior_rows(self):
        """Follow-ups like 'second player with Atlanta' should still resolve prior rows."""
        prior_turns = [
            {
                "question": "career home run leaders",
                "answer": {
                    "answer": "All-time career HR leaders",
                    "intent": "stat_query",
                    "sources": [
                        {
                            "type": "duckdb",
                            "label": "Career HR leaders",
                            "rows": [
                                {"name": "Bonds, Barry", "stat_value": 762},
                                {"name": "Aaron, Hank", "stat_value": 755},
                            ],
                        }
                    ],
                },
            }
        ]

        with (
            patch("baseball_rag.service.route") as mock_route,
            patch("baseball_rag.service.retrieve_grounded_chunks") as mock_retrieve,
            patch("baseball_rag.service.get_duckdb"),
            patch("baseball_rag.corpus.player_bios.resolve_player_by_name") as mock_resolve,
            patch("baseball_rag.service.init_db"),
            patch("baseball_rag.generation.llm.make_request") as mock_llm,
        ):
            from baseball_rag.generation.llm import LLMResponse
            from baseball_rag.routing import RouteResult
            from baseball_rag.service import answer as structured_answer

            mock_route.return_value = RouteResult(
                intent="player_biography",
                stat=None,
                time_period=None,
                player_name="Hank Aaron",
                raw_question="what about Hank Aaron with Atlanta?",
            )
            mock_retrieve.return_value = [
                RetrievedChunk(
                    text="Hank Aaron played for Atlanta.",
                    source="/path/to/aaron.md",
                    title="Hank Aaron",
                    score=0.95,
                )
            ]
            mock_resolve.return_value = PlayerResolution(
                query="Hank Aaron",
                candidates=[PlayerCandidate("aaronha01", "Hank Aaron", "1954-04-13", "1976-10-03")],
            )
            mock_llm.return_value = LLMResponse(
                content="Hank Aaron played for Atlanta.",
                model="test-model",
                done=True,
            )

            structured_answer(
                "what about the second player with Atlanta?", conversation=prior_turns
            )

            mock_route.assert_called_once_with("what about Hank Aaron with Atlanta?")

    def test_ordinal_followup_with_action_to_clause_still_uses_prior_rows(self):
        """Follow-ups like 'second player do to win MVP' should still resolve prior rows."""
        prior_turns = [
            {
                "question": "career home run leaders",
                "answer": {
                    "answer": "All-time career HR leaders",
                    "intent": "stat_query",
                    "sources": [
                        {
                            "type": "duckdb",
                            "label": "Career HR leaders",
                            "rows": [
                                {"name": "Bonds, Barry", "stat_value": 762},
                                {"name": "Aaron, Hank", "stat_value": 755},
                            ],
                        }
                    ],
                },
            }
        ]

        with (
            patch("baseball_rag.service.route") as mock_route,
            patch("baseball_rag.service.retrieve_grounded_chunks") as mock_retrieve,
            patch("baseball_rag.service.get_duckdb"),
            patch("baseball_rag.corpus.player_bios.resolve_player_by_name") as mock_resolve,
            patch("baseball_rag.service.init_db"),
            patch("baseball_rag.generation.llm.make_request") as mock_llm,
        ):
            from baseball_rag.generation.llm import LLMResponse
            from baseball_rag.routing import RouteResult
            from baseball_rag.service import answer as structured_answer

            mock_route.return_value = RouteResult(
                intent="player_biography",
                stat=None,
                time_period=None,
                player_name="Hank Aaron",
                raw_question="what did Hank Aaron do to win MVP?",
            )
            mock_retrieve.return_value = [
                RetrievedChunk(
                    text="Hank Aaron won the 1957 NL MVP.",
                    source="/path/to/aaron.md",
                    title="Hank Aaron",
                    score=0.95,
                )
            ]
            mock_resolve.return_value = PlayerResolution(
                query="Hank Aaron",
                candidates=[PlayerCandidate("aaronha01", "Hank Aaron", "1954-04-13", "1976-10-03")],
            )
            mock_llm.return_value = LLMResponse(
                content="Hank Aaron won the 1957 NL MVP.",
                model="test-model",
                done=True,
            )

            structured_answer("what did the second player do to win MVP?", conversation=prior_turns)

            mock_route.assert_called_once_with("what did Hank Aaron do to win MVP?")

    def test_ordinal_followup_indexes_player_rows_not_all_source_rows(self):
        """Ordinal player references should ignore non-player evidence rows in the same source."""
        prior_turns = [
            {
                "question": "career home run leaders",
                "answer": {
                    "answer": "All-time career HR leaders",
                    "intent": "stat_query",
                    "sources": [
                        {
                            "type": "duckdb",
                            "label": "Career HR leaders",
                            "rows": [
                                {"note": "includes all leagues"},
                                {"name": "Bonds, Barry", "stat_value": 762},
                                {"name": "Aaron, Hank", "stat_value": 755},
                            ],
                        }
                    ],
                },
            }
        ]

        with (
            patch("baseball_rag.service.route") as mock_route,
            patch("baseball_rag.service.retrieve_grounded_chunks") as mock_retrieve,
            patch("baseball_rag.service.get_duckdb"),
            patch("baseball_rag.corpus.player_bios.resolve_player_by_name") as mock_resolve,
            patch("baseball_rag.service.init_db"),
            patch("baseball_rag.generation.llm.make_request") as mock_llm,
        ):
            from baseball_rag.generation.llm import LLMResponse
            from baseball_rag.routing import RouteResult
            from baseball_rag.service import answer as structured_answer

            mock_route.return_value = RouteResult(
                intent="player_biography",
                stat=None,
                time_period=None,
                player_name="Barry Bonds",
                raw_question="tell me about Barry Bonds",
            )
            mock_retrieve.return_value = [
                RetrievedChunk(
                    text="Barry Bonds was an outfielder.",
                    source="/path/to/bonds.md",
                    title="Barry Bonds",
                    score=0.95,
                )
            ]
            mock_resolve.return_value = PlayerResolution(
                query="Barry Bonds",
                candidates=[
                    PlayerCandidate("bondsba01", "Barry Bonds", "1986-05-30", "2007-09-26")
                ],
            )
            mock_llm.return_value = LLMResponse(
                content="Barry Bonds was an outfielder.",
                model="test-model",
                done=True,
            )

            structured_answer("tell me about the first player", conversation=prior_turns)

            mock_route.assert_called_once_with("tell me about Barry Bonds")

    def test_ordinal_followup_does_not_fall_back_past_latest_player_table(self):
        """If the latest player table lacks that ordinal, older tables should not win."""
        prior_turns = [
            {
                "question": "career home run leaders",
                "answer": {
                    "answer": "All-time career HR leaders",
                    "intent": "stat_query",
                    "sources": [
                        {
                            "type": "duckdb",
                            "label": "Career HR leaders",
                            "rows": [
                                {"name": "Bonds, Barry", "stat_value": 762},
                                {"name": "Aaron, Hank", "stat_value": 755},
                            ],
                        }
                    ],
                },
            },
            {
                "question": "what were Hank Aaron's HRs in 1974?",
                "answer": {
                    "answer": "Aaron, Hank (ATL) (1974): 20 HR",
                    "intent": "stat_query",
                    "sources": [
                        {
                            "type": "duckdb",
                            "label": "Hank Aaron HR in 1974",
                            "rows": [{"name": "Aaron, Hank", "stat_value": 20}],
                        }
                    ],
                },
            },
        ]

        with (
            patch("baseball_rag.service.route") as mock_route,
            patch("baseball_rag.service.init_db"),
        ):
            from baseball_rag.routing import RouteResult
            from baseball_rag.service import answer as structured_answer

            mock_route.return_value = RouteResult(
                intent="player_biography",
                stat=None,
                time_period=None,
                player_name=None,
                raw_question="tell me about the second player",
            )

            structured_answer("tell me about the second player", conversation=prior_turns)

            mock_route.assert_called_once_with("tell me about the second player")

    def test_direct_player_bio_anchors_next_pronoun_followup(self):
        """A direct player biography turn should become the active pronoun referent."""
        with (
            patch("baseball_rag.service.route") as mock_route,
            patch("baseball_rag.service.retrieve_grounded_chunks") as mock_retrieve,
            patch("baseball_rag.service.get_duckdb"),
            patch("baseball_rag.corpus.player_bios.resolve_player_by_name") as mock_resolve,
            patch("baseball_rag.service.init_db"),
            patch("baseball_rag.generation.llm.make_request") as mock_llm,
        ):
            from baseball_rag.generation.llm import LLMResponse
            from baseball_rag.routing import RouteResult
            from baseball_rag.service import answer as structured_answer

            mock_route.return_value = RouteResult(
                intent="player_biography",
                stat=None,
                time_period=None,
                player_name="Hank Aaron",
                raw_question="tell me about Hank Aaron",
            )
            mock_retrieve.return_value = [
                RetrievedChunk(
                    text="Hank Aaron was a Hall of Fame right fielder.",
                    source="/path/to/aaron.md",
                    title="Hank Aaron",
                    score=0.95,
                )
            ]
            mock_resolve.return_value = PlayerResolution(
                query="Hank Aaron",
                candidates=[PlayerCandidate("aaronha01", "Hank Aaron", "1954-04-13", "1976-10-03")],
            )
            mock_llm.return_value = LLMResponse(
                content="Hank Aaron bio.",
                model="test-model",
                done=True,
            )

            first = structured_answer("tell me about Hank Aaron")

            assert first.metadata["context_player_name"] == "Hank Aaron"

        prior_turns = [{"question": "tell me about Hank Aaron", "answer": first.to_dict()}]
        with (
            patch("baseball_rag.service.route") as mock_route,
            patch("baseball_rag.service.retrieve_grounded_chunks") as mock_retrieve,
            patch("baseball_rag.service.get_duckdb"),
            patch("baseball_rag.corpus.player_bios.resolve_player_by_name") as mock_resolve,
            patch("baseball_rag.service.init_db"),
            patch("baseball_rag.generation.llm.make_request") as mock_llm,
        ):
            from baseball_rag.generation.llm import LLMResponse
            from baseball_rag.routing import RouteResult
            from baseball_rag.service import answer as structured_answer

            mock_route.return_value = RouteResult(
                intent="player_biography",
                stat=None,
                time_period=None,
                player_name="Hank Aaron",
                raw_question="what teams did Hank Aaron play for?",
            )
            mock_retrieve.return_value = [
                RetrievedChunk(
                    text="Hank Aaron played for the Braves and Brewers.",
                    source="/path/to/aaron.md",
                    title="Hank Aaron",
                    score=0.95,
                )
            ]
            mock_resolve.return_value = PlayerResolution(
                query="Hank Aaron",
                candidates=[PlayerCandidate("aaronha01", "Hank Aaron", "1954-04-13", "1976-10-03")],
            )
            mock_llm.return_value = LLMResponse(
                content="Hank Aaron played for the Braves and Brewers.",
                model="test-model",
                done=True,
            )

            structured_answer("what teams did he play for?", conversation=prior_turns)

            mock_route.assert_called_once_with("what teams did Hank Aaron play for?")

    def test_ordinal_followup_skips_non_player_rows_from_intervening_turns(self):
        """Ordinal references should fall back past evidence rows that are not players."""
        prior_turns = [
            {
                "question": "career home run leaders",
                "answer": {
                    "answer": "All-time career HR leaders",
                    "intent": "stat_query",
                    "sources": [
                        {
                            "type": "duckdb",
                            "label": "Career HR leaders",
                            "rows": [
                                {"name": "Bonds, Barry", "stat_value": 762},
                                {"name": "Aaron, Hank", "stat_value": 755},
                            ],
                        }
                    ],
                },
            },
            {
                "question": "tell me about the second player",
                "answer": {
                    "answer": "Hank Aaron bio",
                    "intent": "player_biography",
                    "metadata": {"context_player_name": "Hank Aaron"},
                    "sources": [
                        {
                            "type": "chroma",
                            "label": "Hank Aaron",
                            "rows": [{"text": "Hank Aaron was a Hall of Famer."}],
                        }
                    ],
                },
            },
        ]

        with (
            patch("baseball_rag.service.route") as mock_route,
            patch("baseball_rag.service.retrieve_grounded_chunks") as mock_retrieve,
            patch("baseball_rag.service.get_duckdb"),
            patch("baseball_rag.corpus.player_bios.resolve_player_by_name") as mock_resolve,
            patch("baseball_rag.service.init_db"),
            patch("baseball_rag.generation.llm.make_request") as mock_llm,
        ):
            from baseball_rag.generation.llm import LLMResponse
            from baseball_rag.routing import RouteResult
            from baseball_rag.service import answer as structured_answer

            mock_route.return_value = RouteResult(
                intent="player_biography",
                stat=None,
                time_period=None,
                player_name="Barry Bonds",
                raw_question="tell me about Barry Bonds",
            )
            mock_retrieve.return_value = [
                RetrievedChunk(
                    text="Barry Bonds was an outfielder.",
                    source="/path/to/bonds.md",
                    title="Barry Bonds",
                    score=0.95,
                )
            ]
            mock_resolve.return_value = PlayerResolution(
                query="Barry Bonds",
                candidates=[
                    PlayerCandidate("bondsba01", "Barry Bonds", "1986-05-30", "2007-09-26")
                ],
            )
            mock_llm.return_value = LLMResponse(
                content="Barry Bonds was an outfielder.",
                model="test-model",
                done=True,
            )

            structured_answer("tell me about the first player", conversation=prior_turns)

            mock_route.assert_called_once_with("tell me about Barry Bonds")

    def test_bare_ordinal_followup_rewrites_to_player_name(self):
        """Bare ordinal references should not append an awkward fallback phrase."""
        prior_turns = [
            {
                "question": "career home run leaders",
                "answer": {
                    "answer": "All-time career HR leaders",
                    "intent": "stat_query",
                    "sources": [
                        {
                            "type": "duckdb",
                            "label": "Career HR leaders",
                            "rows": [
                                {"name": "Bonds, Barry", "stat_value": 762},
                                {"name": "Aaron, Hank", "stat_value": 755},
                            ],
                        }
                    ],
                },
            }
        ]

        with (
            patch("baseball_rag.service.route") as mock_route,
            patch("baseball_rag.service.retrieve_grounded_chunks") as mock_retrieve,
            patch("baseball_rag.service.get_duckdb"),
            patch("baseball_rag.corpus.player_bios.resolve_player_by_name") as mock_resolve,
            patch("baseball_rag.service.init_db"),
            patch("baseball_rag.generation.llm.make_request") as mock_llm,
        ):
            from baseball_rag.generation.llm import LLMResponse
            from baseball_rag.routing import RouteResult
            from baseball_rag.service import answer as structured_answer

            mock_route.return_value = RouteResult(
                intent="player_biography",
                stat=None,
                time_period=None,
                player_name="Barry Bonds",
                raw_question="tell me about Barry Bonds",
            )
            mock_retrieve.return_value = [
                RetrievedChunk(
                    text="Barry Bonds was an outfielder.",
                    source="/path/to/bonds.md",
                    title="Barry Bonds",
                    score=0.95,
                )
            ]
            mock_resolve.return_value = PlayerResolution(
                query="Barry Bonds",
                candidates=[
                    PlayerCandidate("bondsba01", "Barry Bonds", "1986-05-30", "2007-09-26")
                ],
            )
            mock_llm.return_value = LLMResponse(
                content="Barry Bonds was an outfielder.",
                model="test-model",
                done=True,
            )

            structured_answer("tell me about first player", conversation=prior_turns)

            mock_route.assert_called_once_with("tell me about Barry Bonds")

    def test_ordinal_only_followup_rewrites_to_player_name(self):
        """Ordinal-only references like 'the first' should resolve to prior rows."""
        prior_turns = [
            {
                "question": "career home run leaders",
                "answer": {
                    "answer": "All-time career HR leaders",
                    "intent": "stat_query",
                    "sources": [
                        {
                            "type": "duckdb",
                            "label": "Career HR leaders",
                            "rows": [
                                {"name": "Bonds, Barry", "stat_value": 762},
                                {"name": "Aaron, Hank", "stat_value": 755},
                            ],
                        }
                    ],
                },
            }
        ]

        with (
            patch("baseball_rag.service.route") as mock_route,
            patch("baseball_rag.service.retrieve_grounded_chunks") as mock_retrieve,
            patch("baseball_rag.service.get_duckdb"),
            patch("baseball_rag.corpus.player_bios.resolve_player_by_name") as mock_resolve,
            patch("baseball_rag.service.init_db"),
            patch("baseball_rag.generation.llm.make_request") as mock_llm,
        ):
            from baseball_rag.generation.llm import LLMResponse
            from baseball_rag.routing import RouteResult
            from baseball_rag.service import answer as structured_answer

            mock_route.return_value = RouteResult(
                intent="player_biography",
                stat=None,
                time_period=None,
                player_name="Barry Bonds",
                raw_question="tell me about Barry Bonds",
            )
            mock_retrieve.return_value = [
                RetrievedChunk(
                    text="Barry Bonds was an outfielder.",
                    source="/path/to/bonds.md",
                    title="Barry Bonds",
                    score=0.95,
                )
            ]
            mock_resolve.return_value = PlayerResolution(
                query="Barry Bonds",
                candidates=[
                    PlayerCandidate("bondsba01", "Barry Bonds", "1986-05-30", "2007-09-26")
                ],
            )
            mock_llm.return_value = LLMResponse(
                content="Barry Bonds was an outfielder.",
                model="test-model",
                done=True,
            )

            structured_answer("tell me about the first", conversation=prior_turns)

            mock_route.assert_called_once_with("tell me about Barry Bonds")
