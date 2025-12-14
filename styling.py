from __future__ import annotations

import streamlit as st


def inject_css() -> None:
    st.markdown(
        """
        <style>
        body, .stApp {
            background: radial-gradient(circle at top left, #121826, #050816);
            color: #f9fafb;
        }

        .block-container {
            padding-top: 1.8rem;
            padding-bottom: 3rem;
            max-width: 1300px;
        }

        h1, h2, h3, h4 {
            font-family: system-ui, -apple-system, BlinkMacSystemFont, "SF Pro Display",
                         "Segoe UI", sans-serif;
            letter-spacing: 0.02em;
        }

        .hero-card {
            border-radius: 24px;
            padding: 24px 30px;
            background: radial-gradient(circle at 10% 0%, #1f2937, #020617);
            box-shadow: 0 24px 60px rgba(15, 23, 42, 0.9);
            border: 1px solid rgba(148, 163, 184, 0.35);
        }

        .hero-pill {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 4px 10px;
            border-radius: 999px;
            font-size: 11px;
            letter-spacing: 0.12em;
            text-transform: uppercase;
            background: linear-gradient(90deg, #22c55e33, #3b82f633);
            color: #a5b4fc;
            border: 1px solid rgba(129, 140, 248, 0.45);
        }

        .metric-card {
            border-radius: 18px;
            padding: 14px 18px;
            background: linear-gradient(135deg, #020617, #020617);
            border: 1px solid rgba(51, 65, 85, 0.9);
            box-shadow: 0 16px 40px rgba(15, 23, 42, 0.9);
        }

        .metric-label {
            font-size: 11px;
            text-transform: uppercase;
            color: #9ca3af;
            letter-spacing: 0.16em;
        }

        .metric-value {
            font-size: 24px;
            font-weight: 700;
            color: #e5e7eb;
        }

        .metric-subvalue {
            font-size: 12px;
            color: #9ca3af;
        }

        .pill {
            display: inline-flex;
            align-items: center;
            padding: 3px 9px;
            border-radius: 999px;
            font-size: 11px;
            background: rgba(15, 23, 42, 0.85);
            border: 1px solid rgba(55, 65, 81, 0.9);
            color: #e5e7eb;
            margin-right: 6px;
            margin-bottom: 4px;
        }

        .pill-positive {
            background: rgba(22, 163, 74, 0.12);
            border-color: rgba(34, 197, 94, 0.7);
            color: #bbf7d0;
        }

        .pill-negative {
            background: rgba(220, 38, 38, 0.12);
            border-color: rgba(248, 113, 113, 0.6);
            color: #fecaca;
        }

        .coach-card {
            border-radius: 18px;
            padding: 20px 22px;
            background: radial-gradient(circle at top left, #020617, #020617);
            border: 1px solid rgba(51, 65, 85, 0.95);
            box-shadow: 0 18px 40px rgba(15, 23, 42, 0.9);
        }

        .coach-title {
            font-size: 18px;
            font-weight: 700;
            margin-bottom: 12px;
        }

        .coach-body {
            font-size: 14px;
            color: #e5e7eb;
        }

        .matchup-card {
            border-radius: 18px;
            padding: 14px 18px;
            background: linear-gradient(135deg, #020617, #020617);
            border: 1px solid rgba(55, 65, 81, 0.85);
            box-shadow: 0 14px 30px rgba(15, 23, 42, 0.85);
        }

        .matchup-detail-card {
            margin-top: 6px;
            padding: 10px 12px;
            border-radius: 16px;
            background: radial-gradient(circle at top left, #020617, #020617);
            border: 1px solid rgba(55, 65, 81, 0.9);
        }

        .matchup-header-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 6px;
        }

        .matchup-header-names {
            font-size: 13px;
            font-weight: 600;
            color: #e5e7eb;
        }

        .matchup-header-sub {
            font-size: 11px;
            color: #9ca3af;
        }

        .matchup-header-record {
            font-size: 13px;
            font-weight: 600;
            color: #e5e7eb;
        }

        .matchup-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 11px;
        }

        .matchup-table th,
        .matchup-table td {
            padding: 4px 6px;
            text-align: center;
            border-bottom: 1px solid rgba(31, 41, 55, 0.8);
        }

        .matchup-table th:first-child,
        .matchup-table td:first-child {
            text-align: left;
        }

        .matchup-cat-header {
            font-size: 10px;
            text-transform: uppercase;
            color: #9ca3af;
            letter-spacing: 0.08em;
        }

        .matchup-team-cell {
            font-weight: 600;
            color: #e5e7eb;
        }

        .matchup-cell-win {
            background: rgba(34, 197, 94, 0.18);
        }

        .matchup-cell-tie {
            background: rgba(148, 163, 184, 0.16);
        }

        .section-title {
            font-size: 15px;
            text-transform: uppercase;
            letter-spacing: 0.18em;
            color: #9ca3af;
            margin-bottom: 4px;
        }

        .roster-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 12px;
        }

        .roster-table th,
        .roster-table td {
            padding: 6px 8px;
            border-bottom: 1px solid rgba(31, 41, 55, 0.8);
            vertical-align: middle;
        }

        .roster-table th {
            text-align: left;
            font-size: 11px;
            text-transform: uppercase;
            color: #9ca3af;
            letter-spacing: 0.08em;
        }

        .roster-headshot {
            width: 32px;
            height: 32px;
            border-radius: 999px;
            object-fit: cover;
            border: 1px solid rgba(148, 163, 184, 0.8);
        }

                .trade-card {
            margin-top: 14px;
            margin-bottom: 10px;
            padding: 14px 16px;
            border-radius: 18px;
            background: radial-gradient(circle at top left, #020617, #020617);
            border: 1px solid rgba(55, 65, 81, 0.9);
            box-shadow: 0 16px 40px rgba(15, 23, 42, 0.9);
        }

        .trade-card-header {
            display: flex;
            justify-content: space-between;
            align-items: baseline;
            margin-bottom: 8px;
        }

        .trade-card-title {
            font-size: 14px;
            font-weight: 600;
            color: #e5e7eb;
        }

        .trade-card-score {
            font-size: 12px;
            color: #9ca3af;
        }

        .trade-card-body {
            font-size: 13px;
            color: #e5e7eb;
        }

        section[data-testid="stSidebar"] {
            background: radial-gradient(circle at top left, #020617, #020617);
            border-right: 1px solid rgba(31, 41, 55, 0.9);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
