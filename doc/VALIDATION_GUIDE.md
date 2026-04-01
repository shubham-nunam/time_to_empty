# TTE/TTF Validation Guide

**Added:** 2026-04-01
**Feature:** Validation mode for assessing TTE/TTF prediction accuracy

---

## Overview

The validation mechanism compares **predicted TTE/TTF** against **actual outcomes** to answer: "How accurate were our predictions?"

For each prediction made during a discharge session, we compute the **actual remaining time** from that point until the session ends, then compare with the predicted value.

---

## Quick Start

### 1. Train Patterns
```bash
# config.yaml
execution:
  mode: "train_all_batteries"
  patterns_label: "september_2025"

python src/main.py
# Output: output/tte_ttf_results_{battery_id}.csv
```

### 2. Run Validation
```bash
# config.yaml
execution:
  mode: "validate"
  patterns_label: "september_2025"  # Not used in validate mode, just for reference
  validate_month: ""                 # Optional: filter to specific month

python src/main.py
# Output:
#   - Console: Full validation report with all metrics
#   - File: output/validation_{battery_id}.csv
```

---

## Output: Validation Report

The console output includes five major sections:

### Section 1: Error Distribution (Gaussian Analysis)

```
GAUSSIAN ANALYSIS:
  Normality test (p>0.05):    ✓ Gaussian (p=0.342)
  Mean ± Std:                 +0.23 ± 0.91 hours
  68% within ±1σ:             [-0.68, +1.14] (69.2%)
  95% within ±2σ:             [-1.59, +2.05] (95.1%)
```

**Interpretation:**
- **Mean = +0.23**: Slight positive bias (over-predicting by ~14 minutes on average)
- **Std = 0.91**: Precision — 68% of predictions are within ±0.91 hours
- **p=0.342 (>0.05)**: Error distribution is Gaussian ✓
- **95% coverage in ±2σ**: Indicates well-behaved errors

**What this tells you:**
- If mean ≈ 0: Unbiased predictor
- If mean > 0: Consistently over-estimating remaining time
- If mean < 0: Consistently under-estimating remaining time
- If std is high: Predictions are inconsistent
- If not Gaussian: Something unusual in the error distribution (e.g., outliers, multi-modal)

---

### Section 2: Accuracy Metrics

```
ACCURACY METRICS:
  MAE (Mean Absolute Error):   0.82 hours (49 min)
  RMSE:                        0.94 hours
  MAPE:                        12.3%
  Within ±1 hour:              71.4%
  Within ±30 min:              48.3%
  Within ±15 min:              32.1%
```

**Metrics explanation:**

| Metric | Meaning |
|--------|---------|
| **MAE** | Average magnitude of error. 0.82h = on average, predictions are off by 49 minutes |
| **RMSE** | Penalizes large errors more. Use when you want to avoid big misses |
| **MAPE** | Percentage error relative to actual value. 12% error is typical for battery systems |
| **Within ±1h** | % of predictions accurate to within 1 hour. Target >70% |
| **Within ±30min** | % of predictions accurate to within 30 minutes. Target >40% |

---

### Section 3: Calibration by Confidence

```
BY CONFIDENCE LEVEL:
    HIGH: MAE=0.63h, bias=+0.18h, n= 28,433
  MEDIUM: MAE=1.24h, bias=+0.35h, n=  9,979
    LOW:  MAE=2.11h, bias=+0.89h, n=    123
```

**What this shows:**
- High confidence estimates should have **lower MAE** than medium
- Medium should be lower than low
- If they're similar: Confidence labels aren't meaningful (need retuning)

**Expected pattern:**
- High: MAE ≈ 0.5-0.7 hours
- Medium: MAE ≈ 1.0-1.5 hours
- Low: MAE ≈ 2+ hours (if enough data)

---

### Section 4: Accuracy by SOC Range

```
BY SOC RANGE:
   80-100%: MAE=1.34h, n= 8,234
   50-80%:  MAE=0.81h, n=15,421
   20-50%:  MAE=0.62h, n=12,876
    0-20%:  MAE=0.39h, n= 2,471
```

**Typical pattern:**
- **80-100%**: Least accurate (high SOC, just started discharge, uncertain conditions)
- **0-20%**: Most accurate (low SOC, battery near end, decay rates stable)

**Why?**
- At high SOC: Many hours to empty, small errors in decay rate → big relative impact
- At low SOC: Few hours to empty, errors are smaller in proportion

---

### Section 5: Temporal Consistency

```
TEMPORAL CONSISTENCY:
  Monotonicity violations:     3.2% (   1,234 /  38,412)
  Mean TTE change rate:        -0.98 (ideal ≈ -1.0)
```

**What this checks:**
- In a perfect predictor: TTE at t2 = TTE at t1 - (t2 - t1)
- If TTE "jumps up" during discharge: Something changed (confidence reassessment, state change)
- Violations: Count of rows where TTE increased when it shouldn't

**Interpretation:**
- **3.2% violations**: Normal, acceptable
- **>10% violations**: Predictions are erratic (smoothing factor too high)
- **Mean rate ≈ -1.0**: TTE decreases at about 1 hour per hour (stable)

---

## Output CSV: validation_{battery_id}.csv

```csv
timestamp,soc,status,tte_hours,actual_tte_hours,error_hours,error_pct,confidence,session_id
2025-03-15T14:32:15Z,42.3,discharging,5.23,5.10,+0.13,+2.5,high,0
2025-03-15T14:32:20Z,42.2,discharging,5.20,5.08,+0.12,+2.3,high,0
2025-03-15T14:32:25Z,42.1,discharging,5.18,5.07,+0.11,+2.1,high,0
```

**Columns:**
- `timestamp`: When prediction was made
- `soc`: State of charge at that time
- `status`: charging, discharging, or rest
- `tte_hours`: Predicted TTE at this time
- `actual_tte_hours`: Actual remaining time until session ended (+ extrapolated to 0%)
- `error_hours`: predicted - actual (positive = over-estimated)
- `error_pct`: (error / actual) * 100
- `confidence`: high or medium
- `session_id`: Which discharge session this row belongs to

Use this CSV for:
- Detailed post-mortem analysis
- Plotting error trends
- Identifying problem periods
- Machine learning model improvements

---

## Interpreting the Full Report

### Example 1: Good Performance
```
GAUSSIAN ANALYSIS:
  Mean ± Std: +0.15 ± 0.45 hours
  Normality: ✓ Gaussian (p=0.234)

ACCURACY:
  MAE: 0.35 hours (21 min)
  Within ±30min: 72%

BY CONFIDENCE:
  HIGH: MAE=0.28h
  MEDIUM: MAE=0.58h
```
→ **Verdict**: System is working well. Bias is near zero, Gaussian distribution, good separation between confidence levels.

---

### Example 2: Under-estimating
```
GAUSSIAN ANALYSIS:
  Mean ± Std: -0.89 ± 1.12 hours

ACCURACY:
  MAE: 1.02 hours
```
→ **Verdict**: Consistently under-estimating TTE (negative bias). Battery lasts longer than predicted. Decay rates are too pessimistic.

**Fix:** Retrain with more recent data, or increase `session_min_energy_ah` to be more conservative.

---

### Example 3: Over-confident
```
BY CONFIDENCE:
  HIGH: MAE=1.45h
  MEDIUM: MAE=1.38h
```
→ **Verdict**: High and medium confidence are nearly identical. Confidence labels are meaningless.

**Fix:** Increase session gates:
```yaml
session_high_confidence_minutes: 20.0  # was 15.0
session_high_confidence_energy_ah: 1.5  # was 1.0
```

---

### Example 4: Erratic Predictions
```
TEMPORAL CONSISTENCY:
  Monotonicity violations: 18%
  Mean TTE change rate: -0.42
```
→ **Verdict**: TTE jumps around too much. Not decreasing smoothly.

**Fix:** Reduce smoothing factor:
```yaml
tte_ttf_smoothing_factor: 0.08  # was 0.15
```

---

## Validation Workflow for Production

### Step 1: Baseline (Initial Training)
```bash
# Train on 3 months of data
config.yaml: training_month: ""  # all data
python src/main.py (train_all_batteries)

# Validate on same data
config.yaml: mode: validate
python src/main.py
# Note baseline metrics
```

### Step 2: Monthly Check
```bash
# After running apply_battery on new month
config.yaml: mode: validate, validate_month: "2025-05"
python src/main.py

# Compare with baseline:
# - Did MAE increase? (accuracy degraded)
# - Did mean bias shift? (systematic error appearing)
# - Did confidence calibration change?
```

### Step 3: Retrain Decision
**Retrain if:**
- MAE increases >20% from baseline
- Coverage drops below 80%
- Mean bias exceeds ±1.0 hours
- Confidence levels no longer separate

```bash
# Retrain
config.yaml: mode: train_all_batteries, patterns_label: "may_2025"
python src/main.py

# Validate new patterns
config.yaml: mode: validate, patterns_label: "may_2025"
python src/main.py
```

---

## Common Issues & Solutions

| Issue | Root Cause | Solution |
|-------|-----------|----------|
| Mean bias = +2.0h (over-estimating) | Decay rates too fast | Retrain; check if discharge patterns changed |
| MAE varies wildly by SOC | Insufficient training data in some SOC ranges | Add more historical data, reduce session gates |
| High ≈ Medium confidence | Gates too relaxed | Increase `session_high_confidence_*` |
| 20% monotonicity violations | Smoothing too low | Increase `tte_ttf_smoothing_factor` to 0.25 |
| Not Gaussian distribution | Systematic errors or outliers | Check for sensor failures or load pattern shifts |

---

## Statistical Details

### Gaussian Distribution Fit

The validation computes error = predicted_tte - actual_tte for all rows and tests if it follows a Gaussian (normal) distribution using:

- **Shapiro-Wilk test** (for n ≤ 5000 rows)
- **Normality test** (for n > 5000 rows)

**p-value interpretation:**
- p > 0.05: Distribution is Gaussian (can use mean ± std intervals)
- p < 0.05: Distribution is non-Gaussian (caution with Gaussian intervals)

**Why it matters:**
- Gaussian distribution allows confidence intervals (±1σ, ±2σ)
- Non-Gaussian suggests systematic biases or outliers

### Confidence Intervals

```
±1σ interval contains 68% of data (Gaussian property)
±2σ interval contains 95% of data
±3σ interval contains 99.7% of data

Example: Mean error = +0.2h, Std = 0.8h
  68% of predictions: +0.2 ± 0.8 = [-0.6, +1.0] hours
  95% of predictions: +0.2 ± 1.6 = [-1.4, +1.8] hours
```

---

## Advanced: Custom Analysis

Export `validation_{battery_id}.csv` and analyze with your own tools:

```python
import pandas as pd
import numpy as np

val_df = pd.read_csv('output/validation_SE0100000092.csv')

# Which rows have highest errors?
worst = val_df.nlargest(100, 'error_pct')

# How does error vary with time?
val_df['date'] = pd.to_datetime(val_df['timestamp']).dt.date
daily_mae = val_df.groupby('date')['error_hours'].apply(lambda x: np.abs(x).mean())

# Which confidence level performs best?
for conf in ['high', 'medium', 'low']:
    mae = np.abs(val_df[val_df['confidence']==conf]['error_hours']).mean()
    print(f"{conf}: MAE={mae:.2f}h")
```

---

**Related Documentation:**
- [SYSTEM_OVERVIEW.md](SYSTEM_OVERVIEW.md) — How TTE/TTF works
- [ALGORITHM.md](ALGORITHM.md) — Technical algorithm details
- [OUTPUT_SCHEMA.md](OUTPUT_SCHEMA.md) — Understanding output columns
