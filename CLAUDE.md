# Claude Code Instructions

## Documentation
- **Do NOT document code/changes unless explicitly asked**
- **ALL documentation files MUST be in `doc/` folder** (not in project root)
- Keep documentation minimal and focused on operational instructions
- Do NOT create markdown files in root directory—use `doc/` instead
- Examples:
  - ❌ WRONG: `QUICK_START.md` in root
  - ✅ RIGHT: `doc/QUICK_START.md`

## File Management
- Do NOT create more than 4 files in `src/` directory (currently: 7 core utilities)
- Only create test/temporary files when absolutely necessary
- Focus on modifying existing files rather than creating new ones
- **ALL documentation files go in `doc/` folder** (see above)

## Documentation Structure
```
e:\time_to_empty\
├── CLAUDE.md                          ← This file (project rules)
├── config.yaml                        ← Configuration
├── requirements.txt                   ← Dependencies
├── doc/
│   ├── QUICK_START.md                ← Quick reference (2 min read)
│   ├── OPERATIONAL_GUIDE.md          ← Detailed procedures
│   ├── WORKFLOW_DIAGRAM.txt          ← Visual diagrams
│   ├── IMPLEMENTATION_SUMMARY.md     ← What was built
│   └── ...
├── src/
│   ├── main.py                       ← Entry point
│   ├── tte_ttf_algorithm.py          ← Core algorithm
│   ├── pattern_manager.py            ← Pattern persistence
│   ├── data_splitter.py              ← Train-test splitting
│   ├── metrics_calculator.py         ← Metrics computation
│   ├── comparison_reporter.py        ← Report generation
│   └── __init__.py
└── outputs/                          ← Generated results (auto-created)
```

## Execution

### Main Entry Point
- `src/main.py` is the primary execution entry point
- Configuration is in `config.yaml`
- Supports 5 execution modes (see below)

### Execution Modes (config.yaml)

```yaml
execution:
  mode: "train_test_split"  # Options: train_test_split, train_only, apply, full, monthly
```

**Mode Details:**

1. **train_test_split** - Split by date, learn from train period, validate on test period
   - Use case: Initial algorithm validation, understand train-test performance gap
   - Output: patterns/, train_results, test_results, comparison_report
   - Config: train_date_start/end, test_date_start/end

2. **train_only** - Learn from all data, save patterns for later reuse
   - Use case: Before production deployment, learning from full historical data
   - Output: patterns/, full_results
   - Config: patterns_label for naming saved patterns

3. **apply** - Apply previously trained patterns to new data (NO retraining)
   - Use case: Production inference, processing new data with learned patterns
   - Output: applied_results only
   - Config: pattern_path (explicit) or pattern_label_filter (auto-find)

4. **full** - Process entire dataset (legacy mode)
   - Use case: Baseline analysis
   - Output: full_results

5. **monthly** - Filter by month and process
   - Use case: Monthly reporting
   - Config: execution.month = "YYYY-MM"

### Pattern Persistence

Trained patterns are saved to `outputs/patterns/<label>_<timestamp>/`:
- `metadata.json` - Training timestamp, parameters, file locations
- `soc_decay_analyzer.pkl` - Learned SOC decay rates by current/load class
- `load_classifier.pkl` - Learned load classification model

Use PatternManager to load/list patterns:
```python
from src.pattern_manager import PatternManager
mgr = PatternManager("outputs/patterns")
mgr.load_patterns(pattern_path, calculator)
```

## Data Loading Pipeline

### Workflow (matching daily_ness_time_to_empty.ipynb)
1. **Load parquet** - `pd.read_parquet(file_path)`
2. **DTO transformation** - `dto_ness_parquet(df)`:
   - Type conversion (float columns: Ip, Vp, SoC, FullCap, BT1-4, etc.)
   - Merge current and voltage data using `merge_asof()`
   - Split Ip into ic (charge) and id (discharge) based on sign
   - Process temperature: BT1-4 ÷ 10, create tmp as max
   - Column mapping: ts, ic, id, lv, soc, tmp, etc.
3. **Time columns** - `add_time_columns(df)`:
   - Convert timestamp (ms) to UTC datetime
   - Calculate time differences in seconds
4. **Load status** - `get_load_status(current_net)`:
   - Calculate net current: `ic - id`
   - Classify state: charging (>10 mA), discharging (<-10 mA), rest (±10 mA)
5. **Pass to algorithm** - TTE/TTF uses load_status state for session determination

### State Determination (not from SOC change)
- **Charging**: net current > 10 mA
- **Discharging**: net current < -10 mA
- **Rest**: -10 ≤ net current ≤ 10 mA

## Session-Based TTE/TTF Algorithm

### How It Works
Tracks distinct charge/discharge/rest sessions and validates TTE/TTF estimates:
1. **Session tracking** - Creates new session when battery state (from load_status) changes
2. **Energy accumulation** - Tracks SOC changes during session (converted to Ah)
3. **Validation gating** - Outputs TTE/TTF only if session meets dual criteria:
   - Duration ≥ `session_min_duration_minutes` (default: 15 min)
   - Energy change ≥ `session_min_energy_ah` (default: 1 Ah)
4. **Smooth transitions** - Uses exponential smoothing (factor: 0.3) to prevent sudden jumps

### Configuration (config.yaml)
```yaml
tte_ttf:
  current_threshold_ma: 50.0              # Base load injection threshold (mA)
  ema_window_minutes: 15                  # Current smoothing window (min)
  session_min_duration_minutes: 15.0      # Min session duration (min)
  session_min_energy_ah: 1.0              # Min energy change per session (Ah)
  tte_ttf_smoothing_factor: 0.3           # Smoothing: 0.1 (smooth) to 1.0 (responsive)
```

### Tuning Tips
**If coverage is too low (mostly NaN):**
- Reduce `session_min_duration_minutes` (try: 3-5 for frequent state changes)
- Reduce `session_min_energy_ah` (try: 0.1-0.5 for fine-grained tracking)

**If TTE/TTF values jump too much:**
- Decrease `tte_ttf_smoothing_factor` (try: 0.1-0.2 for smoother output)

**If current estimates are noisy:**
- Increase `ema_window_minutes` (try: 20-30 for smoother estimates)

## GUI - Battery Simulation Application

### Overview
Interactive Streamlit-based GUI (`gui/app.py`) for real-time visualization and step-by-step simulation of battery behavior from TTE/TTF results CSV files.

### Running the GUI

**Quick Start:**
```bash
# Windows
gui/run.bat

# Linux/macOS
bash gui/run.sh

# Or directly
streamlit run gui/app.py
```

The app opens at `http://localhost:8501`

### Features
- **Play/Pause Simulation**: Step through historical data at configurable speeds (1-100×)
- **Dynamic Metrics**: Real-time KPI cards showing TTE/TTF, SOC, current, voltage
- **Intelligent Switching**: Automatically displays TTE during discharge, TTF during charge
- **Time Series Charts**: Visualizes SOC, current draw, and voltage trends
- **Interactive Controls**: Speed adjustment, batch size, timeline scrubber
- **Status Indicators**: Color-coded charging state (🟢 charging, 🔴 discharging, 🔵 rest)

### Data Format Expected
CSV files in `outputs/` directory with columns:
- `timestamp`: ISO datetime
- `voltage_v`, `current_a`: Raw measurements
- `status`: 'charging', 'discharging', or 'rest'
- `tte_hours`, `ttf_hours`: Time estimates (NaN when not applicable)
- `soc`, `capacity_ah`: Battery state
- `confidence`, `num_samples`: Prediction metadata

### How to Use
1. Run the application
2. Select a CSV file from sidebar
3. Adjust speed and batch size
4. Click **▶️ Play** to start simulation
5. Watch metrics and charts update in real-time
6. Use slider to jump to any point in the dataset
