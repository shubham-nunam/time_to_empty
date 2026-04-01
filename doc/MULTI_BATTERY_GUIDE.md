# Multi-Battery Support - Train All, Apply Any

**Status:** ✅ IMPLEMENTED
**Date:** 2026-03-31

---

## Overview

You can now:
- **Train on multiple batteries** in one run (auto-discover all `.parquet` files)
- **Save patterns per battery** (pickle format, organized by battery ID)
- **Apply patterns** to any specific battery without retraining

---

## Scenario 1: Train All Batteries at Once

**Goal:** You have 5 battery packs (SE0100000092, SE0100000093, SE0100000094, etc.) in `data/` folder. Train each separately.

### Setup

**File Structure:**
```
data/
├── SE0100000092.parquet     ← Battery 1
├── SE0100000093.parquet     ← Battery 2
├── SE0100000094.parquet     ← Battery 3
└── ...                       ← More batteries
```

**Configuration (`config.yaml`):**
```yaml
execution:
  mode: "train_all_batteries"      # Train all batteries
  save_patterns: true
  patterns_label: "september_2025"
```

**Command:**
```bash
python src/main.py
```

### What Happens

```
[1] Discover batteries
    ✅ SE0100000092
    ✅ SE0100000093
    ✅ SE0100000094
    ✅ SE0100000095

[2] Train each battery separately
    ├─ SE0100000092: Load → Preprocess → Train → Estimate → Save patterns
    ├─ SE0100000093: Load → Preprocess → Train → Estimate → Save patterns
    ├─ SE0100000094: Load → Preprocess → Train → Estimate → Save patterns
    └─ SE0100000095: Load → Preprocess → Train → Estimate → Save patterns

[3] Patterns saved
    outputs/patterns/
    ├── SE0100000092_september_2025/
    │   ├── soc_decay_analyzer.pkl
    │   ├── load_classifier.pkl
    │   └── metadata.pkl
    ├── SE0100000093_september_2025/
    │   ├── soc_decay_analyzer.pkl
    │   ├── load_classifier.pkl
    │   └── metadata.pkl
    ├── SE0100000094_september_2025/
    └── SE0100000095_september_2025/

[4] Results saved
    outputs/
    ├── tte_ttf_SE0100000092.csv
    ├── tte_ttf_SE0100000093.csv
    ├── tte_ttf_SE0100000094.csv
    └── tte_ttf_SE0100000095.csv
```

**Time:** ~40 seconds for 4 batteries (10s per battery)

---

## Scenario 2: Apply Patterns to Specific Battery

**Goal:** You have trained patterns from September. Now it's October. Apply SE0100000092's patterns to new October data.

### Setup

**Configuration (`config.yaml`):**
```yaml
execution:
  mode: "apply_battery"              # Apply to one battery
  battery_id: "SE0100000092"         # Which battery to apply
  patterns_label: "september_2025"   # Which patterns to load
```

**Data File:**
```
data/
└── SE0100000092.parquet    ← New October data
```

**Command:**
```bash
python src/main.py
```

### What Happens

```
[1] Load data for SE0100000092
    ✅ Loaded 67,000 rows

[2] Preprocess

[3] Load patterns
    ✅ From: outputs/patterns/SE0100000092_september_2025/
    ✅ Loaded: soc_decay_analyzer.pkl
    ✅ Loaded: load_classifier.pkl

[4] Estimate TTE/TTF
    (using LOADED patterns, NO retraining!)

[5] Save results
    outputs/tte_ttf_SE0100000092_applied.csv
```

**Time:** ~2 seconds (no training!)

---

## Scenario 3: Train Different Batteries at Different Times

You might want to:
- Train battery A in September
- Train battery B in October
- Apply both in November

**Workflow:**

### Step 1: Train Battery A (September)
```yaml
# config.yaml
execution:
  mode: "train_all_batteries"
  patterns_label: "september_2025"
data:
  input_file: "data/SE0100000092.parquet"  # Only A
```
```bash
python src/main.py
# Saves to: outputs/patterns/SE0100000092_september_2025/
```

### Step 2: Train Battery B (October)
```yaml
# config.yaml
execution:
  mode: "train_all_batteries"
  patterns_label: "october_2025"
data:
  input_file: "data/SE0100000093.parquet"  # Only B
```
```bash
python src/main.py
# Saves to: outputs/patterns/SE0100000093_october_2025/
```

### Step 3: Apply Both in November
```bash
# Apply A with September patterns
python src/main.py  [mode: apply_battery, battery_id: SE0100000092, patterns_label: september_2025]

# Apply B with October patterns
python src/main.py  [mode: apply_battery, battery_id: SE0100000093, patterns_label: october_2025]
```

---

## Pattern Storage (Pickle Format)

Each battery's patterns are stored as **pickle files**:

```
outputs/patterns/SE0100000092_september_2025/
├── soc_decay_analyzer.pkl       ← SOC decay rates (learned from data)
├── load_classifier.pkl          ← Load classification (learned from data)
└── metadata.pkl                 ← Metadata (battery_id, label, params)
```

**Why pickle?**
- ✅ Fast to save and load (< 1ms)
- ✅ Preserves Python objects exactly
- ✅ Compact (binary format)
- ✅ No need for JSON serialization complexity

---

## BatteryManager API

If you need to work with patterns programmatically:

```python
from src.battery_manager import BatteryManager

# Initialize
mgr = BatteryManager(
    data_dir="data",
    patterns_dir="outputs/patterns"
)

# Discover all batteries in data folder
batteries = mgr.discover_batteries()
# Returns: {'SE0100000092': Path(...), 'SE0100000093': Path(...), ...}

# List saved patterns by battery
patterns = mgr.list_battery_patterns()
# Returns: {'SE0100000092': ['september_2025', 'october_2025'], ...}

# Save patterns for a battery
battery_mgr.save_battery_patterns(
    battery_id='SE0100000092',
    calculator_obj=calculator,
    label='september_2025'
)

# Load patterns for a battery
battery_mgr.load_battery_patterns(
    battery_id='SE0100000092',
    calculator_obj=calculator,
    label='september_2025'
)

# Print available batteries and patterns
mgr.print_available_batteries()
```

---

## Command Reference

### Train All Batteries
```yaml
# config.yaml
execution:
  mode: "train_all_batteries"
  patterns_label: "september_2025"
```

### Apply Specific Battery
```yaml
# config.yaml
execution:
  mode: "apply_battery"
  battery_id: "SE0100000092"
  patterns_label: "september_2025"
```

### List Available Batteries and Patterns
```python
from src.battery_manager import BatteryManager
mgr = BatteryManager()
mgr.print_available_batteries()
```

---

## Output Files

### From TRAIN_ALL_BATTERIES
```
outputs/
├── tte_ttf_SE0100000092.csv         (results for battery 1)
├── tte_ttf_SE0100000093.csv         (results for battery 2)
├── tte_ttf_SE0100000094.csv         (results for battery 3)
└── patterns/
    ├── SE0100000092_september_2025/
    │   ├── soc_decay_analyzer.pkl
    │   ├── load_classifier.pkl
    │   └── metadata.pkl
    ├── SE0100000093_september_2025/
    └── SE0100000094_september_2025/
```

### From APPLY_BATTERY
```
outputs/
└── tte_ttf_SE0100000092_applied.csv  (results using loaded patterns)
```

---

## Decision Tree

```
Do you have multiple batteries?
├─ YES
│  ├─ Want to train all? → mode: "train_all_batteries"
│  └─ Want to apply one? → mode: "apply_battery" + battery_id
└─ NO
   ├─ Want to learn patterns? → mode: "train_test_split" or "train_only"
   └─ Want to apply patterns? → mode: "apply"
```

---

## Example: Fleet Deployment

```
Month 1: Learn
┌─────────────────────────────────────┐
│ All 10 battery packs in data/       │
│ python src/main.py                  │
│ [mode: train_all_batteries]         │
│                                     │
│ Output: patterns for all 10 packs   │
└─────────────────────────────────────┘

Month 2: Deploy
┌─────────────────────────────────────┐
│ New data for each pack              │
│ python src/main.py × 10 times       │
│ [mode: apply_battery, battery_id]   │
│                                     │
│ ⚡ Fast! No retraining              │
│ Output: results for all 10 packs    │
└─────────────────────────────────────┘
```

---

## Troubleshooting

### Error: No battery files found
**Cause:** Files in `data/` don't have `.parquet` extension or folder doesn't exist

**Solution:**
```bash
ls -la data/
# Should show: battery_1.parquet, battery_2.parquet, etc.
```

### Error: Pattern not found for battery
**Cause:** Patterns not trained yet, or label mismatch

**Solution:**
```python
from src.battery_manager import BatteryManager
mgr = BatteryManager()
mgr.print_available_batteries()
# Check what patterns exist
```

### Slow on many batteries?
**Tip:** Consider training in parallel (future enhancement)
- Currently: Sequential (one battery at a time)
- Each battery: ~10 seconds

---

## Summary

✅ **TRAIN_ALL_BATTERIES:** Auto-discover and train all batteries
✅ **APPLY_BATTERY:** Apply saved patterns to specific battery
✅ **Pickle format:** Fast save/load, no JSON complexity
✅ **Fleet-ready:** Designed for multi-pack deployments

**Next:** Use config.yaml to switch between modes!

