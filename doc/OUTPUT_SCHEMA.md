# Output CSV Schema

**File Pattern:** `output/tte_ttf_results_{battery_id}.csv`
**Last Updated:** 2026-04-01

All output CSVs follow this schema. Understanding each column helps in analysis and debugging.

---

## Column Reference

### Timestamp & Identification

#### `timestamp`
**Type:** ISO 8601 datetime string
**Example:** `2025-03-15T14:32:15.000000Z`

UTC timestamp of the measurement. Corresponds to original data time.

```csv
timestamp
2025-03-15T14:32:15.000000Z
2025-03-15T14:32:20.000000Z
```

---

### Electrical Measurements

#### `voltage_v`
**Type:** Float
**Unit:** Volts
**Example:** `48.35`

Battery pack voltage at time of measurement.

**Typical values:**
- Li-ion 48V pack: 40-54V
- Li-ion 24V pack: 20-27V
- Lead-acid 48V: 42-55V

---

#### `current_a`
**Type:** Float
**Unit:** Amperes (absolute value)
**Example:** `3.45`

**Absolute** current magnitude. Use `status` column to determine direction:
- Charging (TTF mode): current flowing in
- Discharging (TTE mode): current flowing out
- Rest: current near 0

```csv
timestamp,current_a,status,tte_hours,ttf_hours
2025-03-15T14:32:15Z,3.45,discharging,12.5,NaN
2025-03-15T14:32:20Z,0.05,rest,NaN,NaN
2025-03-15T14:32:25Z,8.20,charging,NaN,5.2
```

---

### State & Capacity

#### `status`
**Type:** String
**Possible Values:** `charging` | `discharging` | `rest`

Current battery state. Determined by net current magnitude and direction.

| Status | Condition | TTE | TTF |
|--------|-----------|-----|-----|
| `discharging` | Current > 50 mA (discharging) | **Valid** | NaN |
| `charging` | Current < -50 mA (charging in) | NaN | **Valid** |
| `rest` | \|Current\| ≤ 50 mA | NaN | NaN |

---

#### `soc`
**Type:** Float
**Unit:** Percentage (0-100)
**Example:** `42.3`

State of Charge — battery capacity level.

**Valid range:** 0% (empty) to 100% (full)

**Quality checks:**
```python
# Good data
assert (df['soc'] >= 0).all() and (df['soc'] <= 100).all()

# Watch for:
# - soc > 100 or < 0 (data corruption)
# - Flat soc (sensor issue)
# - Only 2-3 soc values (not enough variation for TTE learning)
```

---

#### `capacity_ah`
**Type:** Float
**Unit:** Amp-Hours (Ah)
**Example:** `100.5`

Estimated battery capacity in Amp-Hours. Derived from `FullCap` in raw data.

**Typical values:**
- Small pack (e-bike): 0.5-5 Ah
- Medium pack (scooter): 10-50 Ah
- Large pack (vehicle): 100-400 Ah

**How TTE/TTF uses it:**
```
TTE (hours) = (current_soc / 100) × capacity_ah / effective_current_a
TTF (hours) = ((100 - current_soc) / 100) × capacity_ah / effective_current_a
```

---

### TTE/TTF Estimates

#### `tte_hours`
**Type:** Float | NaN
**Unit:** Hours
**Example:** `5.23`

**Time To Empty** — hours until battery reaches 0% SOC, assuming discharge continues at current rate.

**When populated:**
- Status = `discharging`
- Session meets validation gate (≥3 min + ≥0.2 Ah)
- Trained patterns available

**When NaN:**
- Status is `charging` or `rest`
- Not enough discharge activity yet (first few minutes)
- No training data for current conditions

**Interpretation:**
```
tte_hours = 5.23  → Battery will be empty in ~5 hours 14 minutes
tte_hours = NaN   → Cannot estimate (not enough data yet, or charging)
```

**Quality checks:**
```python
# Reasonable values?
assert df[df['tte_hours'].notna()]['tte_hours'].between(0, 100).all()

# Watch for:
# - tte_hours = 0 (SOC already at 0)
# - tte_hours > 100 (very small current, unrealistic)
# - Sudden jumps (smoothing factor too high)
```

---

#### `ttf_hours`
**Type:** Float | NaN
**Unit:** Hours
**Example:** `3.87`

**Time To Full** — hours until battery reaches 100% SOC, assuming charge continues at current rate.

**When populated:**
- Status = `charging`
- Session meets validation gate (≥3 min + ≥0.2 Ah)
- Trained patterns available

**When NaN:**
- Status is `discharging` or `rest`
- Not enough charging activity yet
- No training data for current conditions

**Interpretation:**
```
ttf_hours = 3.87  → Battery will be full in ~3 hours 52 minutes
ttf_hours = NaN   → Cannot estimate (charging too slow, not charging, or no patterns)
```

---

### Confidence & Validation

#### `confidence`
**Type:** String
**Possible Values:** `high` | `medium`

Reliability indicator for TTE/TTF estimate.

| Confidence | Validation Gate | Meaning |
|------------|-----------------|---------|
| `high` | ≥15 min + ≥1 Ah | Very reliable, strict validation |
| `medium` | ≥3 min + ≥0.2 Ah | Early estimate, broader conditions |

**How to use:**
```python
# For critical decisions, use only high confidence
critical_only = df[df['confidence'] == 'high']

# For trend analysis, can include medium
trends = df[df['confidence'].isin(['high', 'medium'])]

# Monitor confidence distribution
print(df['confidence'].value_counts(normalize=True))
# Goal: >70% high, <30% medium
```

**Carry-forward behavior:**
When a discharge session hasn't met the medium gate yet, the system uses the last valid TTE and decrements it by elapsed time. These carry-forward estimates have `confidence='medium'` and fill NaN gaps.

---

#### `num_samples`
**Type:** Integer
**Example:** `127`

Number of samples (rows) used in the TTE/TTF calculation. Indicates estimation reliability.

**What it represents:**
- How many historical training samples contributed to the learned decay rate for current conditions
- Higher = more training data, more reliable estimate

**Typical values:**
- `num_samples > 100`: Very reliable
- `num_samples > 50`: Reliable
- `num_samples 10-50`: Moderate (may need more training data)
- `num_samples < 10`: Use with caution

**Analysis:**
```python
# Which conditions have few samples?
sparse = df[df['num_samples'] < 10]
print(f"Sparse samples: {len(sparse)} / {len(df)} ({100*len(sparse)/len(df):.1f}%)")

# Retrain if >10% of data has <10 samples
```

---

### Power Metrics

#### `average_usage_kw`
**Type:** Float | NaN
**Unit:** Kilowatts (kW)
**Example:** `2.34`

Rolling 30-minute average power consumption during **discharge only**.

**Calculation:**
```
Power(kW) = Voltage(V) × Current(A) / 1,000,000
Rolling avg = 30-min centered moving average
Applied only when status='discharging'
```

**When populated:**
- Status = `discharging`
- Within a 30-minute window with discharge activity

**When NaN:**
- Status is `charging` or `rest`
- Insufficient discharge activity in recent 30-minute window

**Use cases:**
```python
# Track average power over time
df_disch = df[df['status'] == 'discharging']
power_trend = df_disch[['timestamp', 'average_usage_kw']].dropna()

# Peak power analysis
peak_power = df['average_usage_kw'].max()

# Energy calculation over time window
# Energy (Wh) = Power (kW) × Duration (hours)
```

---

## Complete Example

```csv
timestamp,voltage_v,current_a,status,soc,capacity_ah,tte_hours,ttf_hours,average_usage_kw,confidence,num_samples
2025-03-15T14:32:15.000000Z,48.35,3.45,discharging,42.3,100.5,5.23,NaN,2.34,high,127
2025-03-15T14:32:20.000000Z,48.32,3.41,discharging,42.2,100.5,5.20,NaN,2.35,high,127
2025-03-15T14:32:25.000000Z,48.28,3.50,discharging,42.1,100.5,5.18,NaN,2.33,high,128
2025-03-15T14:35:00.000000Z,48.10,0.02,rest,41.8,100.5,NaN,NaN,NaN,NaN,0
2025-03-15T14:37:15.000000Z,47.90,8.20,charging,41.8,100.5,NaN,4.52,NaN,medium,45
2025-03-15T14:37:20.000000Z,47.95,8.25,charging,41.9,100.5,NaN,4.50,NaN,medium,45
```

---

## Data Quality Checks

Run these checks on output CSVs:

### 1. Valid Timestamp Format
```python
import pandas as pd
df = pd.read_csv('output/tte_ttf_results_SE0100000092.csv')
df['timestamp'] = pd.to_datetime(df['timestamp'])
# Should not raise error
```

### 2. Valid SOC Range
```python
assert df['soc'].between(0, 100).all(), "SOC out of range [0-100]"
```

### 3. Valid Capacity
```python
assert df['capacity_ah'] > 0, "Negative or zero capacity"
assert df['capacity_ah'].std() == 0, "Capacity should be constant"  # Usually
```

### 4. TTE/TTF Consistency
```python
# TTE only in discharge, TTF only in charge
assert df[(df['status']=='discharging') & (df['tte_hours'].isna())].shape[0] < 0.1 * len(df), \
    "Too many NaN TTE in discharge (coverage <90%)"

assert df[(df['status']=='charging') & (df['ttf_hours'].isna())].shape[0] < 0.1 * len(df), \
    "Too many NaN TTF in charge (coverage <90%)"
```

### 5. Reasonable TTE/TTF Values
```python
# No negative times
assert df['tte_hours'].dropna().min() >= 0, "Negative TTE"
assert df['ttf_hours'].dropna().min() >= 0, "Negative TTF"

# No extreme values (>1000 hours likely means zero current)
assert df['tte_hours'].dropna().max() < 1000, "Unrealistic TTE (>1000 hours)"
assert df['ttf_hours'].dropna().max() < 1000, "Unrealistic TTF (>1000 hours)"
```

### 6. Confidence Distribution
```python
conf = df[df['confidence'].notna()]['confidence'].value_counts(normalize=True)
print(conf)
# Expect: >70% 'high', <30% 'medium'
if conf.get('high', 0) < 0.7:
    print("WARNING: Low confidence (high < 70%)")
```

### 7. Coverage Metrics
```python
total = len(df)
tte_cov = df[(df['status']=='discharging') & (df['tte_hours'].notna())].shape[0] / \
          df[df['status']=='discharging'].shape[0] * 100
ttf_cov = df[(df['status']=='charging') & (df['ttf_hours'].notna())].shape[0] / \
          df[df['status']=='charging'].shape[0] * 100

print(f"TTE Coverage: {tte_cov:.1f}%")
print(f"TTF Coverage: {ttf_cov:.1f}%")
# Expect: >90% for both
```

---

## Troubleshooting Output

| Issue | Likely Cause | Check |
|-------|-------------|-------|
| All NaN TTE/TTF | Wrong patterns loaded | Did training run first? Correct `patterns_label`? |
| No 'high' confidence | Gates too strict | Check session duration/energy thresholds |
| Negative SOC | Data corruption | Validate source parquet files |
| Constant SOC | Sensor error | Check raw data for variation |
| Huge TTE values (>100h) | Very low discharge current | Check current_a values; low current expected |
| TTE jumps 20h in seconds | Smoothing too low | Increase `tte_ttf_smoothing_factor` |

---

## Analysis Examples

### Calculate Battery Runtime at Current Rate
```python
df_now = df[df['status'] == 'discharging'].iloc[-1]
tte_remaining = df_now['tte_hours']
print(f"Battery will be empty in {tte_remaining:.2f} hours ({tte_remaining*60:.0f} minutes)")
```

### Find Peak Discharge Current
```python
df_disch = df[df['status'] == 'discharging']
peak_current = df_disch['current_a'].max()
peak_time = df_disch[df_disch['current_a'] == peak_current]['timestamp'].iloc[0]
print(f"Peak discharge: {peak_current:.2f} A at {peak_time}")
```

### Estimate Full Discharge Time from Current SOC
```python
current_soc = df['soc'].iloc[-1]
current_capacity = df['capacity_ah'].iloc[-1]
avg_current = df[df['status']=='discharging']['current_a'].mean()

discharge_time_hours = (current_soc / 100) * current_capacity / avg_current
print(f"Estimated full discharge: {discharge_time_hours:.1f} hours at {avg_current:.2f}A avg")
```

---

**Next:** See `doc/CONFIGURATION.md` for output settings
**Next:** See `doc/ALGORITHM.md` for how TTE/TTF is calculated
