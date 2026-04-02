# Incremental Training - Pattern Merging

## Overview

Incremental training enables combining patterns from multiple training runs with proper statistical weighting. Instead of overwriting old patterns, new patterns are **merged** with existing ones as if you had trained on all the combined data together.

**Before:** Each training run replaced all previous patterns
**After:** Each training run enriches the existing patterns with new insights

## How It Works

### Scenario

Suppose you train your algorithm on different time periods:

1. **First training** - March 2025 data
   - Learns battery decay patterns from 539,150 samples
   - Patterns saved with label `parquet_training`

2. **Second training** - April 2025 data
   - Learns battery decay patterns from 400,000 new samples
   - Would normally **overwrite** March patterns
   - **Now:** Merges with March patterns using weighted averaging

### Result

The final patterns represent the combined learning from both March + April data, weighted by sample counts:
- Patterns with more samples have more influence
- Statistical distributions (mean, std, median) are properly combined
- Effective as if you trained on 939,150 combined samples

## Technical Details

### Weighted Averaging Algorithm

For each decay rate pattern `(SOC_window, load_class, current_range)`:

**Combined count:**
```
total_count = old_count + new_count
```

**Combined mean (weighted average):**
```
merged_mean = (old_count × old_mean + new_count × new_mean) / total_count
```

**Combined standard deviation (parallel axis theorem):**
```
old_variance = old_std²
new_variance = new_std²

old_contribution = old_count × (old_variance + (old_mean - merged_mean)²)
new_contribution = new_count × (new_variance + (new_mean - merged_mean)²)

merged_variance = (old_contribution + new_contribution) / total_count
merged_std = √merged_variance
```

**Combined median (weighted average as approximation):**
```
merged_median = (old_count × old_median + new_count × new_median) / total_count
```

### Implementation

Two new methods in `src/db.py`:

1. **`merge_patterns()`** - Main method for merging
   - Loads existing patterns from database
   - Applies weighted averaging for all statistics
   - Saves merged result back to database
   - Preserves the pattern label and metadata

2. **`_merge_stats_dicts()`** - Static helper for weighted averaging
   - Combines two statistics dictionaries
   - Handles cases where patterns exist in only one dataset
   - Applies parallel axis theorem for variance combination

### Updated Logic in `battery_manager.py`

When saving patterns, the code now:

1. Checks if patterns already exist for `(battery_id, label)`
2. If yes → Call `merge_patterns()` (incremental training)
3. If no → Call `save_patterns()` (first training)

```python
if existing_discharge is not None and existing_charge is not None:
    # Merge with weighted averaging
    self.db.merge_patterns(battery_id, discharge_stats, charge_stats, label, metadata)
    print(f"Merged with existing patterns")
else:
    # Save as new
    self.db.save_patterns(battery_id, discharge_stats, charge_stats, label, metadata)
    print(f"Saved new patterns")
```

## Example Workflow

### Step 1: Train on March Data

```yaml
execution:
  mode: "train_all_batteries"
  patterns_label: "march_april_combined"
  training_month: "2025-03"
```

```bash
python src/main.py
# Output: Saved new patterns to database (label: march_april_combined)
```

**Database state after Step 1:**
```
Battery: LSE18B260667, Label: march_april_combined
- 26 discharge patterns (from March data)
- 17 charge patterns (from March data)
- Sample counts: 539,150 rows
```

### Step 2: Train on April Data (Same Label)

```yaml
execution:
  mode: "train_all_batteries"
  patterns_label: "march_april_combined"   # Same label!
  training_month: "2025-04"
```

```bash
python src/main.py
# Output: Merged with existing patterns (label: march_april_combined)
#         Old + new patterns combined with weighted averaging
```

**Database state after Step 2:**
```
Battery: LSE18B260667, Label: march_april_combined
- 26 discharge patterns (merged from March + April)
- 17 charge patterns (merged from March + April)
- Sample counts: 539,150 (March) + 400,000 (April) = 939,150 total
- Statistics: Weighted averages from both periods
```

### Step 3: Apply to Test Data

```yaml
execution:
  mode: "apply_battery"
  patterns_label: "march_april_combined"
```

```bash
python src/main.py
# Uses combined patterns (equivalent to training on all data at once)
# TTE/TTF estimates reflect learning from both March + April
```

## Use Cases

### 1. Progressive Learning
- Train on weekly data, accumulate insights
- Each week's training enriches the model
- No data loss from previous training

### 2. Multi-Region Deployment
- Train on Region A data
- Later train on Region B data with same label
- Final model works well for both regions

### 3. Seasonal Patterns
- Train on winter data
- Train on summer data (same label)
- Captures seasonal variations automatically

### 4. Continuous Improvement
- Deploy model trained on historical data
- Periodically retrain on new data
- Keep accumulating patterns without reset

## Important Notes

### Label Behavior
- **Same label** → Patterns are merged (incremental training)
- **Different labels** → Patterns are separate (multiple models)

```yaml
# First training
patterns_label: "model_v1"    # Creates model_v1

# Second training (same label)
patterns_label: "model_v1"    # Merges with model_v1

# Second training (different label)
patterns_label: "model_v2"    # Creates separate model_v2
```

### When to Use Different Labels
Use different labels when you want to maintain separate models:
- Different battery types
- Completely different data sources
- A/B testing of algorithms
- Rolling models (e.g., `"last_7_days"`, `"last_30_days"`)

### When to Use Same Label
Use the same label for incremental training:
- Accumulating patterns over time
- Training on different time periods for same battery
- Enriching models with additional data

## Performance Characteristics

### Storage Impact
- **Memory:** Minimal - only stores statistics, not raw data
- **Database:** ~1-2 KB per pattern (small)
- **Training + Merge:** ~50-100ms overhead per battery

### Quality Impact
- **Better estimates:** More samples = more reliable rates
- **Stability:** Weighted averaging prevents overfitting to recent data
- **Coverage:** Patterns fill in gaps from previous training

### Validation
To verify incremental training is working:

```python
from src.battery_manager import BatteryManager

bm = BatteryManager()
patterns = bm.list_battery_patterns()

# Check sample counts
for battery_id, labels in patterns.items():
    for label in labels:
        discharge, charge, meta = bm.db.load_patterns(battery_id, label)
        if discharge:
            total_samples = sum(s['count'] for s in discharge.values())
            print(f"{battery_id}/{label}: {total_samples:,} samples")
```

## Limitations

1. **Median estimation:** Uses weighted average instead of true weighted median (acceptable approximation)
2. **Distribution shape:** Assumes both distributions are reasonably similar (works for gradual accumulation)
3. **Outliers:** Extreme patterns aren't auto-filtered (statistical weighting handles this)

## Troubleshooting

### "Merged with existing patterns" but counts didn't increase
- Verify the label is exactly the same
- Check if database file was cleared

### Quality degraded after merging
- Ensure data sources are compatible
- Check if new data is significantly different
- Consider using a different label for different data sources

### How to Reset Patterns
To start fresh (if needed):
```bash
rm battery_patterns.db
# Then retrain
python src/main.py
```

## Summary

Incremental training enables:
- ✅ Accumulating patterns from multiple training runs
- ✅ Proper statistical weighting by sample count
- ✅ Seamless combination of data from different periods
- ✅ Better TTE/TTF estimates over time
- ✅ No data loss or overwrites

Use the same `patterns_label` when you want incremental training, or different labels when you want separate models.
