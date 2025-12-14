"""
Enhanced trade suggestion engine with improved algorithms.

Key improvements:
1. Diminishing returns on category improvements
2. Category volatility weighting
3. Category ceiling/floor analysis
4. Better preference modeling with non-linear curves
5. Positional need scoring
"""

from __future__ import annotations

import math
import statistics
from itertools import combinations
from typing import Any, Dict, List, Tuple

from config import CATEGORIES
from fantasy_models import RosterPlayer, TeamProfile
from analysis.injury import injury_severity
from analysis.position import position_balance_delta
from analysis.trade import (
    TRADE_CATEGORIES,
    PLAYER_Z_PREFIX,
    _compute_local_player_z,
    _player_effect_vector,
    _package_effect_vector,
)

# Category volatility (higher = more volatile, less predictable)
# Based on typical week-to-week variance in 9-cat leagues
CATEGORY_VOLATILITY: Dict[str, float] = {
    "PTS": 0.15,   # Moderate volatility
    "REB": 0.12,   # Relatively stable
    "AST": 0.18,   # Moderate-high volatility
    "STL": 0.35,   # Very volatile
    "BLK": 0.32,   # Very volatile
    "FG%": 0.08,   # Very stable
    "FT%": 0.10,   # Very stable
    "3PM": 0.25,   # High volatility
}

# Category correlations (how often categories move together)
# Used to avoid over-weighting correlated improvements
CATEGORY_CORRELATIONS: Dict[Tuple[str, str], float] = {
    ("REB", "FG%"): 0.6,   # Big men get both
    ("AST", "PTS"): 0.5,   # Ball handlers
    ("STL", "AST"): 0.4,   # Active guards
    ("BLK", "REB"): 0.5,   # Big men
    ("3PM", "PTS"): 0.6,   # Shooters
}


def _diminishing_returns(value: float, threshold: float = 1.5) -> float:
    """
    Apply diminishing returns to category improvements.
    
    Once you're already strong in a category, additional improvements
    matter less. Uses exponential decay.
    """
    if value <= 0:
        return value
    # Sigmoid-like function: rapid growth early, plateaus later
    return value * (1.0 - math.exp(-value / threshold))


def _category_swing_value(
    current_z: float,
    improvement: float,
    volatility: float,
) -> float:
    """
    Calculate the "swing value" of a category improvement.
    
    Considers:
    - How close you are to the edge (winning by 0.1 vs 5.0)
    - Category volatility (volatile cats need bigger margins)
    - Diminishing returns on already-strong categories
    """
    # If you're already winning by a lot, small improvements don't matter
    if current_z > 1.0:
        # Diminishing returns kick in
        effective_improvement = improvement * (1.0 / (1.0 + current_z))
    elif current_z < -0.5:
        # If you're losing badly, improvements are very valuable
        effective_improvement = improvement * 1.5
    else:
        # Close to average - improvements are most valuable
        effective_improvement = improvement * 1.2
    
    # Volatile categories need bigger margins to be reliable
    # So we downweight improvements in volatile cats
    volatility_factor = 1.0 - (volatility * 0.3)
    
    return effective_improvement * volatility_factor


def _build_enhanced_preference_vector(
    team: TeamProfile,
    category_weights: Dict[str, float],
    opponent: TeamProfile | None = None,
) -> Dict[str, float]:
    """
    Enhanced preference vector with non-linear modeling.
    
    Improvements:
    1. Non-linear preference curves (diminishing returns)
    2. Category gap analysis (prioritize fixing close-to-average weaknesses)
    3. Volatility weighting
    4. Opponent-aware preferences (if opponent is known)
    """
    prefs: Dict[str, float] = {}
    punt_set = set(team.punt_categories or [])
    strengths_set = set(team.strength_categories or [])
    
    for cat in TRADE_CATEGORIES:
        z = float(team.raw_zscores.get(cat, 0.0))
        w = float(category_weights.get(cat, 1.0))
        volatility = CATEGORY_VOLATILITY.get(cat, 0.15)
        
        # Base preference with non-linear curve
        if cat in strengths_set and z > 0:
            # Strong cat - use diminishing returns
            base = 1.0 + 0.5 * _diminishing_returns(z, threshold=1.0)
        elif z > 0.2:
            # Mild positive - still valuable but less urgent
            base = 0.7 + 0.3 * z
        elif z > -0.3:
            # Close to average - HIGH priority (swing potential)
            # This is where small improvements can flip categories
            gap = abs(z)
            base = 0.8 + 0.4 * (1.0 - gap)  # Closer to 0 = higher priority
        else:
            # Weak category - moderate priority
            base = 0.4 + 0.2 * (-min(z, 0.0))
        
        # Opponent-aware adjustment
        if opponent:
            opp_z = float(opponent.raw_zscores.get(cat, 0.0))
            margin = z - opp_z
            
            # If you're losing by a small margin, boost priority
            if -0.5 < margin < 0:
                base *= 1.3  # Close loss = high priority
            # If you're winning comfortably, reduce priority
            elif margin > 1.0:
                base *= 0.7  # Big lead = lower priority
        
        # Volatility adjustment: stable categories are more valuable
        # (you can rely on them week-to-week)
        volatility_bonus = (1.0 - volatility) * 0.2
        base += volatility_bonus
        
        if cat in punt_set:
            base *= 0.2  # Even more heavily reduce punted cats
        
        score = max(0.0, base * w)
        prefs[cat] = score
    
    total = sum(prefs.values())
    if total <= 0:
        n = len(TRADE_CATEGORIES)
        return {cat: 1.0 / n for cat in TRADE_CATEGORIES}
    
    return {cat: val / total for cat, val in prefs.items()}


def _score_package_enhanced(
    team: TeamProfile,
    preferences: Dict[str, float],
    players_out: List[RosterPlayer],
    players_in: List[RosterPlayer],
    opponent: TeamProfile | None = None,
) -> Tuple[float, Dict[str, float]]:
    """
    Enhanced package scoring with:
    1. Category swing value (how much does this actually move the needle?)
    2. Volatility weighting
    3. Correlation penalties (avoid double-counting correlated improvements)
    4. Position balance
    """
    out_eff = _package_effect_vector(players_out)
    in_eff = _package_effect_vector(players_in)
    
    total_gain = 0.0
    per_cat_gain: Dict[str, float] = {}
    
    # Track correlated improvements to avoid double-counting
    correlated_improvements: Dict[str, float] = {}
    
    for cat in TRADE_CATEGORIES:
        delta_raw = in_eff[cat] - out_eff[cat]
        current_z = float(team.raw_zscores.get(cat, 0.0))
        volatility = CATEGORY_VOLATILITY.get(cat, 0.15)
        weight = float(preferences.get(cat, 0.0))
        
        # Calculate swing value (how much does this actually matter?)
        swing_value = _category_swing_value(current_z, delta_raw, volatility)
        
        # Apply preference weight
        delta = swing_value * weight
        
        # Check for correlations and apply penalty
        correlation_penalty = 1.0
        for (cat1, cat2), corr in CATEGORY_CORRELATIONS.items():
            if cat == cat1 and cat2 in per_cat_gain and per_cat_gain[cat2] > 0:
                # If we're already improving a correlated category, reduce this one
                correlation_penalty *= (1.0 - corr * 0.3)
            elif cat == cat2 and cat1 in per_cat_gain and per_cat_gain[cat1] > 0:
                correlation_penalty *= (1.0 - corr * 0.3)
        
        delta *= correlation_penalty
        per_cat_gain[cat] = delta
        total_gain += delta
    
    # Position-balance term (unchanged)
    pos_delta = position_balance_delta(team, players_out, players_in)
    pos_weight = 0.15  # Slightly increased
    pos_gain = pos_weight * pos_delta
    per_cat_gain["_pos_balance"] = pos_gain
    total_gain += pos_gain
    
    return total_gain, per_cat_gain


def generate_enhanced_trade_suggestions(
    team_a: TeamProfile,
    team_b: TeamProfile,
    category_weights: Dict[str, float],
    max_trades: int = 3,
    consider_opponent: bool = True,
) -> List[Dict[str, Any]]:
    """
    Enhanced trade suggestions with improved algorithms.
    
    Key improvements:
    1. Better preference modeling (non-linear, volatility-aware)
    2. Category swing value (prioritizes improvements that actually matter)
    3. Correlation penalties (avoids double-counting)
    4. Opponent-aware preferences (if available)
    """
    from analysis.trade import _build_ai_reason, _fairness_score_for_packages
    
    # 1) Compute local z-scores
    all_players: List[RosterPlayer] = list(team_a.players) + list(team_b.players)
    _compute_local_player_z(all_players)
    
    # 2) Build enhanced preference vectors
    # Optionally use opponent info if available
    opponent_a = team_b if consider_opponent else None
    opponent_b = team_a if consider_opponent else None
    
    prefs_a = _build_enhanced_preference_vector(team_a, category_weights, opponent_a)
    prefs_b = _build_enhanced_preference_vector(team_b, category_weights, opponent_b)
    
    suggestions: List[Dict[str, Any]] = []
    sizes = (1, 2)
    
    for size_a in sizes:
        combos_a = list(combinations(team_a.players, size_a))
        for size_b in sizes:
            combos_b = list(combinations(team_b.players, size_b))
            
            for pack_a in combos_a:
                pack_a_list = list(pack_a)
                names_a = {p.display_name for p in pack_a_list}
                
                for pack_b in combos_b:
                    pack_b_list = list(pack_b)
                    names_b = {p.display_name for p in pack_b_list}
                    
                    if names_a == names_b:
                        continue
                    
                    # Enhanced scoring
                    fit_a, per_cat_a = _score_package_enhanced(
                        team=team_a,
                        preferences=prefs_a,
                        players_out=pack_a_list,
                        players_in=pack_b_list,
                        opponent=opponent_a,
                    )
                    
                    fit_b, per_cat_b = _score_package_enhanced(
                        team=team_b,
                        preferences=prefs_b,
                        players_out=pack_b_list,
                        players_in=pack_a_list,
                        opponent=opponent_b,
                    )
                    
                    if fit_a <= 0.0 or fit_b <= 0.0:
                        continue
                    
                    total_fit = fit_a + fit_b
                    if total_fit <= 0.08:  # Slightly higher threshold
                        continue
                    
                    # Fairness check
                    fairness = _fairness_score_for_packages(
                        pack_a_list, pack_b_list, category_weights
                    )
                    if fairness < 0.85:
                        continue
                    
                    # Categories improved
                    improve_a = sorted(
                        [c for c in TRADE_CATEGORIES if per_cat_a.get(c, 0.0) > 0],
                        key=lambda c: per_cat_a[c],
                        reverse=True,
                    )[:3]
                    
                    improve_b = sorted(
                        [c for c in TRADE_CATEGORIES if per_cat_b.get(c, 0.0) > 0],
                        key=lambda c: per_cat_b[c],
                        reverse=True,
                    )[:3]
                    
                    ai_reason = _build_ai_reason(
                        team_a=team_a,
                        team_b=team_b,
                        pack_a=pack_a_list,
                        pack_b=pack_b_list,
                        per_cat_a=per_cat_a,
                        per_cat_b=per_cat_b,
                        gain_a=fit_a,
                        gain_b=fit_b,
                        fairness_score=fairness,
                    )
                    
                    suggestions.append(
                        {
                            "from_a": pack_a_list,
                            "from_b": pack_b_list,
                            "gain_a": fit_a,
                            "gain_b": fit_b,
                            "score": total_fit * fairness,
                            "fairness": fairness,
                            "improve_a": improve_a,
                            "improve_b": improve_b,
                            "ai_reason": ai_reason,
                        }
                    )
    
    suggestions.sort(key=lambda s: s["score"], reverse=True)
    return suggestions[:max_trades]

