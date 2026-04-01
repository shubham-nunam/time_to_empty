# TTE/TTF Multi-Battery System — Project Rules

**Last Updated:** 2026-04-01

## Project Overview

Multi-battery Time To Empty (TTE) / Time To Full (TTF) estimation system using historical SOC decay patterns. Learns from parquet data files and stores patterns in SQLite.

- **Two execution modes:** `train_all_batteries` (learn), `apply_battery` (inference)
- **Core modules:** 5 files in `src/` directory
- **Storage:** SQLite database (`battery_patterns.db`)
- **Input:** Parquet files in `data/` directory
- **Output:** CSV results in `output/` directory

---

## Documentation Standards

- **Do NOT document code unless explicitly asked**
- **ALL documentation goes in `doc/` folder** (NOT project root)
- Keep operational, concise, focused on how to run the system
- Examples:
  - ❌ WRONG: `QUICK_START.md` in root
  - ✅ RIGHT: `doc/SYSTEM_OVERVIEW.md` in doc folder

**Current documentation:**
- `doc/SYSTEM_OVERVIEW.md` — High-level system architecture and modes
- `doc/CONFIGURATION.md` — All config.yaml settings with examples
- `doc/OUTPUT_SCHEMA.md` — CSV output columns and interpretation
- `doc/ALGORITHM.md` — Technical details of TTE/TTF calculation

---

## File Management

**Current `src/` structure (5 core files, as intended):**
```
src/
├── main.py                      ← Entry point (dispatch to modes)
├── battery_manager.py           ← Multi-battery orchestration
├── db.py                        ← SQLite pattern storage/retrieval
├── tte_ttf_algorithm.py         ← Core TTE/TTF calculation
└── __init__.py
```

**Rule:** Avoid adding more files to `src/`. Keep focused on these 5 core utilities.

---

## Execution Modes

All behavior controlled by `config.yaml`:

### Mode 1: `train_all_batteries`
**Purpose:** Learn SOC decay patterns from battery data

```yaml
execution:
  mode: "train_all_batteries"
  patterns_label: "september_2025"     # Name for saved patterns
  training_month: ""                   # "" = all data, "2025-09" = Sept only
```

**Workflow:**
1. Discovers all `.parquet` files in `data/` directory
2. Trains LoadClassifier + SOCDecayAnalyzer for each battery
3. Saves patterns to SQLite with given label
4. Outputs: One CSV per battery with TTE/TTF estimates

**Time:** ~10-30s depending on data volume

---

### Mode 2: `apply_battery`
**Purpose:** Apply previously trained patterns to new data (no retraining)

```yaml
execution:
  mode: "apply_battery"
  patterns_label: "september_2025"     # Which patterns to load from DB
  apply_month: ""                      # "" = all data, "2025-10" = Oct only
```

**Workflow:**
1. Loads patterns from SQLite using label
2. Applies SimpleTTECalculator to new data
3. Outputs: One CSV per battery with TTE/TTF estimates

**Time:** ~2-5s per battery (no training overhead)

---

## Data Pipeline

### Input Data
- **Format:** Parquet files in `data/` directory
- **File naming:** `{battery_id}.parquet` (e.g., `SE0100000092.parquet`)
- **Columns:** ts (timestamp), ic (charge current), id (discharge current), lv (voltage), soc, FullCap, etc.

### Processing Steps
1. **Load parquet** via `pd.read_parquet()`
2. **DTO transformation** via `dto_ness_parquet()` (type conversion, ic/id split)
3. **Add time columns** (UTC time, time diffs)
4. **State classification** (charging/discharging/rest based on net current)
5. **TTE/TTF estimation** (LoadClassifier → decay rate lookup → smoothing)
6. **Save CSV** results to `output/` directory

### State Determination
State (charging/discharging/rest) based on **net current** (>50mA / <-50mA / ±50mA):
```python
net_current = ic - id
if net_current > 50 mA:    status = "charging"
elif net_current < -50 mA: status = "discharging"
else:                       status = "rest"
```

---

## Algorithm Architecture

**Three components:**

1. **LoadClassifier**
   - Categorizes discharge pattern: idle, steady, transient, cyclic
   - Uses 30-sample current history window

2. **SOCDecayAnalyzer** (training only)
   - Learns SOC decay rates (% per minute) for:
     - SOC levels (10% buckets: 0-10%, 10-20%, ...)
     - Load classes (idle, steady, transient, cyclic)
     - Current ranges (configurable buckets)
     - States (charging vs discharging)
   - Stores in SQLite with sample counts and percentiles

3. **SimpleTTECalculator** (training + inference)
   - Looks up learned decay rate for current conditions
   - Validates session (dual gates: medium 3min+0.2Ah, high 15min+1Ah)
   - Applies EMA smoothing for stability
   - Assigns confidence (high / medium)
   - Implements carry-forward to fill NaN gaps

**Session Tracking:**
- Monitors when state changes (start new session)
- Accumulates SOC change + time
- Emits TTE/TTF when gate criteria met
- Uses last valid TTE (decremented by time) during gaps

**Fallback hierarchy** when training data sparse:
1. Exact condition match (SOC bucket, load, current)
2. Relax load class (transient → cyclic → steady → idle)
3. Neighbor SOC bucket (±10%)
4. Global fleet average
5. Hard default (0.15%/min)

---

## Configuration (config.yaml)

**Critical settings:**
```yaml
execution:
  mode: "train_all_batteries" or "apply_battery"
  patterns_label: "label_name"        # Used to save/load patterns
  training_month: ""                  # Filter by YYYY-MM or empty
  apply_month: ""                     # Filter by YYYY-MM or empty

database:
  path: "battery_patterns.db"         # SQLite file

tte_ttf:
  current_threshold_ma: 50.0          # Noise floor for state detection
  ema_window_minutes: 20              # Current smoothing window
  session_min_duration_minutes: 3.0   # Medium gate: min session duration
  session_min_energy_ah: 0.2          # Medium gate: min SOC change
  session_high_confidence_minutes: 15.0   # High gate: duration
  session_high_confidence_energy_ah: 1.0 # High gate: energy
  tte_ttf_smoothing_factor: 0.15      # EMA smoothing (0.05-0.5)
  current_thresholds_a: [0.5, 2.0, 5.0]  # Current bucketing
  usage_window_minutes: 30            # Rolling avg power window
  default_discharge_rate_pct_per_min: 0.15  # Fallback rate
```

**See `doc/CONFIGURATION.md` for all options and tuning guide.**

---

## Output Format

**File pattern:** `output/tte_ttf_results_{battery_id}.csv`

**Key columns:**
- `timestamp`: ISO datetime
- `voltage_v`, `current_a`: Electrical measurements
- `status`: charging | discharging | rest
- `soc`, `capacity_ah`: Battery state
- **`tte_hours`**: Time To Empty estimate (NaN if not discharging)
- **`ttf_hours`**: Time To Full estimate (NaN if not charging)
- `average_usage_kw`: Rolling 30-min discharge power
- `confidence`: high | medium (validation level)
- `num_samples`: Training data sample count for this condition

**See `doc/OUTPUT_SCHEMA.md` for column definitions and quality checks.**

---

## Typical Workflow

### Month 1: Training
```bash
# config.yaml
execution:
  mode: "train_all_batteries"
  patterns_label: "march_2025"
  training_month: "2025-03"

# Run
python src/main.py

# Output: output/tte_ttf_results_*.csv + patterns in DB
```

### Month 2+: Apply
```bash
# config.yaml
execution:
  mode: "apply_battery"
  patterns_label: "march_2025"        # ← Same label!
  apply_month: "2025-04"

# Run
python src/main.py

# Output: output/tte_ttf_results_*.csv (using learned patterns)
```

---

## Performance Expectations

- **Training:** 10-30s for multi-month data across multiple batteries
- **Apply:** 2-5s per battery (no training)
- **Coverage:** >90% TTE during discharge, >90% TTF during charge (goal)
- **Confidence:** 60-80% high confidence, 20-40% medium (typical)

---

## Directory Structure

```
e:\time_to_empty\
├── CLAUDE.md                         ← This file
├── config.yaml                       ← Settings (edit before running)
├── requirements.txt                  ← Python dependencies
├── battery_patterns.db               ← SQLite pattern storage (auto-created)
├── src/
│   ├── main.py                      ← Entry point
│   ├── battery_manager.py           ← Orchestration
│   ├── db.py                        ← Database access
│   ├── tte_ttf_algorithm.py         ← Core algorithm
│   └── __init__.py
├── data/
│   ├── SE0100000092.parquet         ← Input data files
│   ├── SE0100000093.parquet
│   └── ...
├── output/                           ← Generated results
│   └── tte_ttf_results_{battery_id}.csv
└── doc/                              ← Documentation (in doc/ folder only!)
    ├── SYSTEM_OVERVIEW.md
    ├── CONFIGURATION.md
    ├── OUTPUT_SCHEMA.md
    ├── ALGORITHM.md
    └── WORKFLOW_DIAGRAM.txt
```

---

## Quick Reference

| Task | Config Mode | Command |
|------|-------------|---------|
| Train patterns | `train_all_batteries` | `python src/main.py` |
| Apply patterns | `apply_battery` | `python src/main.py` |
| Train one month | Set `training_month: "2025-03"` | `python src/main.py` |
| Apply to new month | Set `apply_month: "2025-04"` | `python src/main.py` |

---

## References

- **System overview:** `doc/SYSTEM_OVERVIEW.md`
- **Configuration guide:** `doc/CONFIGURATION.md`
- **Output columns:** `doc/OUTPUT_SCHEMA.md`
- **Algorithm details:** `doc/ALGORITHM.md`
