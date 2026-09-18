"""Public source credits shared by answers, evidence and downloadable results."""

RETROSHEET_CREDIT = (
    "The information used here was obtained free of charge from and is copyrighted by "
    'Retrosheet. Interested parties may contact Retrosheet at "www.retrosheet.org".'
)
RETROSHEET_URL = "https://www.retrosheet.org/"
LAHMAN_CREDIT = "Historical statistics: Sean Lahman / SABR, via NeuML. CC BY-SA 3.0."


def source_credit(provider: str) -> dict[str, str]:
    """Use required application-owned credit, never model-authored attribution."""
    credits = {
        "retrosheet": (RETROSHEET_CREDIT, RETROSHEET_URL),
        "lahman": (LAHMAN_CREDIT, "https://sabr.org/lahman-database/"),
        "thesportsdb": ("Fixture information from TheSportsDB.", "https://www.thesportsdb.com/"),
        "wikidata": ("Structured facts from Wikidata, CC0.", "https://www.wikidata.org/"),
        "mlb_glossary": (
            "Stat definitions paraphrased from the MLB glossary.",
            "https://www.mlb.com/glossary",
        ),
        "mlb_stats": (
            "Current baseball records from MLB. Probable pitchers and schedules may change.",
            "https://www.mlb.com/",
        ),
        "groundball": (
            "Ground Ball stat-definition reference.",
            "https://github.com/DiscoStew6082/groundball",
        ),
    }
    text, url = credits[provider]
    return {"provider": provider, "text": text, "url": url}
