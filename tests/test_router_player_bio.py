"""Tests for player_biography routing intent."""

from baseball_rag.routing import route


class TestPlayerBioRouting:
    def test_who_was_wally_pipp(self):
        """'who was Wally Pipp' → player_biography."""
        result = route("who was Wally Pipp")
        assert result.intent == "player_biography"
        assert result.player_name == "Wally Pipp"

    def test_what_teams_did_he_play_for(self):
        """'what teams did he play for' → player_biography (when player context exists)."""
        # This tests that biography questions route correctly
        # Note: without prior context, this might not extract player_name in fallback
        result = route("what teams did he play for")
        assert result.intent == "player_biography"

    def test_tell_me_about_player(self):
        """'tell me about this player' → player_biography."""
        result = route("tell me about this player")
        assert result.intent == "player_biography"

    def test_stat_query_not_biography(self):
        """'how many HRs did Aaron Judge have' → stat_query, not biography."""
        result = route("how many HRs did Aaron Judge have")
        assert result.intent == "stat_query"
        assert result.player_name == "Aaron Judge"
        # Should NOT be player_biography even though a name is present

    def test_rbi_count_not_biography(self):
        """'how many RBIs does Shohei Ohtani have' → stat_query."""
        result = route("how many RBIs does Shohei Ohtani have")
        assert result.intent == "stat_query"
        assert result.player_name == "Shohei Ohtani"

    def test_biography_extracts_player_name(self):
        """player_biography should extract player_name when present."""
        result = route("who was Rogers Hornsby")
        assert result.intent == "player_biography"
        assert result.player_name == "Rogers Hornsby"

    def test_pasted_biography_verification_request_routes_to_player_bio(self):
        """A supplied biography asking for claim verification should resolve the player."""
        result = route(
            "Alex Rodriguez recorded 696 HR, 2,086 RBI, 3,115 H, and 301 SB. "
            "A three-time American League MVP. Which stat claims can be verified against DuckDB?"
        )

        assert result.intent == "player_biography"
        assert result.player_name == "Alex Rodriguez"

    def test_claim_verification_request_can_name_player_after_prompt_prefix(self):
        result = route("Can DuckDB verify the claim that Babe Ruth hit 714 HR?")

        assert result.intent == "player_biography"
        assert result.player_name == "Babe Ruth"

    def test_claim_verification_request_can_put_biography_after_question(self):
        result = route("Which stat claims can be verified against DuckDB? Babe Ruth hit 714 HR.")

        assert result.intent == "player_biography"
        assert result.player_name == "Babe Ruth"

    def test_general_explanation_when_no_player_name(self):
        """'what is baseball' → general_explanation, not player_biography."""
        result = route("what is a balk")
        assert result.intent == "general_explanation"
