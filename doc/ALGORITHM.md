# TTE/TTF Algorithm Details

**Code:** `src/tte_ttf_algorithm.py`
**Last Updated:** 2026-04-01

This document explains how the Time To Empty (TTE) and Time To Full (TTF) estimates are calculated.

---

## Core Principle

**Instead of predicting TTE from instantaneous current (noisy), learn historical SOC decay rates and apply them.**

### Problem with Reactive Filtering
```
Naive approach: TTE = SOC% / current_rate
Issue: Current is noisy, TTE jumps around

Example:
  t=0s: Current=2A, TTE = 20% / 2A = 10 hours
  t=1s: Current=2.5A, TTE = 20% / 2.5A = 8 hours   ← Why did it drop 2 hours?
  t=2s: Current=1.8A, TTE = 20% / 1.8A = 11 hours  ← Now it rose again?
```

### Solution: Learn Historical Decay Rates
```
Training: Observe actual SOC drops under different conditions
  "At 20% SOC, steady load, 2A current → SOC drops 0.85%/min"
  "At 20% SOC, steady load, 4A current → SOC drops 1.2%/min"

Runtime: Apply learned rate to current conditions
  "Current SOC=20%, load=steady, current=3.5A"
  → Interpolate to 0.95%/min rate
  → TTE = 20% / 0.95%/min ≈ 21 minutes (stable estimate)
```

---

## Three Components

### 1. LoadClassifier
**Purpose:** Categorize discharge pattern into meaningful load classes

**Input:** Current measurements over a time window (30 samples × ~5sec = ~2.5 min window)

**Outputs:**
- `idle`: Very stable current (std < 10%)
- `steady`: Stable current (std < 20%)
- `transient`: Rapidly changing current
- `cyclic`: Repeating pattern (e.g., PWM control)

**Algorithm:**
```python
window_std = current_history.std()
window_mean = current_history.mean()

if window_std < 0.1 * window_mean:
    load_class = "idle"
elif window_std < 0.2 * window_mean:
    load_class = "steady"
elif has_cyclic_pattern(current_history):
    load_class = "cyclic"
else:
    load_class = "transient"
```

**Use:** Different SOC decay rates for different load patterns. Steady load → predictable decay.

---

### 2. SOCDecayAnalyzer
**Purpose:** Learn how fast SOC drops under specific conditions

**Inputs during training:**
- Time series: SOC values
- Metadata: Load class, current, voltage, etc.

**Output:** Database of decay rates

**Bucketing strategy:**
```
Dimensions:
  - SOC level: 10% buckets (0-10%, 10-20%, ..., 90-100%)
  - Load class: idle, steady, transient, cyclic
  - Current range: [0-0.5A, 0.5-2A, 2-5A, 5+A]  (configurable)
  - State: charging, discharging

For each bucket: Median SOC decay rate (%/min)
```

**Example learned table:**
```
SOC 20-30%, Discharge, Steady, 2-5A:  rate = 0.92%/min
SOC 20-30%, Discharge, Steady, 5+A:   rate = 1.45%/min
SOC 20-30%, Discharge, Idle, 0-0.5A:  rate = 0.05%/min
```

**Training algorithm:**
```python
for each charging/discharging session:
    for each SOC bucket:
        soc_change = soc_end - soc_start
        time_elapsed = time_end - time_start

        rate = soc_change / time_elapsed  # %/min

        load_class = classify_load(current)
        current_bucket = find_current_bucket(current)

        store(soc_bucket, load_class, current_bucket, rate)

# Aggregate: median, percentiles, sample count
```

**Why median?** Robust to outliers (e.g., sensor glitches).

---

### 3. SimpleTTECalculator
**Purpose:** Runtime estimation using learned rates + smoothing

**Algorithm:**

#### Step 1: Get Current EMA
```python
ema_factor = 2 / (ema_window_minutes * 60 / sample_interval_sec + 1)
ema_current = (1 - ema_factor) * ema_prev + ema_factor * current_new
```
**Why:** Smooth out high-frequency noise.

#### Step 2: Classify Current Load
```python
load_class = LoadClassifier.classify(current_history)
```

#### Step 3: Look Up Learned Decay Rate
```python
soc_bucket = round(current_soc / 10) * 10
current_bucket = find_bucket(ema_current)

decay_rate = lookup_table[
    soc_bucket,
    state,
    load_class,
    current_bucket
]  # %/min

# If no exact match, use fallback hierarchy:
# 1. Same bucket, broader load class (transient > cyclic > steady > idle)
# 2. Neighbor SOC bucket
# 3. Global fleet average
# 4. Hard default (0.15%/min)
```

#### Step 4: Calculate Raw TTE/TTF
```python
tte_raw = current_soc / decay_rate  # hours (assuming rate in %/min)
```

#### Step 5: Session Validation Gating
Checks if current session meets minimum criteria:

```python
session_duration = time_since_session_start  # minutes
session_energy_ah = soc_change * capacity_ah / 100

# Dual gates:
if session_duration >= 3.0 and session_energy_ah >= 0.2:
    confidence = "medium"
    valid_tte = True
elif session_duration >= 15.0 and session_energy_ah >= 1.0:
    confidence = "high"
    valid_tte = True
else:
    # Not validated yet — use carry-forward
    confidence = "medium"
    tte_raw = max(last_valid_tte - elapsed_time, 0)
    valid_tte = True  # Emit with lower confidence
```

**Gate logic:**
- **Medium gate (3min + 0.2Ah):** Emit early, broad conditions
- **High gate (15min + 1Ah):** Only after sustained activity, very confident

**Carry-forward:**
When session hasn't met medium gate, use the last valid TTE and decrement:
```python
if not session_validated:
    tte_raw = max(last_valid_tte - (elapsed_time / 60), 0)
```
**Benefit:** No hard NaN during early discharge/charge, smoother transitions.

#### Step 6: Apply EMA Smoothing
```python
if previous_tte is not None:
    smoothing_factor = 0.15  # Configurable
    tte_smooth = (1 - smoothing_factor) * previous_tte + \
                 smoothing_factor * tte_raw
else:
    tte_smooth = tte_raw  # First estimate
```

**Effect:**
```
Smoothing factor = 0.15 means:
  - New estimate: 15% weight
  - Previous estimate: 85% weight
  → Changes take ~6-7 estimates to fully propagate (smooth)

Smoothing factor = 0.3 means:
  - More responsive to changes
  - Higher jitter (noisier)
```

#### Step 7: Return Result
```python
return TTEResult(
    timestamp=ts,
    tte_hours=tte_smooth,
    ttf_hours=ttf_smooth,
    confidence=confidence,  # "high" or "medium"
    status=state,
    num_samples=samples_in_bucket,  # How much training data
    voltage_v=voltage,
    current_a=ema_current,
    ...
)
```

---

## State Determination

State determines whether to calculate TTE or TTF:

```python
net_current = ic - id  # Charge current - discharge current

if net_current > 50 mA:
    state = "charging"      → Calculate TTF, TTE=NaN
elif net_current < -50 mA:
    state = "discharging"   → Calculate TTE, TTF=NaN
else:
    state = "rest"          → Both NaN
```

**50 mA threshold:** Current noise floor, avoids false state transitions.

---

## Session Tracking

The algorithm tracks distinct charge/discharge sessions:

```
Time →

t=0s ────────────────────── t=900s ────────────────────── t=2700s
Discharge Session 1        State change           Discharge Session 2

├─ Start: session_duration=0, energy_change=0
├─ t=100s: duration=1.7min, energy=0.15Ah → NOT VALID YET
├─ t=200s: duration=3.3min, energy=0.25Ah → MEDIUM gate met!
│  └─ confidence="medium", TTE emitted
├─ t=900s: state changes → END session 1
│  └─ New session 2 starts
├─ t=1000s: duration=1.7min, energy=0.1Ah → START CARRY-FORWARD
│  └─ Use last_valid_tte from Session 1, decrement
├─ t=1100s: duration=3.3min, energy=0.2Ah → MEDIUM gate met again
│  └─ confidence="medium", TTE from new session

```

**Carry-forward prevents hard NaN gaps:**
```
Without carry-forward:
  ─ ─ ─ ─ NaN NaN NaN ─ ─ ─ ─ (ugly gap when switching sessions)

With carry-forward:
  ─ ─ ─ ─ ↘ ↘ ↘ ↗ ─ ─ ─ ─ (smooth, decrements previous TTE)
```

---

## Confidence Assignment

Two types of confidence reflect different validation levels:

### Medium Confidence (≥3 min + ≥0.2 Ah)
- Relaxed validation gate
- Earlier estimates (useful for early predictions)
- Broader condition coverage
- Typical: 20-40% of estimates

### High Confidence (≥15 min + ≥1 Ah)
- Strict validation gate
- Only after sustained activity
- Very reliable estimates
- Typical: 60-80% of estimates

**User guidance:**
```python
# For critical systems, use only high confidence
critical = df[df['confidence'] == 'high']

# For analytics/trends, include both
analytics = df[df['confidence'].isin(['high', 'medium'])]
```

---

## Fallback Hierarchy

When current conditions lack training data:

```
Level 1: Exact match
  SOC bucket, state, load_class, current_bucket

  If no data in bucket:

  ├─ Level 2: Relax load class
  │   Try: transient → cyclic → steady → idle
  │   Keep: SOC bucket, state, current_bucket
  │
  ├─ Level 3: Neighbor SOC bucket
  │   Try: ±10% SOC (e.g., 20-30% if trained on 10-20%)
  │
  ├─ Level 4: Global fleet average
  │   Aggregate across all batteries
  │   Keep: state only
  │
  └─ Level 5: Hard default
      0.15% SOC/min (conservative fallback)
```

**Example:** Battery has no data for "20% SOC, discharge, transient, 10A"
1. Try exact match → No data
2. Try "idle" load class → No data
3. Try "steady" load class → Found! Use it
4. If not, try 10-20% SOC bucket → Found! Use it
5. If not, use fleet average → Found! Use it
6. If nothing, use 0.15%/min default

---

## Training Data Requirements

### Minimum Data for Good Patterns
- **>100 discharge rows** per battery per current bucket
- **Variety of SOC levels:** Ideally data from all 10% buckets (0-10%, 10-20%, ..., 90-100%)
- **Different load patterns:** Mix of idle, steady, transient
- **Duration:** ≥7 days typically provides good coverage

### Sparse Training Data Effects
| Symptom | Cause | Fix |
|---------|-------|-----|
| Coverage <80% | Insufficient training data | Add more historical data |
| Mostly "medium" confidence | Too many fallback lookups | Retrain with richer data |
| Unrealistic TTE (0 or 1000h) | Hitting hard default | Ensure SOC varies |

---

## Tuning Guide

### Goal: High Coverage (>90%)
```yaml
# Relax session gates
session_min_duration_minutes: 1.0      # was 3.0
session_min_energy_ah: 0.05            # was 0.2
session_high_confidence_minutes: 5.0   # was 15.0
session_high_confidence_energy_ah: 0.2 # was 1.0
```

### Goal: High Confidence (>70% "high")
```yaml
# Tighten high-confidence gate
session_high_confidence_minutes: 20.0  # was 15.0
session_high_confidence_energy_ah: 2.0 # was 1.0
```

### Goal: Smooth Estimates (Less Jitter)
```yaml
tte_ttf_smoothing_factor: 0.1      # was 0.15 (less responsive)
ema_window_minutes: 30             # was 20 (smoother current)
```

### Goal: Responsive Estimates (Quick Adaptation)
```yaml
tte_ttf_smoothing_factor: 0.3      # was 0.15 (more responsive)
ema_window_minutes: 10             # was 20 (follow fast changes)
```

---

## Example Walkthrough

```
Data:
  SOC: 25% → 20% (0.5% drop)
  Time: 0:00 → 10:00 (10 minutes)
  Current: ~2.5A, steady
  State: discharge

Training database has:
  SOC 20-30%, discharge, steady, 2-5A bucket:
    - median rate: 0.92%/min
    - samples: 127

Calculation:
  1. ema_current = 2.5A (smooth)
  2. load_class = "steady"
  3. soc_bucket = 20%, state = "discharge", load_class = "steady", current = 2-5A
  4. decay_rate = 0.92%/min (from training table, 127 samples)
  5. tte_raw = 20% / 0.92%/min = 21.7 minutes = 0.362 hours

  6. Session validation:
     - duration = 10 min ≥ 3 min ✓
     - energy = 0.5% × 100Ah / 100 = 0.5 Ah ≥ 0.2 Ah ✓
     - duration = 10 min < 15 min ✗
     → confidence = "medium"

  7. Smoothing (assume previous TTE = 0.35h):
     - tte_smooth = 0.85 × 0.35 + 0.15 × 0.362 = 0.352 hours

  Output:
    timestamp: 2025-03-15T14:10:00Z
    tte_hours: 0.352
    ttf_hours: NaN
    confidence: medium
    num_samples: 127
    status: discharging
```

---

## Code Architecture

```
tte_ttf_algorithm.py
├── LoadClassifier
│   ├── classify(current_history) → load_class
│   └── Tracks 30-sample window
│
├── SOCDecayRateAnalyzer
│   ├── observe(soc, time, current, state, ...) → None
│   ├── get_rate(soc_bucket, state, load, current) → decay_rate
│   └── Database of rates per condition bucket
│
└── SimpleTTECalculator
    ├── estimate_single(soc, ...) → TTEResult
    ├── estimate_batch(dataframe) → results_df
    └── Manages session tracking, smoothing, fallbacks
```

---

## References

**Training:** `src/battery_manager.py` — Orchestrates LoadClassifier + SOCDecayAnalyzer
**Inference:** `src/tte_ttf_algorithm.py` — SimpleTTECalculator + persistence
**Storage:** `src/db.py` — SQLite pattern database

---

**Next:** See `doc/CONFIGURATION.md` for tuning parameters
**Next:** See `doc/OUTPUT_SCHEMA.md` for result interpretation
