# Investigation Summary: TTE Validation Issues

## Problem Discovered
Initial validation showed **mean bias = -9.18 hours** with **non-Gaussian distribution**. This appeared to be a prediction accuracy problem, but investigation revealed a **data pipeline issue**.

## Root Cause Identified

### Level 1: Empty TTE Predictions (Initial Symptom)
- Output file had all tte_hours = NaN/empty
- Session validation gates (3min + 0.2Ah) were never met
- No predictions emitted → no validation possible

### Level 2: Session Fragmentation (Real Issue)
```
Data characteristics:
  - 706 discharge "sessions" detected
  - 651/706 (92%) are < 5 minutes duration
  - 651/706 (92%) have < 0.5% SOC change
  - Top 5 sessions: 850-900 minutes with 70-77% SOC change
```

Data is highly fragmented with many micro-sessions (noise) and few macro-sessions (real).

### Level 3: Training Aggregation Broken (Root Cause)
```
Database analysis:
  - 210 discharge patterns saved
  - Each pattern has only 1 training sample
  - Should have: hundreds of samples per pattern (aggregated)
```

The SOCDecayAnalyzer is storing **individual observations** instead of **statistical aggregates**.

Result: Patterns are unreliable, one-off measurements with no robustness.

---

## Current Validation Results (After Fixes)

With gates disabled (0min + 0Ah), forced predictions everywhere:

| Metric | Value | Status |
|--------|-------|--------|
| **TTE Coverage** | 99.9% | ✓ Much better |
| **Mean Bias** | -9.25 hours | ✗ Still under-predicting |
| **Std Dev** | 6.18 hours | ✗ High variance |
| **MAE** | 9.27 hours | ✗ Large errors |
| **Gaussian** | p<0.001 | ✗ Heavily skewed |
| **Monotonicity** | 81.5% violations | ✗ TTE jumping wildly |
| **Change rate** | -0.01/hour | ✗ Should be -1.0/hour |

---

## Why Results Are Bad

1. **Training patterns unreliable** (1 sample each)
2. **Predictions calculated from poor patterns**
3. **Disabled gates force noisy early estimates**
4. **81.5% monotonicity violations** = TTE fluctuating wildly
5. **Mean change rate -0.01** = TTE staying constant instead of decreasing by 1h/hour

---

## Three Paths Forward

### PATH 1: Fix Training Aggregation (BEST LONG-TERM)
**What:** Modify SOCDecayAnalyzer to aggregate observations properly
**Effort:** Medium (requires code changes)
**Result:** Stable patterns with statistical reliability
**Benefit:** System works as designed

**Changes needed:**
- In `tte_ttf_algorithm.py`: SOCDecayAnalyzer
- Group observations by (SOC bucket, load_class, current_range)
- Store median/percentiles instead of individual rows
- Current code stores each observation separately

### PATH 2: Improve Smoothing (QUICK, PARTIAL)
**What:** Increase tte_ttf_smoothing_factor from 0.35 to 0.7
**Effort:** Minimal (config change)
**Result:** Reduces fluctuation, still poor accuracy
**Benefit:** Makes oscillations less severe
**Problem:** Doesn't fix underlying pattern quality

### PATH 3: Accept Data Limitation (REALISTIC)
**What:** Validate on "big" discharge sessions only (>5min, >0.5% SOC)
**Effort:** Low (validation filtering)
**Result:** Evaluate accuracy on meaningful data
**Benefit:** Realistic assessment of what works
**Problem:** Discards 92% of data

---

## Recommendation

**For this session's validation testing:**
→ Apply PATH 2 + PATH 3: Smooth predictions AND filter to realistic sessions

This lets you:
- Assess validation mechanism itself (does it correctly measure accuracy?)
- Get meaningful metrics on real discharge events (big sessions)
- Defer training algorithm fix to separate work

**For production robustness:**
→ PATH 1: Fix training aggregation in SOCDecayAnalyzer

---

## Git Checkpoint

Current changes in config.yaml:
```yaml
session_min_duration_minutes: 0.0      # Disabled
session_min_energy_ah: 0.0             # Disabled
tte_ttf_smoothing_factor: 0.35         # Increased
default_discharge_rate_pct_per_min: 0.10  # Reduced
```

To rollback: `git checkout config.yaml`
Backup: `.claude/git_status_backup.txt`

