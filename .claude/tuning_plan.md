# TUNING PLAN — Skewed Distribution (-9.18 hours bias)

## Problem Diagnosis
- **Mean = -9.18h**: Consistently UNDER-predicting (battery dies sooner than predicted)
- **Sigma = 6.23h**: High variance (predictions inconsistent)
- **Skewed left**: Long tail of severe under-predictions
- **NOT Gaussian**: Systematic bias, not random noise

## Root Causes (in order of likelihood)

### 1. **Decay Rates Too Aggressive** (60% likely)
```
Effect: Predicting battery empties faster than reality
Why: Training data may have high peak currents that inflate decay rates
Fix: Reduce default discharge rate or retrain with lower percentile
```

### 2. **Session Gates Too Relaxed** (25% likely)
```
Effect: Including unreliable early-session estimates with high variance
Why: Medium gate (3min + 0.2Ah) captures unstable transitions
Fix: Increase session_min_duration_minutes to 5-10 min
```

### 3. **Insufficient Smoothing** (15% likely)
```
Effect: Each TTE change is too responsive to noisy current
Why: Current fluctuations cause rapid TTE swings
Fix: Increase tte_ttf_smoothing_factor from 0.15 to 0.25-0.35
```

## Tuning Strategy (3 experiments)

### EXPERIMENT 1: Reduce Decay Rate Aggression
```yaml
# In config.yaml:
tte_ttf:
  default_discharge_rate_pct_per_min: 0.10  # was 0.15 (-33%)
  session_min_duration_minutes: 5.0         # was 3.0 (stricter gate)
  session_min_energy_ah: 0.3                # was 0.2 (stricter gate)
```
**Expected effect:** Shift mean error closer to 0 (less under-prediction)

### EXPERIMENT 2: Increase Smoothing for Stability
```yaml
# In config.yaml:
tte_ttf:
  tte_ttf_smoothing_factor: 0.25   # was 0.15 (67% more smoothing)
  ema_window_minutes: 30            # was 20 (smoother current)
```
**Expected effect:** Reduce variance (σ from 6.23 to ~4.5), tighter distribution

### EXPERIMENT 3: Tighten High-Confidence Gate
```yaml
# In config.yaml:
tte_ttf:
  session_high_confidence_minutes: 20.0    # was 15.0
  session_high_confidence_energy_ah: 2.0   # was 1.0
```
**Expected effect:** Reduce high-confidence estimates to only most reliable cases

## Testing Procedure

For each experiment:
1. Update config.yaml with tuned parameters
2. Run: `python src/main.py`  (with mode = "train_all_batteries")
3. Then: `python src/main.py` (with mode = "validate")
4. Check output/validation/ charts
5. Compare: Is mean closer to 0? Is σ lower? Is distribution less skewed?

## Rollback
If things get worse, run:
```bash
git checkout config.yaml
```
(We saved git status in .claude/git_status_backup.txt)

## Success Criteria
After tuning, target:
- **Mean bias**: < ±2.0 hours (acceptable range)
- **Sigma**: < 4.0 hours (tight predictions)
- **Gaussian p-value**: > 0.05 (normal distribution)
- **Within ±1h**: > 60% of estimates

