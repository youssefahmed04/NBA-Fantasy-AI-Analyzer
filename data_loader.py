from typing import List, Dict
import statistics

import pandas as pd
from nba_api.stats.endpoints import leaguedashplayerstats

from models import Player, CATEGORIES, NEGATIVE_CATEGORIES

# Map our fantasy categories to nba_api fields
STAT_FIELD_MAP: Dict[str, str] = {
    "PTS": "PTS",
    "REB": "REB",
    "AST": "AST",
    "STL": "STL",
    "BLK": "BLK",
    "FG%": "FG_PCT",
    "FT%": "FT_PCT",
    "3PM": "FG3M",
    "TOV": "TOV",
}


def load_players_via_api(season: str = "2025-26", top_n: int = 350) -> List[Player]:
    """
    Fetch per-game stats from nba_api and convert to Player objects with z-scores.
    """
    df = leaguedashplayerstats.LeagueDashPlayerStats(
        season=season,
        per_mode_detailed="PerGame",
    ).get_data_frames()[0]

    # Take top N by scoring to keep things manageable
    df = df.sort_values("PTS", ascending=False).head(top_n).reset_index(drop=True)

    players: List[Player] = []
    for _, row in df.iterrows():
        stats = {cat: float(row.get(STAT_FIELD_MAP[cat], 0.0)) for cat in CATEGORIES}
        pid = row.get("PLAYER_ID")
        try:
            pid_int = int(pid)
        except Exception:
            pid_int = None
        p = Player(
            name=str(row["PLAYER_NAME"]),
            team=str(row["TEAM_ABBREVIATION"]),
            stats=stats,
            player_id=pid_int,
        )
        players.append(p)

    # compute z-scores across population
    for cat in CATEGORIES:
        values = [p.stats[cat] for p in players]
        if len(values) < 2:
            continue
        mean = statistics.mean(values)
        std = statistics.pstdev(values) or 1.0
        for p in players:
            z = (p.stats[cat] - mean) / std
            if cat in NEGATIVE_CATEGORIES:
                z = -z
            p.zscores[cat] = z

    return players
