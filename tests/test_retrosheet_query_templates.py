"""Contract tests for the separately governed Retrosheet query templates."""

import csv
import json

import pytest

from baseball_rag.db.duckdb_schema import DATA_DIR
from baseball_rag.db.generate_retrosheet_team_reference import (
    REFERENCE_PATH,
    render_retrosheet_team_reference,
)
from baseball_rag.db.retrosheet_query_templates import match_retrosheet_template
from baseball_rag.retrosheet_query import execute_retrosheet_query


@pytest.mark.parametrize(
    ("question", "template_id"),
    [
        ("what is the longest stolen base streak in MLB history", "batting_stat_streak"),
        ("show Rickey Henderson games with at least 2 stolen bases", "player_batting_game_log"),
        (
            "show Nolan Ryan games with at least 10 strikeouts",
            "pitcher_daily_strikeout_game_log",
        ),
        (
            "when did Nolan Ryan strike out the side in 1973",
            "pitcher_strikeout_side_game_log",
        ),
        (
            "how many times did Nolan Ryan strike out the side in his career",
            "pitcher_strikeout_side_count",
        ),
        (
            "which pitchers have the most strike out the side games in their careers",
            "pitcher_strikeout_side_leaders",
        ),
    ],
)
def test_matcher_exposes_only_the_six_retrosheet_template_families(question, template_id):
    matched = match_retrosheet_template(question)

    assert matched is not None
    assert matched.template_id == template_id
    assert matched.sql.lstrip().split(None, 1)[0].upper() in {"SELECT", "WITH"}
    assert matched.source_detail.startswith("Retrosheet")


def test_matcher_does_not_accept_primary_lahman_questions():
    assert match_retrosheet_template("who had the most RBIs in 1962") is None


def test_templates_use_the_versioned_team_reference_instead_of_the_legacy_team_map():
    questions = (
        "what is the longest stolen base streak in MLB history",
        "show Rickey Henderson games with at least 2 stolen bases",
        "when did Nolan Ryan strike out the side in 1973",
        "how many times did Nolan Ryan strike out the side in his career",
    )

    sql = "\n".join(match_retrosheet_template(question).sql for question in questions)  # type: ignore[union-attr]

    assert "retrosheet_team_reference" in sql
    assert "JOIN teams" not in sql


@pytest.mark.parametrize(
    "question",
    [
        "show Nolan Ryan strikeout game log in 1973",
        "show Rickey Henderson stolen base game log in 1982",
    ],
)
def test_show_game_log_prefix_is_not_captured_as_part_of_the_player_name(question):
    result = execute_retrosheet_query(question)

    assert result["kind"] == "rows"
    assert result["rows"]
    assert result["evidence"]["bound_values"][0] in {"nolan ryan", "rickey henderson"}


def test_opponent_nickname_resolves_through_season_aware_retrosheet_identity():
    result = execute_retrosheet_query(
        "show Jeremy Bonderman strike out the side games against the Angels in 2005"
    )

    assert result["kind"] == "rows"
    assert len(result["rows"]) == 2
    assert {row["opponent_team"] for row in result["rows"]} == {"Los Angeles Angels of Anaheim"}


def test_retrosheet_team_reference_is_generated_from_upstream_identity_columns(tmp_path):
    teams = tmp_path / "Teams.csv"
    retrosheet_teams = tmp_path / "retrosheet-teams.html"
    teams.write_text(
        "yearID,teamID,name,teamIDretro\n"
        "2005,LAA,Los Angeles Angels of Anaheim,ANA\n"
        "1939,TC,Toledo Crawfords,TLC\n"
        "1939,TC2,Toledo Crawfords,TLC\n",
        encoding="utf-8",
    )
    retrosheet_teams.write_text(
        "<pre>\n"
        "ANA\tAnaheim Angels\t19970402\t20250928\n"
        "KCR\tKansas City Royals\t19431017\t19481107\n"
        "TLC\tToledo Crawfords\t19390513\t19390821\n"
        "</pre>\n",
        encoding="utf-8",
    )

    csv_bytes, manifest_bytes = render_retrosheet_team_reference(teams, retrosheet_teams)

    lines = csv_bytes.decode().splitlines()
    assert lines[0] == "yearID,retrosheetTeamID,name"
    assert "1939,TLC,Toledo Crawfords" in lines
    assert "1948,KCR,Kansas City Royals" in lines
    assert "2005,ANA,Los Angeles Angels of Anaheim" in lines
    manifest = json.loads(manifest_bytes)
    assert manifest["reference_version"] == "retrosheet-season-aware-v1"
    assert manifest["rows"] == 36


def test_retrosheet_team_reference_covers_every_governed_event_team_identity():
    with REFERENCE_PATH.open(newline="", encoding="utf-8") as source:
        reference = {
            (int(row["yearID"]), row["retrosheetTeamID"]) for row in csv.DictReader(source)
        }
    projection_path = (
        DATA_DIR / "secondary_sources" / "retrosheet" / "pitcher_strikeout_side_events.csv"
    )
    with projection_path.open(newline="", encoding="utf-8") as source:
        missing = {
            (int(row["year"]), team_id)
            for row in csv.DictReader(source)
            for team_id in (row["pitcher_team_id"], row["opponent_team_id"])
            if (int(row["year"]), team_id) not in reference
        }

    assert missing == set()
