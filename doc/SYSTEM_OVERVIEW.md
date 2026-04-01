# TTE/TTF Multi-Battery System Overview

**Last Updated:** 2026-04-01
**Status:** ✅ Production Ready

---

## What This System Does

Estimates **Time To Empty (TTE)** and **Time To Refill (TTF)** for battery packs using historical SOC decay patterns. Works across multiple battery types by learning battery-specific discharge characteristics.

---

## Key Concepts

### 1. SOC Decay Rates
Instead of predicting TTE from instantaneous current (noisy), the system learns **how fast SOC drops** for specific conditions:
- **Condition:** SOC level 20-30%, steady discharge, 2-4A current
- **Learning:** "SOC drops at 0.85%/min"
- **Runtime:** Current matches condition → use 0.85%/min → TTE = 20% ÷ 0.85%/min = ~23 minutes

### 2. Dual Confidence Gates
Estimates have two quality levels:
- **Medium confidence** (3min + 0.2Ah): Early estimates, broader conditions
- **High confidence** (15min + 1Ah): Strict validation, very reliable estimates

### 3. Pattern Persistence
Learned patterns are stored in **SQLite database** (`battery_patterns.db`):
- Per-battery decay rates
- Load classification data
- Organized by pattern label (e.g., "september_2025")
- Reusable across runs

---

## System Architecture

```
┌─ DATA LOADING ──────────────────┐
│ Input: Parquet files            │
│ - Voltage, current, SOC, etc.   │
│ - One file per battery          │
└────────────────────────────────┘
              ↓
┌─ PREPROCESSING ─────────────────┐
│ - DTO transformation            │
│ - State detection (charging/    │
│   discharging/rest)             │
│ - Time column calculation       │
└────────────────────────────────┘
              ↓
┌─ TRAINING (MODE: train_all) ───┐
│ 1. LoadClassifier learns load   │
│    patterns                     │
│ 2. SOCDecayAnalyzer learns      │
│    historical decay rates       │
│ 3. Patterns saved to SQLite     │
└────────────────────────────────┘
              ↓
┌─ INFERENCE (MODE: apply) ──────┐
│ 1. Load saved patterns from DB  │
│ 2. SimpleTTECalculator uses     │
│    patterns to estimate TTE/TTF │
│ 3. EMA smoothing for stability  │
│ 4. Confidence assignment        │
└────────────────────────────────┘
              ↓
┌─ OUTPUT ───────────────────────┐
│ CSV file with TTE/TTF estimates │
│ - Per-row: timestamp, voltage,  │
│   current, TTE, TTF, confidence │
└────────────────────────────────┘
```

---

## Two Execution Modes

### Mode 1: `train_all_batteries`
**When to use:** Initial training, new battery types, or monthly pattern updates

**What happens:**
1. Discovers all `.parquet` files in `data/` directory
2. Trains each battery independently
3. Saves patterns to SQLite with label (e.g., "september_2025")
4. Outputs: One CSV per battery with TTE/TTF estimates

**Time:** ~10-30s (depending on data volume)

**Configuration:**
```yaml
execution:
  mode: "train_all_batteries"
  patterns_label: "september_2025"
  training_month: ""  # empty = use all data
```

---

### Mode 2: `apply_battery`
**When to use:** Production inference, apply learned patterns to new data

**What happens:**
1. Loads previously trained patterns from SQLite
2. Applies patterns to new data (no retraining)
3. Outputs: One CSV per battery with TTE/TTF estimates

**Time:** ~2-5s per battery (no training overhead)

**Configuration:**
```yaml
execution:
  mode: "apply_battery"
  patterns_label: "september_2025"  # which patterns to load
  apply_month: ""  # empty = use all data
```

---

## How to Run

### Setup (One-Time)
```bash
# Install dependencies
pip install -r requirements.txt

# Place battery data files in data/ directory
# File naming: {battery_id}.parquet (e.g., SE0100000092.parquet)
```

### Training New Patterns
```bash
# 1. Edit config.yaml
#    - Set mode = "train_all_batteries"
#    - Set patterns_label = "september_2025"
#    - Optionally set training_month = "2025-09"

# 2. Run
python src/main.py

# 3. Output files generated in output/ directory
#    - output/tte_ttf_results_SE0100000092.csv
#    - output/tte_ttf_results_SE0100000093.csv
#    - ... (one per battery)
```

### Applying Saved Patterns
```bash
# 1. Edit config.yaml
#    - Set mode = "apply_battery"
#    - Set patterns_label = "september_2025"  (same label used during training)
#    - Optionally set apply_month = "2025-10" (for new month)

# 2. Run
python src/main.py

# 3. Output files generated in output/ directory
#    - output/tte_ttf_results_SE0100000092.csv
#    - output/tte_ttf_results_SE0100000093.csv
#    - ... (same batteries, using learned patterns)
```

---

## Output Files

### CSV Schema
Each output CSV contains the following columns:

| Column | Type | Description |
|--------|------|-------------|
| `timestamp` | ISO datetime | UTC timestamp of measurement |
| `voltage_v` | float | Battery voltage in volts |
| `current_a` | float | Pack current in amperes (positive = discharge) |
| `status` | str | Charging, discharging, or rest |
| `tte_hours` | float | **Time To Empty (hours)** — NaN if not charging |
| `ttf_hours` | float | **Time To Refill (hours)** — NaN if not discharging |
| `soc` | float | State of Charge (0-100%) |
| `capacity_ah` | float | Battery capacity in Ah |
| `average_usage_kw` | float | Rolling 30-min average power during discharge |
| `confidence` | str | `high` or `medium` (estimate reliability) |
| `num_samples` | int | Samples used in TTE/TTF calculation |

---

## Monitoring & Diagnostics

### Coverage Metrics
- **TTE Coverage:** % of discharge rows with valid TTE estimate
- **TTF Coverage:** % of charging rows with valid TTF estimate
- Target: **>90% coverage** indicates good training data

### Confidence Distribution
- **High confidence:** Strict validation (≥15min + ≥1Ah session)
- **Medium confidence:** Early estimates (≥3min + ≥0.2Ah session)
- Good sign: **>70% of estimates are high confidence**

### Warning Signs
| Issue | Likely Cause | Solution |
|-------|------------|----------|
| Coverage <80% | Insufficient training data | Add more historical data, reduce session gates |
| Mostly NaN TTE/TTF | Wrong patterns loaded | Check patterns_label matches actual training |
| TTE jumps wildly | Smoothing too low | Increase `tte_ttf_smoothing_factor` to 0.25-0.3 |
| All "medium" confidence | Training data gaps | Retrain with larger date range |

---

## When to Retrain

**Retrain patterns if:**
- 🔴 Coverage drops below 80%
- 🔴 TTE/TTF values become erratic (std dev > 50% of mean)
- 🔴 New battery types added
- 🔴 Significant environmental changes (temperature, load patterns)

**Reuse patterns if:**
- ✅ Coverage stays >90%
- ✅ Estimates stable and reasonable
- ✅ Same battery types
- ✅ Similar operating conditions

**Recommended Schedule:**
- First month: Monthly retraining (learn seasonal patterns)
- Subsequent: Quarterly or event-driven

---

## Common Workflows

### Workflow 1: Monthly Pattern Update
```bash
# Training
config.yaml: mode = "train_all_batteries", training_month = "2025-04", patterns_label = "april_2025"
python src/main.py

# Apply to new month
config.yaml: mode = "apply_battery", patterns_label = "april_2025", apply_month = "2025-05"
python src/main.py
```

### Workflow 2: Multi-Month Training (Better Stability)
```bash
# Don't filter by month — use all data for robust patterns
config.yaml: mode = "train_all_batteries", training_month = "", patterns_label = "full_year_2025"
python src/main.py

# Apply any new data
config.yaml: mode = "apply_battery", patterns_label = "full_year_2025"
python src/main.py
```

### Workflow 3: Compare Training Periods
```bash
# Train on Period A, apply to Period B
config.yaml: mode = "train_all_batteries", training_month = "2025-03", patterns_label = "march_2025"
python src/main.py  # Generates training results

config.yaml: mode = "apply_battery", patterns_label = "march_2025", apply_month = "2025-04"
python src/main.py  # Apply March patterns to April data
# Compare results to see if patterns generalize
```

---

## Files & Directories

```
e:\time_to_empty\
├── config.yaml                    ← Configuration (edit before running)
├── src/
│   ├── main.py                   ← Entry point
│   ├── battery_manager.py        ← Multi-battery orchestration
│   ├── db.py                     ← SQLite pattern storage
│   ├── tte_ttf_algorithm.py      ← Core TTE/TTF logic
│   └── __init__.py
├── data/                         ← Input parquet files
│   ├── SE0100000092.parquet
│   ├── SE0100000093.parquet
│   └── ...
├── output/                       ← Generated results
│   ├── tte_ttf_results_SE0100000092.csv
│   ├── tte_ttf_results_SE0100000093.csv
│   └── ...
├── battery_patterns.db           ← SQLite pattern database
└── doc/                          ← Documentation
```

---

## Troubleshooting

### Error: "No parquet files found in data/"
- **Check:** Are `.parquet` files in `data/` directory?
- **Fix:** Ensure files are named `{battery_id}.parquet` (e.g., `SE0100000092.parquet`)

### Error: "Pattern label not found in database"
- **Check:** Did you run training first (`mode: train_all_batteries`)?
- **Check:** Is the `patterns_label` in apply mode the same as training mode?
- **Fix:** Run training with desired label first

### Coverage is <50%
- **Check:** Is training data sufficient (>1000 discharge rows)?
- **Check:** Are SOC values realistic (0-100%)?
- **Fix:** Try reducing `session_min_duration_minutes` to 1.0, `session_min_energy_ah` to 0.05

### TTE values look wrong
- **Check:** Are input units correct? (current in A, voltage in V, SOC in %)
- **Check:** Is capacity (FullCap) correct in data?
- **Fix:** Verify data preprocessing with sample printouts

---

## Next Steps

1. **Configure** — Edit `config.yaml` with your data paths and settings
2. **Train** — Run `python src/main.py` with `mode: train_all_batteries`
3. **Review** — Check coverage % in console output
4. **Apply** — Run with `mode: apply_battery` on new data
5. **Monitor** — Track TTE/TTF confidence over time

---

**For detailed configuration options, see:** `doc/CONFIGURATION.md`
**For algorithm details, see:** `doc/ALGORITHM.md`
**For output column definitions, see:** `doc/OUTPUT_SCHEMA.md`
