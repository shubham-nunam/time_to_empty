# TTE/TTF Operational Guide - Train, Test, Apply

**Last Updated:** 2026-03-31

---

## Quick Summary

You now have **three operational modes** for running the TTE/TTF system:

| Mode | Purpose | Training | Output |
|------|---------|----------|--------|
| **TRAIN_TEST_SPLIT** | Learn patterns from historical data, validate on recent data | YES (on train set) | patterns/, train_results, test_results, comparison |
| **TRAIN_ONLY** | Learn patterns from all data, save for reuse | YES (all data) | patterns/, full_results |
| **APPLY** | Use previously trained patterns on new data | NO | applied_results |

---

## Scenario 1: Learning Phase (Train-Test Split)

**Goal:** Learn from Sept 1-25 data, validate on Sept 26-30 data

**Configuration (config.yaml):**
```yaml
execution:
  mode: "train_test_split"
  train_date_start: "2025-09-01"
  train_date_end: "2025-09-25"
  test_date_start: "2025-09-26"
  test_date_end: "2025-09-30"
  save_patterns: true
  patterns_label: "september_2025"
```

**Command:**
```bash
python src/main.py
```

**What Happens:**
1. Load full September data
2. Preprocess (DTO, time columns, state determination)
3. Split into train (Sept 1-25) and test (Sept 26-30) sets
4. **Train** algorithm on Sept 1-25 data
   - Learns SOC decay rates at different current levels
   - Learns load classification patterns
5. **Estimate** on both train and test sets
6. **Save** patterns to: `outputs/patterns/september_2025_<timestamp>/`
7. **Compare** metrics between train and test
8. Print train vs test comparison report
9. Save comparison CSV: `outputs/train_test_comparison.csv`

**Output Files:**
```
outputs/
├── tte_ttf_train_results.csv       (Sept 1-25 estimates)
├── tte_ttf_test_results.csv        (Sept 26-30 estimates)
├── train_test_comparison.csv       (side-by-side metrics)
└── patterns/
    └── september_2025_20260331_120000/
        ├── metadata.json           (when trained, parameters)
        ├── soc_decay_analyzer.pkl  (learned decay rates)
        └── load_classifier.pkl     (learned load patterns)
```

**Success Criteria:**
- ✅ TTE coverage > 90% (discharge samples)
- ✅ Test coverage similar to train (no major distribution shift)
- ✅ Mean TTE difference < 5% between train and test
- ✅ Patterns saved successfully

---

## Scenario 2: Learning Phase (Train All Data)

**Goal:** Learn from all available data, save patterns for production

**Configuration (config.yaml):**
```yaml
execution:
  mode: "train_only"
  save_patterns: true
  patterns_label: "september_all_data"
```

**Command:**
```bash
python src/main.py
```

**What Happens:**
1. Load full September data
2. Preprocess
3. **Train** algorithm on ALL data
4. **Estimate** TTE/TTF on all data
5. **Save** patterns to: `outputs/patterns/september_all_data_<timestamp>/`

**Output Files:**
```
outputs/
├── tte_ttf_results_full.csv
└── patterns/
    └── september_all_data_20260331_120000/
        ├── metadata.json
        ├── soc_decay_analyzer.pkl
        └── load_classifier.pkl
```

---

## Scenario 3: Apply Learned Patterns (Production/Testing)

**Goal:** Process NEW data using previously trained patterns (no retraining)

### Option A: Auto-Find Latest Pattern

**Configuration (config.yaml):**
```yaml
execution:
  mode: "apply"
  pattern_path: null                    # Leave null to auto-find
  pattern_label_filter: "september"     # Find patterns with "september" in label
data:
  input_file: data/SE0100000092_OCTOBER.parquet  # New data file
```

**Command:**
```bash
python src/main.py
```

**What Happens:**
1. Load new data (October parquet file)
2. Preprocess
3. **Find** latest pattern matching "september" label
4. **Load** patterns (no training)
5. **Estimate** TTE/TTF on new data using loaded patterns
6. Save results: `outputs/tte_ttf_results_applied.csv`

### Option B: Specify Exact Pattern Path

**Configuration (config.yaml):**
```yaml
execution:
  mode: "apply"
  pattern_path: "outputs/patterns/september_2025_20260331_120000"  # Explicit path
data:
  input_file: data/SE0100000092_OCTOBER.parquet
```

**Command:**
```bash
python src/main.py
```

**Output:**
```
outputs/
└── tte_ttf_results_applied.csv    (October estimates using September patterns)
```

---

## Scenario 4: Monthly Processing (Legacy Mode)

**Goal:** Process single month, learn and estimate (backward compatible)

**Configuration (config.yaml):**
```yaml
execution:
  mode: "monthly"
  month: "2025-10"
data:
  input_file: data/SE0100000092.parquet  # Full data (filtered by month)
```

**Command:**
```bash
python src/main.py
```

**Output:**
```
outputs/
└── tte_ttf_results_2025-10.csv
```

---

## Scenario 5: Full Dataset Processing

**Goal:** Process entire file, learn and estimate

**Configuration (config.yaml):**
```yaml
execution:
  mode: "full"
data:
  input_file: data/SE0100000092.parquet
```

**Command:**
```bash
python src/main.py
```

**Output:**
```
outputs/
└── tte_ttf_results_full.csv
```

---

## Pattern Management

### List Available Patterns

```python
from src.pattern_manager import PatternManager

mgr = PatternManager("outputs/patterns")
patterns = mgr.list_patterns()

for p in patterns:
    print(f"Label: {p['label']}")
    print(f"Path:  {p['path']}")
    print(f"Saved: {p['saved_at']}")
```

### Get Latest Pattern

```python
mgr = PatternManager("outputs/patterns")
latest = mgr.get_latest_pattern(label_filter="september")
print(f"Latest pattern: {latest}")
```

### Manually Load Patterns

```python
from src.pattern_manager import PatternManager
from src.tte_ttf_algorithm import TTETTFCalculator

# Create calculator
calc = TTETTFCalculator(...)

# Load patterns
mgr = PatternManager("outputs/patterns")
mgr.load_patterns("outputs/patterns/september_2025_20260331_120000", calc)

# Now use calc.estimate_batch() with new data
```

---

## Metrics & Reporting

### Auto-Generated Reports (Train-Test Mode)

When running **TRAIN_TEST_SPLIT**, you get:

1. **Console Output:** Side-by-side comparison table
   ```
   [TRAIN vs TEST COMPARISON REPORT]

   Metric                         Training             Testing
   ───────────────────────────────────────────────────────
   Total samples                      54,632               18,608
   TTE coverage                        98.5%               97.8%
   Mean TTE (hours)                    5.23                5.19
   Std TTE (hours)                     2.15                2.18
   TTE drift (hours)                  +0.04               -0.02
   ```

2. **Comparison CSV:** `outputs/train_test_comparison.csv`
   ```
   Dataset,Total_Samples,TTE_Valid,TTE_Valid_Pct,TTE_Mean,TTE_Std,TTE_Min,TTE_Max,TTE_Median
   Training,54632,53781,98.45,5.23,2.15,0.05,18.73,5.12
   Testing,18608,18207,97.84,5.19,2.18,0.08,19.02,5.08
   ```

### Manual Metrics Calculation

```python
from src.metrics_calculator import MetricsCalculator
import pandas as pd

# Load results
results = pd.read_csv('outputs/tte_ttf_test_results.csv')

# Compute all metrics
calc = MetricsCalculator(results)
metrics = calc.compute_all()

# Print summary
calc.print_summary()
```

---

## Decision Logic: When to Train vs Apply

### Train (TRAIN_TEST_SPLIT or TRAIN_ONLY)
- [ ] Starting fresh with new battery pack data
- [ ] Significant change in usage patterns
- [ ] Software update / algorithm change
- [ ] Coverage drops below 80%
- [ ] Mean TTE diverges > 2 hours between training and testing
- [ ] Stability (std dev) increases > 50%

### Apply (APPLY)
- [ ] Processing new data from same battery pack
- [ ] Same time period (data comes from same BMS firmware)
- [ ] Patterns already learned and saved
- [ ] No major changes in usage patterns

### Retraining Decision
```
IF (coverage < 80%) OR (std_dev_increase > 50%) OR (drift > 1 hour):
    → Run TRAIN_ONLY with new data
    → Save new patterns
    → Test on next batch before production
ELSE:
    → Use existing patterns with APPLY mode
    → Monitor metrics in output
```

---

## Troubleshooting

### Error: No patterns found

**Cause:** Trying to use APPLY mode without having trained first

**Solution:**
1. Run TRAIN_TEST_SPLIT or TRAIN_ONLY first
2. Check patterns directory: `outputs/patterns/`
3. Use correct pattern_path in config.yaml

### Error: TTE coverage too low (< 50%)

**Cause:** Session thresholds too strict

**Solution:** In config.yaml, reduce thresholds:
```yaml
tte_ttf:
  session_min_duration_minutes: 5      # ↓ from 15 (more frequent sessions)
  session_min_energy_ah: 0.3           # ↓ from 1.0 (lower energy bar)
  tte_ttf_smoothing_factor: 0.2        # ↑ to be more responsive
```

### Error: TTE values jumping wildly

**Cause:** Smoothing factor too high (too responsive)

**Solution:** In config.yaml, increase stability:
```yaml
tte_ttf:
  tte_ttf_smoothing_factor: 0.1        # ↓ from 0.15 (more conservative)
  session_min_duration_minutes: 20     # ↑ from 15 (longer sessions)
```

---

## Command Reference

```bash
# TRAIN_TEST_SPLIT (learn Sept 1-25, test Sept 26-30)
# config.yaml: execution.mode = "train_test_split"
python src/main.py

# TRAIN_ONLY (learn all September data)
# config.yaml: execution.mode = "train_only"
python src/main.py

# APPLY (process October data with learned patterns)
# config.yaml: execution.mode = "apply"
#             data.input_file = "data/SE0100000092_OCTOBER.parquet"
python src/main.py

# FULL (process all data in file)
# config.yaml: execution.mode = "full"
python src/main.py

# MONTHLY (process single month)
# config.yaml: execution.mode = "monthly"
#             execution.month = "2025-09"
python src/main.py
```

---

## Output Files Explained

### tte_ttf_results_*.csv

Standard TTE/TTF output with columns:
- `timestamp`: UTC time
- `voltage_v`: Terminal voltage (mV)
- `current_a`: Discharge/charge current (A)
- `soc`: State of Charge (%)
- `tte_hours`: Time to Empty estimate
- `ttf_hours`: Time to Full estimate
- `status`: charging / discharging / rest
- `confidence`: low / medium / high
- `num_samples`: Session sample count

### patterns/metadata.json

```json
{
  "label": "september_2025",
  "timestamp": "20260331_120000",
  "saved_at": "2026-03-31T12:00:00",
  "files": {
    "soc_decay_analyzer": "...",
    "load_classifier": "..."
  },
  "calculator_params": {
    "session_min_duration_minutes": 15.0,
    "session_min_energy_ah": 1.0,
    "tte_ttf_smoothing_factor": 0.15
  }
}
```

---

## Performance Tips

1. **Faster estimation:** Increase batch_size in estimate_batch() (larger memory usage)
2. **More stable:** Decrease tte_ttf_smoothing_factor (more conservative)
3. **Better coverage:** Decrease session_min_duration_minutes and session_min_energy_ah
4. **Smarter patterns:** Train on longer periods (e.g., month instead of week)

---

## Next Steps

1. **First run:** Use TRAIN_TEST_SPLIT to validate algorithm on your data
2. **Review metrics:** Check train vs test comparison report
3. **Deploy:** Use TRAIN_ONLY for full dataset, save patterns
4. **Production:** Switch to APPLY mode for new incoming data
5. **Monitor:** Track coverage and stability in outputs
6. **Retrain:** When metrics degrade, use TRAIN_ONLY again

