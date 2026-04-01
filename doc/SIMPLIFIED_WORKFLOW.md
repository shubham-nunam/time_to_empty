# Simplified Multi-Battery Workflow

**Status:** ✅ DEFAULT CONFIG
**Modes:** Only 2 (train_all_batteries, apply_battery)
**Output:** One pickle folder per battery

---

## Workflow

### Step 1: Train All Batteries

```yaml
# config.yaml
execution:
  mode: "train_all_batteries"        # ← Default
  patterns_label: "september_2025"
```

```bash
python src/main.py
```

**What happens:**
1. Scans `data/` folder
2. Finds all `*.parquet` files (e.g., SE0100000092.parquet, SE0100000093.parquet, ...)
3. Trains each battery independently
4. Saves patterns as pickle files

**Output:**
```
outputs/
├── tte_ttf_SE0100000092.csv           (results)
├── tte_ttf_SE0100000093.csv           (results)
├── tte_ttf_SE0100000094.csv           (results)
└── patterns/
    ├── SE0100000092_september_2025/   (pickle files)
    │   ├── soc_decay_analyzer.pkl
    │   ├── load_classifier.pkl
    │   └── metadata.pkl
    ├── SE0100000093_september_2025/   (pickle files)
    ├── SE0100000094_september_2025/   (pickle files)
    └── ...
```

---

### Step 2: Apply to Specific Battery

```yaml
# config.yaml
execution:
  mode: "apply_battery"              # ← Switch mode
  battery_id: "SE0100000092"         # ← Which battery
  patterns_label: "september_2025"   # ← Which patterns
```

```bash
python src/main.py
```

**What happens:**
1. Loads patterns from: `outputs/patterns/SE0100000092_september_2025/`
2. Applies to: `data/SE0100000092.parquet`
3. No retraining (fast!)

**Output:**
```
outputs/
└── tte_ttf_SE0100000092_applied.csv    (results using loaded patterns)
```

---

## Quick Reference

| Task | Config | Command |
|------|--------|---------|
| **Train all batteries** | `mode: train_all_batteries` | `python src/main.py` |
| **Apply to battery X** | `mode: apply_battery, battery_id: X` | `python src/main.py` |

---

## Data Folder Structure

```
data/
├── SE0100000092.parquet     ← Battery 1
├── SE0100000093.parquet     ← Battery 2
├── SE0100000094.parquet     ← Battery 3
└── SE0100000095.parquet     ← Battery 4
```

- One file per battery
- Auto-discovered
- Works with 1 file or 1000 files

---

## Pattern Storage (Pickle)

Each battery's patterns stored as:
```
outputs/patterns/
├── SE0100000092_september_2025/
│   ├── soc_decay_analyzer.pkl      ← Binary, fast, compact
│   ├── load_classifier.pkl         ← Binary, fast, compact
│   └── metadata.pkl                ← Binary, fast, compact
└── SE0100000093_september_2025/
    ├── soc_decay_analyzer.pkl
    ├── load_classifier.pkl
    └── metadata.pkl
```

**Why pickle?**
- ✅ Binary format (compact)
- ✅ Fast load/save (<1ms)
- ✅ Preserves Python objects exactly
- ✅ No JSON serialization needed

---

## Timeline Example

**Month 1: September (Learning)**
```
python src/main.py [mode: train_all_batteries, patterns_label: september_2025]
↓
Patterns saved: outputs/patterns/<battery_id>_september_2025/
```

**Month 2: October (Production)**
```
python src/main.py [mode: apply_battery, battery_id: SE0100000092, patterns_label: september_2025]
python src/main.py [mode: apply_battery, battery_id: SE0100000093, patterns_label: september_2025]
python src/main.py [mode: apply_battery, battery_id: SE0100000094, patterns_label: september_2025]
↓
Results: tte_ttf_<battery_id>_applied.csv (fast, no training!)
```

**Month 3+: Scale**
```
For each new battery or new data:
python src/main.py [mode: apply_battery, battery_id: <your_battery>]
↓
Results in ~2 seconds per battery
```

---

## That's It!

✅ Simple
✅ Scalable
✅ Fast

Just switch `mode` in config.yaml and run!

