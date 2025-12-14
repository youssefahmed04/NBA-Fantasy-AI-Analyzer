# Codebase Refactoring Plan

## Current Issues

1. **services.py is too large (1295 lines)** - Contains multiple distinct functional areas:
   - Injury heuristics
   - Position analysis
   - League data aggregation
   - Matchup analysis
   - Trade analysis
   - Streaming analysis

2. **ui_components.py is large (825 lines)** - All UI rendering in one file

3. **No clear module separation** - Business logic is mixed together

## Proposed Structure

```
nba_fantasy_ai_analyzer/
├── app.py                    # Main entry point (keep as-is)
├── config.py                 # Configuration (keep as-is)
├── models.py                 # Basic Player model (keep as-is)
├── fantasy_models.py         # Fantasy-specific models (keep as-is)
├── data_loader.py            # NBA data loading (keep as-is)
├── styling.py                # CSS styling (keep as-is)
│
├── core/                     # Core business logic
│   ├── __init__.py
│   ├── league.py            # League connection & aggregation
│   ├── team_analysis.py      # Team profile & scoring
│   └── matchup.py           # Matchup analysis
│
├── analysis/                 # Analysis modules
│   ├── __init__.py
│   ├── injury.py            # Injury severity analysis
│   ├── position.py          # Position balance analysis
│   ├── trade.py             # Trade suggestion engine
│   └── streaming.py         # Streaming/waiver wire analysis
│
└── ui/                       # UI components
    ├── __init__.py
    ├── sidebar.py           # Sidebar controls
    ├── league_view.py        # League overview UI
    ├── matchup_view.py       # Matchup tab UI
    ├── team_view.py          # Team analyzer UI
    ├── trade_view.py         # Trade analyzer UI
    └── streaming_view.py     # Streaming tab UI
```

## Benefits

1. **Better organization** - Each module has a single, clear responsibility
2. **Easier maintenance** - Find code by feature area
3. **Better testability** - Smaller, focused modules are easier to test
4. **Scalability** - Easy to add new features without bloating existing files
5. **Clearer imports** - `from analysis.trade import generate_trade_suggestions`

## Migration Strategy

1. ✅ Create new directory structure
2. ✅ Move functions to appropriate modules
3. ✅ Update imports across codebase
4. ⏳ Test to ensure nothing breaks
5. ⏳ Remove old services.py and ui_components.py (optional - can keep as backup)

## Refactoring Complete!

The codebase has been successfully refactored into a modular structure:

### New Structure Created:
- `core/` - Core business logic
  - `league.py` - League connection & aggregation
  - `team_analysis.py` - Team profile & scoring
  - `matchup.py` - Matchup analysis
- `analysis/` - Analysis modules
  - `injury.py` - Injury severity analysis
  - `position.py` - Position balance analysis
  - `trade.py` - Trade suggestion engine
  - `streaming.py` - Streaming/waiver wire analysis
- `ui/` - UI components
  - `sidebar.py` - Sidebar controls
  - `league_view.py` - League overview UI
  - `matchup_view.py` - Matchup tab UI
  - `team_view.py` - Team analyzer UI
  - `trade_view.py` - Trade analyzer UI
  - `streaming_view.py` - Streaming tab UI

### Files Updated:
- `app.py` - Updated to use new module structure

### Old Files (can be removed after testing):
- `services.py` - Replaced by modules in `core/` and `analysis/`
- `ui_components.py` - Replaced by modules in `ui/`

