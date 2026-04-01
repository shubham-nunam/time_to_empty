# Quick Start - When to Train vs Apply

---

## Your Question Answered

> "when i need to train then how i run when i just need to test based on previous training then how i will run"

---

## ⚡ WHEN YOU NEED TO TRAIN

### Scenario: Learning Patterns from Historical Data

**Edit `config.yaml`:**
```yaml
execution:
  mode: "train_test_split"              # or "train_only"
  train_date_start: "2025-09-01"
  train_date_end: "2025-09-25"
  test_date_start: "2025-09-26"
  test_date_end: "2025-09-30"
  save_patterns: true
  patterns_label: "september_2025"
```

**Run Command:**
```bash
python src/main.py
```

**What Happens:**
1. ✅ Learns SOC decay patterns from Sept 1-25 data
2. ✅ Tests on Sept 26-30 data
3. ✅ Saves patterns to: `outputs/patterns/september_2025_<timestamp>/`
4. ✅ Generates comparison report

**Output Files:**
```
outputs/tte_ttf_train_results.csv       ← Training dataset results
outputs/tte_ttf_test_results.csv        ← Testing dataset results
outputs/train_test_comparison.csv       ← Metrics comparison
outputs/patterns/september_2025.../     ← Saved patterns (for later reuse)
```

---

## ⚡ WHEN YOU NEED TO TEST BASED ON PREVIOUS TRAINING

### Scenario: Apply Previously Learned Patterns to New Data

**Edit `config.yaml`:**
```yaml
execution:
  mode: "apply"                          # Don't retrain, just apply!
  pattern_path: null                     # Auto-find latest pattern, OR
  # pattern_path: "outputs/patterns/september_2025_20260331_120000"  # Explicit path
  pattern_label_filter: "september"      # Search term if auto-finding
data:
  input_file: data/SE0100000092_OCTOBER.parquet  # New data (no retraining)
```

**Run Command:**
```bash
python src/main.py
```

**What Happens:**
1. ✅ Loads previously trained patterns (no learning)
2. ✅ Applies patterns to NEW October data
3. ✅ Generates estimates FAST (no training overhead)
4. ✅ Saves results

**Output Files:**
```
outputs/tte_ttf_results_applied.csv      ← Results on new data (using learned patterns)
```

---

## 🎯 Side-by-Side Comparison

| Scenario | Config Mode | Training? | Pattern Save? | Best For |
|----------|-------------|-----------|---------------|----------|
| **Learn phase** | `train_test_split` | ✅ YES | ✅ YES | Understanding algorithm performance |
| **Learn + save** | `train_only` | ✅ YES | ✅ YES | Before production deployment |
| **Apply only** | `apply` | ❌ NO | ❌ NO | Production inference (fast!) |

---

## 📊 Typical Workflow

### Week 1: Learning Phase
```
Collect historical data (Sept 1-25)
         ↓
python src/main.py  [mode: train_test_split]
         ↓
Review metrics comparison
         ↓
Patterns saved to outputs/patterns/
```

### Week 2+: Production Phase
```
New incoming data arrives (Oct 1-31)
         ↓
python src/main.py  [mode: apply]  (NO TRAINING, JUST APPLY)
         ↓
Results saved immediately
         ↓
Process next batch same way
```

---

## 🔧 How to Switch Modes

### Currently in TRAIN Mode?
```yaml
# config.yaml
execution:
  mode: "train_test_split"  # or "train_only"
```

### Switch to APPLY Mode?
```yaml
# config.yaml
execution:
  mode: "apply"                    # Changed this
  pattern_path: null               # Auto-find pattern
  pattern_label_filter: "september"  # Or specify explicit path above
```

---

## 💾 Pattern Storage & Reuse

### Where Patterns Live
```
outputs/patterns/
├── september_2025_20260331_120000/     ← Pattern #1 (learned Sept 1-25)
│   ├── metadata.json
│   ├── soc_decay_analyzer.pkl
│   └── load_classifier.pkl
├── september_all_20260402_090000/      ← Pattern #2 (learned all Sept)
│   ├── metadata.json
│   ├── soc_decay_analyzer.pkl
│   └── load_classifier.pkl
└── ...
```

### List Available Patterns
```bash
# In Python
from src.pattern_manager import PatternManager
mgr = PatternManager("outputs/patterns")
patterns = mgr.list_patterns()
for p in patterns:
    print(f"{p['label']} - {p['saved_at']}")
```

### Use Latest Pattern
```yaml
# config.yaml - APPLY mode
execution:
  mode: "apply"
  pattern_path: null                      # null = auto-find
  pattern_label_filter: "september"       # Find patterns with "september"
```

---

## ✅ Checklist: First Time?

- [ ] Run **TRAIN_TEST_SPLIT** first (learn + validate)
  - Proves algorithm works on your data
  - Shows coverage, stability metrics
  - Saves patterns for reuse

- [ ] Review **comparison report** in console
  - Check coverage > 90%
  - Check test metrics similar to train

- [ ] Run **APPLY** on new data
  - Uses saved patterns
  - No retraining = fast
  - Same output format

---

## ❓ Quick FAQ

**Q: Do I need to retrain every time I get new data?**
A: No! Use APPLY mode. Retrain only if accuracy degrades.

**Q: How do I know if I need to retrain?**
A: Run APPLY → Check coverage/stability → If coverage < 80%, retrain.

**Q: Can I use patterns from September on October data?**
A: Yes! Patterns encode typical discharge behavior. As long as battery/usage similar, patterns apply.

**Q: What if I have a new battery?**
A: Retrain with new battery data using TRAIN_TEST_SPLIT or TRAIN_ONLY.

**Q: How long does TRAIN take?**
A: ~10 seconds for 100K rows (one-time cost). APPLY is instant.

**Q: Where are the results saved?**
A: All in `outputs/` directory. CSV files named by mode (train/test/applied).

---

## 🚀 Copy-Paste Commands

### First time (learn from data)
```bash
# Edit config.yaml to set mode: "train_test_split"
python src/main.py
```

### Running on new data (no learning)
```bash
# Edit config.yaml to set mode: "apply"
python src/main.py
```

### Monthly report
```bash
# Edit config.yaml to set mode: "monthly", execution.month: "2025-10"
python src/main.py
```

---

**That's it!** Change config.yaml, run `python src/main.py`, get results. 🎉

