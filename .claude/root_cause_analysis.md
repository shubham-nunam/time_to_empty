# ROOT CAUSE ANALYSIS — Why TTE Predictions Are Empty

## The Problem Chain

```
1. Data has 706 discharge sessions (highly fragmented)
2. Training creates 210 patterns from these sessions
3. Each pattern has only 1 training sample
4. SimpleTTECalculator.estimate_tte() checks: if state == 'discharging' and session_valid and self.soc_decay.is_trained
5. is_trained = True (210 patterns exist)
6. But gates (session_min_duration_minutes + session_min_energy_ah) still not met
7. So carry-forward never activates either
8. Result: TTE stays empty/NaN for all rows
```

## Why Gates Aren't Met

### Current gates (after my tuning):
```yaml
session_min_duration_minutes: 0.1  (6 seconds!)
session_min_energy_ah: 0.01        (tiny!)
```

### But session statistics show:
- 651/706 sessions (92%) are < 5 minutes
- 651/706 sessions (92%) have < 0.5% SOC change
- SOC change = (soc_delta / 100) * capacity_ah
- Capacity appears to be 100 Ah (from previous output)
- So 0.01 Ah = 1% SOC change needed

The problem: **Individual short sessions have almost 0% SOC change**

### Example:
- Session at SOC=99%, discharge for 18 seconds
- SOC_final = 99.0 (unchanged at resolution)
- SOC_change = 0%
- Energy_change = 0 Ah
- Never meets 0.01 Ah gate!

## Why Database Has Only 1-Sample Patterns

The training algorithm is storing **individual session observations** rather than **aggregating** them.

Each pattern row represents one session's decay rate, not an accumulated statistic across many sessions.

This means:
- No median/percentile statistics
- Severe overfitting to single observations
- Pattern values are unstable and unreliable

## Solution Options

### Option A: Fix Training Aggregation (BEST, but requires code changes)
- Modify SOCDecayAnalyzer to properly aggregate discharge rates
- Combine all similar discharge observations into statistical buckets
- Store median/mean/std instead of individual observations

### Option B: Disable Session Gates + Heavy Smoothing (QUICK FIX)
- Set session gates to 0 (emit on every sample)
- Increase smoothing_factor to 0.7+ for stability
- Accept that early estimates will be very noisy

### Option C: Analyze Data Quality (INVESTIGATION)
- Check if SOC values are actually changing in raw parquet files
- Verify data sampling rate and precision
- Confirm capacity_ah value is correct

## Recommendation

Since goal is validation testing (not production):
→ Use **Option B** to force predictions, then evaluate accuracy despite fragmented data
