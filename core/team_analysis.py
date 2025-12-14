"""Team profile scoring and analysis."""

from __future__ import annotations

from typing import Dict, List

from config import CATEGORIES, TURNOVER_WEIGHT
from fantasy_models import TeamProfile


def apply_weights_and_scores(
    profiles: List[TeamProfile],
    category_weights: Dict[str, float],
) -> None:
    """
    - Compute weighted z-scores + total_score for each team.
    - Detect punts & strengths with simple, fantasy-realistic thresholds:

        • Manual punt: any category with weight == 0  → always in punts,
          and not counted toward total score.

        • Auto punts (1–3 max):
            - Look only at categories with weight > 0.
            - Consider cats with z < 0 as weak.
            - If any cats have z <= -0.5, punt up to the worst 3 of those.
            - Else, if only slightly negative, punt just the single worst cat.

        • Strengths:
            - Non-punted categories with z >= +0.4.
            - Take the top 4 strongest by z-score.
    """

    for tp in profiles:
        tp.weighted_zscores = {}
        total = 0.0

        # -------- Weighted z-scores & total score (respect manual weights) --------
        for cat in CATEGORIES:
            base_z = tp.raw_zscores.get(cat, 0.0)
            base_weight = category_weights.get(cat, 1.0)

            # If user sets weight to 0, treat as a hard punt and exclude from score.
            if base_weight <= 0.0:
                continue

            eff_weight = base_weight * (TURNOVER_WEIGHT if cat == "TOV" else 1.0)
            weighted_z = base_z * eff_weight

            tp.weighted_zscores[cat] = weighted_z
            total += weighted_z

        tp.total_score = total

        # -------- Manual punts (from UI weights) --------
        manual_punts = [
            cat for cat in CATEGORIES if category_weights.get(cat, 1.0) == 0.0
        ]

        # -------- Auto punts based on z-scores --------
        z_vals = {
            cat: tp.raw_zscores.get(cat, 0.0)
            for cat in CATEGORIES
            if category_weights.get(cat, 1.0) > 0.0
        }

        # Weak = below league average; serious weak = clearly bad.
        weak_cats = [cat for cat, z in z_vals.items() if z < 0.0]
        serious_weak = [cat for cat, z in z_vals.items() if z <= -0.5]

        auto_punts: List[str] = []

        if serious_weak:
            serious_weak_sorted = sorted(serious_weak, key=lambda c: z_vals[c])
            auto_punts = serious_weak_sorted[:3]
        elif weak_cats:
            weakest = min(weak_cats, key=lambda c: z_vals[c])
            auto_punts = [weakest]
        else:
            auto_punts = []

        punt_set = set(manual_punts) | set(auto_punts)
        punts = [cat for cat in CATEGORIES if cat in punt_set]

        # -------- Strengths (non-punted, clearly above average) --------
        strength_candidates = [
            (cat, z)
            for cat, z in z_vals.items()
            if cat not in punt_set and z >= 0.4
        ]
        strength_candidates.sort(key=lambda x: x[1], reverse=True)
        strengths = [cat for cat, _ in strength_candidates[:4]]

        tp.punt_categories = punts
        tp.strength_categories = strengths

