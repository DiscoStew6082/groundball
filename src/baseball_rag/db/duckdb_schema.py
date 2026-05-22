"""DuckDB CSV schema setup — zero-ingestion queries over NeuML/baseballdata CSVs."""

import csv
import threading
from pathlib import Path

import duckdb

# Module-level singleton connection with double-checked locking for thread safety.
_cached_conn: duckdb.DuckDBPyConnection | None = None
_lock = threading.Lock()

# Project root: go up 4 levels — lahman.py -> db/ -> baseball_rag/ -> src/ -> repo/
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "data"
RETROSHEET_DATA_SUBDIR = Path("secondary_sources") / "retrosheet"
RETROSHEET_STAT_TABLES = {
    "retrosheet_batting": "batting.csv",
    "retrosheet_pitching": "pitching.csv",
    "retrosheet_fielding": "fielding.csv",
}
RETROSHEET_BIOFILE = ("retrosheet_biofile", "biofile0.csv")

# Try to load Teams.csv at module init; fall back to {} if not present.
_TEAMS_CSV_PATH = DATA_DIR / "Teams.csv"
try:
    _TEAM_MAP: dict[str, str] = {}
    with open(_TEAMS_CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            team_id = row.get("teamID") or row.get("TeamCode") or row.get("ID")
            name = (
                row.get("name")
                or row.get("Name")
                or row.get("teamName")
                or f"{row.get('city', '')} {row.get('nickname', '')}".strip()
            )
            if team_id and name:
                _TEAM_MAP[team_id] = name
except Exception:
    _TEAM_MAP = {}

# Fallback comprehensive MLB team map (covers all teams in the NeuML/baseballdata batting data)
if not _TEAM_MAP:
    _TEAM_MAP = {
        # Active MLB teams (2020s)
        "ARI": "Arizona Diamondbacks",
        "ATL": "Atlanta Braves",
        "BAL": "Baltimore Orioles",
        "BOS": "Boston Red Sox",
        "CHA": "Chicago White Sox",
        "CHN": "Chicago Cubs",
        "CIN": "Cincinnati Reds",
        "CLE": "Cleveland Guardians",
        "COL": "Colorado Rockies",
        "DET": "Detroit Tigers",
        "HOU": "Houston Astros",
        "KCA": "Kansas City Royals",
        "LAA": "Los Angeles Angels",
        "LAN": "Los Angeles Dodgers",
        "MIA": "Miami Marlins",
        "MIL": "Milwaukee Brewers",
        "MIN": "Minnesota Twins",
        "NYA": "New York Yankees",
        "NYN": "New York Mets",
        "OAK": "Oakland Athletics",
        "PHI": "Philadelphia Phillies",
        "PIT": "Pittsburgh Pirates",
        "SDN": "San Diego Padres",
        "SEA": "Seattle Mariners",
        "SFN": "San Francisco Giants",
        "SLN": "St. Louis Cardinals",
        "TBA": "Tampa Bay Rays",
        "TEX": "Texas Rangers",
        "TOR": "Toronto Blue Jays",
        "WAS": "Washington Nationals",
        # Historical team names
        "ANA": "Anaheim Angels",
        "BRO": "Brooklyn Dodgers",
        "BSN": "Boston Braves",
        "CAL": "California Angels",
        "FLO": "Florida Marlins",
        "MON": "Montreal Expos",
        "NYY": "New York Yankees",  # alias
        "PHA": "Philadelphia Athletics",
        "MLA": "Milwaukee Braves",
        "ML4": "Milwaukee Brewers (1982)",
        "WS1": "Washington Senators (1901-1960)",
        "WS2": "Washington Senators (1961-1971)",
        # Negro Leagues & early teams
        "AB": "Abbott",  # ABB? placeholder for unknown/early
        "AC": "All Cubans",
        "ATH": "Athletics (Philadelphia, early)",
        "BLU": "Baltimore Orioles (19th c.)",
        "BR1": "Brooklyn (alt.",
        "BR2": "Brooklyn (alt 2)",
        "BR3": "Brooklyn (alt 3)",
        "BR4": "Brooklyn (alt 4)",
        "CBG": "Cincinnati (old)",
        "CH1": "Chicago (AA/NL early)",
        "CHN": "Chicago Cubs",  # noqa: F601 — also in active teams above
        "CL1": "Cleveland (early AL)",
        "CL2": "Cleveland (early NL)",
        "CL3": "Cleveland (alt 3)",
        "CL4": "Cleveland (alt 4)",
        "CL5": "Cleveland (alt 5)",
        "CL6": "Cleveland (alt 6)",
        "CN1": "Chicago (NL early)",
        "CN2": "Chicago (NL alt)",
        "CSW": "Chicago White Stockings",
        "DTN": "Detroit (early NL)",
        "LS1": "Louisville (early)",
        "LS2": "Louisville (alt 2)",
        "ML1": "Milwaukee (Braves/Brewers)",
        "NE": "New England",
        "NEW": "Newark (Negro league)",
        "NY1": "New York Giants (NL)",
        "NY2": "New York (AL early)",
        "NY3": "New York (alt 3)",
        "NYC": "New York (city teams)",
        "PH1": "Philadelphia (early NL)",
        "PH2": "Philadelphia (alt 2)",
        # PHA: Philadelphia Athletics — already mapped at line 75
        "PHP": "Philadelphia Phillies",
        # PIT: Pittsburgh Pirates — already mapped above
        "PRO": "Providence Grays",
        # SDN: San Diego Padres — already mapped above
        "SL1": "St. Louis (early NL)",
        "SL2": "St. Louis Browns",
        "SL4": "St. Louis (alt 4)",
        "SL5": "St. Louis (alt 5)",
        "SLA": "St. Louis Browns",
        "SLF": "St. Louis (fall league?)",
        # SLN: St. Louis Cardinals — already mapped at line 62
        "WS3": "Washington Senators (1900s)",
    }

# Alias the map for backward compat
TEAM_MAP = _TEAM_MAP


def get_duckdb() -> duckdb.DuckDBPyConnection:
    """Return a shared in-memory DuckDB connection, creating it on first call.

    Thread-safe singleton using double-checked locking. The connection is
    reused across all calls — callers must NOT close it.
    """
    global _cached_conn

    if _cached_conn is not None:
        try:
            _cached_conn.execute("SELECT 1")
            return _cached_conn
        except Exception:
            # Connection was closed; discard it and fall through to recreate.
            _cached_conn = None

    with _lock:
        # Check again after acquiring the lock (double-checked locking pattern).
        if _cached_conn is None:
            conn = duckdb.connect(database=":memory:", read_only=False)

            # Register CSVs via read_csv_auto
            batting_path = str(DATA_DIR / "Batting.csv")
            fielding_path = str(DATA_DIR / "Fielding.csv")
            people_path = str(DATA_DIR / "People.csv")
            pitching_path = str(DATA_DIR / "Pitching.csv")

            conn.execute(f"CREATE TABLE batting AS SELECT * FROM read_csv_auto('{batting_path}')")
            conn.execute(f"CREATE TABLE fielding AS SELECT * FROM read_csv_auto('{fielding_path}')")
            conn.execute(f"CREATE TABLE people AS SELECT * FROM read_csv_auto('{people_path}')")
            conn.execute(f"CREATE TABLE pitching AS SELECT * FROM read_csv_auto('{pitching_path}')")
            _load_optional_retrosheet_tables(conn, DATA_DIR)

            # Create a teams table from _TEAM_MAP so queries can JOIN on it
            teams_rows = ", ".join(f"('{k}', '{v}')" for k, v in _TEAM_MAP.items())
            conn.execute("CREATE TABLE teams (teamID TEXT, name TEXT)")
            if teams_rows:
                conn.execute(f"INSERT INTO teams VALUES {teams_rows}")

            # Assign to module-level singleton (global declared at function top).
            _cached_conn = conn

        return _cached_conn


def init_db() -> None:
    """No-op — kept for backward compatibility with code that calls it."""
    pass


def _load_optional_retrosheet_tables(conn: duckdb.DuckDBPyConnection, data_dir: Path) -> None:
    retrosheet_dir = data_dir / RETROSHEET_DATA_SUBDIR
    if not retrosheet_dir.exists():
        return

    for table_name, csv_name in RETROSHEET_STAT_TABLES.items():
        csv_path = retrosheet_dir / csv_name
        if csv_path.exists():
            conn.execute(
                f"""
                CREATE TABLE {table_name} AS
                SELECT *
                FROM read_csv_auto('{_sql_string(csv_path)}')
                WHERE lower(stattype) = 'value'
                  AND lower(gametype) IN ('regular', 'playoff')
                """
            )

    table_name, csv_name = RETROSHEET_BIOFILE
    csv_path = retrosheet_dir / csv_name
    if csv_path.exists():
        conn.execute(
            f"""
            CREATE TABLE {table_name} AS
            SELECT *
            FROM read_csv_auto('{_sql_string(csv_path)}')
            """
        )


def _sql_string(path: Path) -> str:
    return str(path).replace("'", "''")
