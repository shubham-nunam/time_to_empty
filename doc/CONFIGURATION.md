# Configuration Guide

**File:** `config.yaml`
**Last Updated:** 2026-04-01

All system behavior is controlled by settings in `config.yaml`. This guide explains each option.

---

## Execution Settings

### `execution.mode`
**Type:** String
**Options:** `train_all_batteries` | `apply_battery`
**Default:** `train_all_batteries`

Controls which operation to run.

```yaml
execution:
  mode: "train_all_batteries"  # Learn patterns from all batteries
  # OR
  mode: "apply_battery"         # Use learned patterns on new data
```

| Mode | Purpose | Input | Output | Time |
|------|---------|-------|--------|------|
| `train_all_batteries` | Learn decay rates | All `.parquet` files in `data/` | TTE/TTF CSV + DB patterns | 10-30s |
| `apply_battery` | Inference only | New data + patterns from DB | TTE/TTF CSV | 2-5s |

---

### `execution.patterns_label`
**Type:** String
**Default:** `"september_2025"`

Label for saving/loading patterns in SQLite database. Use descriptive names.

```yaml
execution:
  patterns_label: "september_2025"     # Training month
  # OR
  patterns_label: "full_year_2025"     # Full year data
  # OR
  patterns_label: "battery_type_A_v2"  # Battery type + version
```

**Important:** When switching from `train_all_batteries` to `apply_battery`, the `patterns_label` must match the patterns you want to use.

```yaml
# Training phase
execution:
  mode: "train_all_batteries"
  patterns_label: "march_2025"

# Later — apply those patterns
execution:
  mode: "apply_battery"
  patterns_label: "march_2025"  # ← Same label!
```

---

### `execution.training_month`
**Type:** String (YYYY-MM) | Empty string
**Default:** `"2025-03"`

Filter training data by month to reduce computation or study seasonal patterns.

```yaml
execution:
  training_month: ""            # ← Use ALL available data
  # OR
  training_month: "2025-03"     # ← March 2025 only
  # OR
  training_month: "2025-04"     # ← April 2025 only
```

**Use cases:**
- `""` (empty): Build robust patterns from full historical data (recommended for production)
- `"2025-03"`: Fast training, seasonal analysis (good for testing)
- `"2025-04"`: Compare seasonal differences month-to-month

**Note:** Applies only to `mode: train_all_batteries`. Ignored in apply mode.

---

### `execution.apply_month`
**Type:** String (YYYY-MM) | Empty string
**Default:** `""`

Filter apply data by month. Useful for testing patterns on specific periods.

```yaml
execution:
  apply_month: ""            # ← Apply to ALL available data
  # OR
  apply_month: "2025-03"     # ← March 2025 only
```

**Use cases:**
- `""` (empty): Apply to all new data (typical)
- `"2025-04"`: Test how March patterns perform on April data

**Note:** Applies only to `mode: apply_battery`. Ignored in training mode.

---

## Output Settings

### `output.output_dir`
**Type:** String (file path)
**Default:** `output`

Directory where result CSVs are saved.

```yaml
output:
  output_dir: output              # Relative to project root
  # OR
  output_dir: /absolute/path/out  # Absolute path
```

**Output files:**
- `tte_ttf_results_{battery_id}.csv` per battery

---

### `output.training_data_dir`
**Type:** String (file path)
**Default:** `training_data`

Directory where raw input data is expected (informational).

```yaml
output:
  training_data_dir: training_data  # Where data/ is sourced
```

---

## Database Settings

### `database.path`
**Type:** String (file path)
**Default:** `battery_patterns.db`

SQLite database file storing all learned patterns.

```yaml
database:
  path: "battery_patterns.db"        # Relative to project root
  # OR
  path: "/absolute/path/patterns.db" # Absolute path
```

**Important:** This file persists across runs. Backup before major changes.

```bash
# Backup before retraining
cp battery_patterns.db battery_patterns.db.backup
python src/main.py  # New training writes to same DB
```

---

## TTE/TTF Algorithm Settings

### `tte_ttf.current_threshold_ma`
**Type:** Float
**Default:** `50.0`
**Unit:** Milliamps

Threshold to distinguish charging from resting. Current noise floor.

```yaml
tte_ttf:
  current_threshold_ma: 50.0   # ±50 mA is noise, >50 mA is charge/discharge
```

**State classification:**
- Charging: Net current > 50 mA
- Discharging: Net current < -50 mA
- Rest: -50 mA ≤ current ≤ 50 mA

**Adjust if:**
- Frequent false state transitions: Increase to 100-200 mA
- Missing valid states: Decrease to 25-30 mA

---

### `tte_ttf.ema_window_minutes`
**Type:** Float
**Default:** `20`
**Unit:** Minutes

Exponential Moving Average (EMA) window for smoothing current measurements.

```yaml
tte_ttf:
  ema_window_minutes: 20    # Smooth over 20-min window
```

**Effect:**
- Larger window (30-40): Smoother current estimates, slower response
- Smaller window (5-10): Responsive to changes, noisier

**Typical:** 15-25 minutes for battery data

---

### Session Validation: Relaxed Gate (Medium Confidence)

#### `tte_ttf.session_min_duration_minutes`
**Type:** Float
**Default:** `3.0`
**Unit:** Minutes

Minimum session duration before emitting **medium confidence** TTE/TTF.

```yaml
tte_ttf:
  session_min_duration_minutes: 3.0   # Emit estimate after 3 min of discharge
```

#### `tte_ttf.session_min_energy_ah`
**Type:** Float
**Default:** `0.2`
**Unit:** Amp-Hours

Minimum SOC change (energy) before emitting **medium confidence** TTE/TTF.

```yaml
tte_ttf:
  session_min_energy_ah: 0.2  # After 0.2 Ah of discharge
```

**Combined Gate:**
- TTE emitted when **BOTH**: duration ≥ 3 min **AND** energy ≥ 0.2 Ah
- Confidence assigned: `"medium"`
- Coverage: Higher (more rows have TTE/TTF)

**Adjust if:**
- Coverage too low (<80%): Reduce both (try 1.0 min, 0.05 Ah)
- Too many false positives: Increase both (try 5 min, 0.5 Ah)

---

### Session Validation: Strict Gate (High Confidence)

#### `tte_ttf.session_high_confidence_minutes`
**Type:** Float
**Default:** `15.0`
**Unit:** Minutes

Minimum session duration for **high confidence** TTE/TTF.

```yaml
tte_ttf:
  session_high_confidence_minutes: 15.0  # Very reliable after 15 min
```

#### `tte_ttf.session_high_confidence_energy_ah`
**Type:** Float
**Default:** `1.0`
**Unit:** Amp-Hours

Minimum SOC change for **high confidence** TTE/TTF.

```yaml
tte_ttf:
  session_high_confidence_energy_ah: 1.0  # After 1 Ah of change
```

**Combined Gate:**
- Confidence escalated to `"high"` when **BOTH**: duration ≥ 15 min **AND** energy ≥ 1 Ah
- Only most reliable estimates marked high
- Typical: 30-40% of estimates are high confidence

**Tuning:**
- Too few high-confidence: Relax (try 10 min, 0.5 Ah)
- Not strict enough: Tighten (try 20 min, 2 Ah)

---

### `tte_ttf.tte_ttf_smoothing_factor`
**Type:** Float (0.0 - 1.0)
**Default:** `0.15`

Exponential smoothing factor for TTE/TTF values. Controls estimate stability.

```yaml
tte_ttf:
  tte_ttf_smoothing_factor: 0.15   # Smooth: 0.1-0.2, Responsive: 0.3-0.5
```

**Formula:**
```
tte_smooth = (1 - factor) × tte_prev + factor × tte_new
```

**Effect:**
- **0.05** (very smooth): TTE changes slowly, lags real conditions
- **0.15** (smooth): Good balance, default
- **0.3** (responsive): Quick response, more jitter
- **0.5** (very responsive): Follows every change, noisy

**Adjust if:**
- TTE jumps erratically: Decrease to 0.05-0.1
- TTE too stale: Increase to 0.25-0.4

---

### `tte_ttf.current_thresholds_a`
**Type:** List of floats
**Default:** `[0.5, 2.0, 5.0]`
**Unit:** Amperes

Current range thresholds for bucketing learned decay rates. Defines current "buckets."

```yaml
tte_ttf:
  current_thresholds_a: [0.5, 2.0, 5.0]
  # Creates buckets:
  #   - 0.0-0.5 A (very low load)
  #   - 0.5-2.0 A (low load)
  #   - 2.0-5.0 A (medium load)
  #   - 5.0+ A (high load)
```

**Adjust based on actual discharge current distribution:**

```bash
# Analyze your data
df['pack_current'].describe()
# Look at percentiles: p25, p60, p85

# Example if p25=0.3, p60=1.2, p85=4.0
# Use: [0.3, 1.2, 4.0]
```

**Why adjust?**
- Too few buckets: Loss of granularity
- Too many buckets: Overfitting, sparse training data
- Unbalanced buckets: Some buckets have no training data

---

### `tte_ttf.usage_window_minutes`
**Type:** Float
**Default:** `30`
**Unit:** Minutes

Rolling window for calculating average power during discharge (`average_usage_kw` column).

```yaml
tte_ttf:
  usage_window_minutes: 30   # 30-min rolling average
```

**Use case:** Track average discharge power over time.

**Adjust:**
- Shorter window (5-10 min): Fine-grained, noisy
- Longer window (60+ min): Smooth, less responsive

---

### `tte_ttf.min_discharge_rows`
**Type:** Integer
**Default:** `100`

Minimum discharge rows needed for training. Warnings if data is sparse.

```yaml
tte_ttf:
  min_discharge_rows: 100   # Warn if <100 discharge samples
```

**What it does:**
- If training data has <100 discharge rows, console warning printed
- Training still proceeds (uses available data)
- High sensitivity to sparse data

**Adjust:**
- Stricter check: Increase to 500-1000
- Lenient (for small datasets): Decrease to 20-50

---

### `tte_ttf.default_discharge_rate_pct_per_min`
**Type:** Float
**Default:** `0.15`

Fallback discharge rate (% SOC per minute) when no training data or all fallbacks fail.

```yaml
tte_ttf:
  default_discharge_rate_pct_per_min: 0.15   # 0.15%/min ≈ 11 hours full discharge
```

**When used:**
- New battery with no training data
- All learned patterns missing for current conditions
- Last resort estimate

**Adjust based on battery chemistry:**
- Li-ion (typical): 0.10-0.20
- Lead-acid (lower capacity): 0.05-0.10
- Ultra-capacitor: 0.5-2.0

---

## Complete Example Configurations

### Example 1: Production — Monthly Patterns
```yaml
execution:
  mode: "train_all_batteries"
  patterns_label: "april_2025"
  training_month: "2025-04"          # Current month
  apply_month: ""

tte_ttf:
  current_threshold_ma: 50.0
  ema_window_minutes: 20
  session_min_duration_minutes: 3.0
  session_min_energy_ah: 0.2
  session_high_confidence_minutes: 15.0
  session_high_confidence_energy_ah: 1.0
  tte_ttf_smoothing_factor: 0.15
  current_thresholds_a: [0.5, 2.0, 5.0]
  usage_window_minutes: 30
  default_discharge_rate_pct_per_min: 0.15
```

### Example 2: Full-Year Robust Patterns
```yaml
execution:
  mode: "train_all_batteries"
  patterns_label: "full_year_2025"
  training_month: ""                 # ← ALL data
  apply_month: ""

tte_ttf:
  current_threshold_ma: 50.0
  ema_window_minutes: 20
  session_min_duration_minutes: 3.0
  session_min_energy_ah: 0.2
  session_high_confidence_minutes: 15.0
  session_high_confidence_energy_ah: 1.0
  tte_ttf_smoothing_factor: 0.15
  current_thresholds_a: [0.5, 2.0, 5.0]
  usage_window_minutes: 30
  default_discharge_rate_pct_per_min: 0.15
```

### Example 3: Apply Patterns
```yaml
execution:
  mode: "apply_battery"
  patterns_label: "full_year_2025"   # ← Load these patterns
  apply_month: "2025-05"             # Apply to May

# tte_ttf section not used in apply mode
```

### Example 4: Testing — Loose Gates for Coverage
```yaml
execution:
  mode: "train_all_batteries"
  patterns_label: "test_loose"
  training_month: ""

tte_ttf:
  current_threshold_ma: 30.0          # ← Tighter state detection
  ema_window_minutes: 10              # ← More responsive
  session_min_duration_minutes: 1.0   # ← Very relaxed
  session_min_energy_ah: 0.05         # ← Minimal validation
  session_high_confidence_minutes: 5.0
  session_high_confidence_energy_ah: 0.2
  tte_ttf_smoothing_factor: 0.3       # ← More responsive
  current_thresholds_a: [0.3, 1.0, 3.0, 10.0]  # ← More buckets
  usage_window_minutes: 10            # ← Finer granularity
  default_discharge_rate_pct_per_min: 0.2
```

---

## Troubleshooting Configuration

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| "Pattern not found in database" | Wrong `patterns_label` in apply mode | Verify training and apply modes use same label |
| Coverage <50% | Gates too strict | Reduce `session_min_*` values |
| All results are NaN | Wrong data format | Check units (current in A, SOC in %) |
| TTE jumps erratically | Smoothing too low | Increase `tte_ttf_smoothing_factor` to 0.25 |
| Training takes >1 minute | Too much data | Set `training_month` to filter by month |
| Mostly "medium" confidence | Gates too relaxed | Increase `session_high_confidence_*` values |

---

## Advanced: Seasonal Tuning

Different seasons may need different thresholds:

```bash
# Train each season separately
config.yaml: patterns_label = "winter_2025", training_month = "2025-01"
python src/main.py

config.yaml: patterns_label = "summer_2025", training_month = "2025-07"
python src/main.py

# Later, apply seasonal patterns as needed
config.yaml: mode = "apply_battery", patterns_label = "winter_2025", apply_month = "2025-02"
python src/main.py  # Apply winter patterns to February
```

---

**Next:** See `doc/SYSTEM_OVERVIEW.md` for execution workflow
**Next:** See `doc/ALGORITHM.md` for technical details
