# PATH 1 Investigation Results

## Applied Fix
**Filter training to exclude micro-sessions (<5 min, <0.5% SOC change)**

Expected impact: Remove noisy short sessions, improve decay rate reliability

## Results
- Patterns: 210 → 206 (4 removed)
- Total samples: 16,078 → 16,055 (23 removed)
- Decay rates: **UNCHANGED** (0.2121 → 0.2098 %/min mean)
- Validation metrics: **COMPLETELY IDENTICAL** to before PATH 1

## Conclusion
**Micro-sessions are NOT the problem.** The decay rate aggregation is working correctly regardless.

## Root Cause Found (Different Issue)
**Temporal Inconsistency: TTE is not decreasing properly**

Expected behavior:
```
t=0:  TTE = 10 hours
t=1h: TTE = 9 hours  (decreased by 1 hour)
t=2h: TTE = 8 hours
```

Actual behavior:
```
t=0:  TTE = 7.8 hours
t=1h: TTE = 7.6 hours  (decreased by 0.2 hours)
t=2h: TTE = 7.5 hours
→ Mean change rate = -0.01/hour (should be -1.0/hour)
```

**89% monotonicity violations** = TTE sometimes INCREASES during discharge (should never happen)

## Why This Matters
- Even if decay rates are correct (0.21%/min)
- If TTE doesn't decrement properly, predictions will drift
- High smoothing factor (0.70) might be "sticking" to old values
- Carry-forward logic might have bugs

## Next Investigation Steps
1. Inspect SimpleTTECalculator._smooth_value() method
2. Check carry-forward logic (when session gates not met)
3. Verify EMA smoothing window calculations
4. Look for off-by-one errors in time calculations

## PATH 1 Status
**Completed but ineffective** - The session filtering works but doesn't address root cause

The real fix needed is PATH 1b: **Fix temporal consistency in SimpleTTECalculator**
