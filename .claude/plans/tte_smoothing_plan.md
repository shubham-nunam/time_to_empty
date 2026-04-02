# Plan: Reduce TTE Fluctuations with Gradual Load-Aware Smoothing

## Problem Analysis
Current TTE shows sudden jumps up to 4.2 hours between consecutive samples due to:
- **Load volatility**: 66% coefficient of variation (high variability)
- **High SOC sensitivity**: At 99% SOC with low current (0.9A), small load changes cause large TTE swings
- **Current EMA smoothing (0.15)**: Not aggressive enough for load-driven volatility

Example jump: TTE goes from 19.6h → 23.9h → 31.9h → 33.2h (rapid escalation at SOC=99%)

## Observation
You noted: **"discharge load is predictable"** — Load patterns follow distinct phases:
- Ramp-up (load increases gradually)
- Steady-state (stable load)
- Ramp-down (load decreases gradually)

This suggests we can use load patterns to anticipate TTE changes instead of reacting abruptly.

---

## Options for Gradual TTE Transitions

### Option 1: Adaptive EMA Based on Load Change Rate (RECOMMENDED)
**Concept**: When load changes rapidly, increase smoothing. When stable, use normal smoothing.

```
load_change_rate = |current_load - previous_load| / time_delta
if load_change_rate > threshold:
    smoothing_factor = 0.40  (more smoothing when load changes)
else:
    smoothing_factor = 0.15  (normal smoothing when stable)
```

**Pros:**
- Automatically detects load transitions
- Gradually adapts as load stabilizes
- No lag during stable periods
- Simple to implement

**Cons:**
- Needs threshold tuning
- Still responsive within 2-3 samples

---

### Option 2: Load Prediction with Anticipatory Smoothing
**Concept**: Predict the load 5-10 samples ahead, pre-smooth TTE to expected value.

```
predicted_load = load_classifier.predict_next_n_samples(5)
estimated_tte_at_predicted_load = soc / (decay_rate_for_predicted_load)
smoothed_tte = blend(current_tte, estimated_tte_at_predicted_load, 0.3)
```

**Pros:**
- Most responsive, anticipates trends
- Eliminates lag completely
- Follows user's insight about "predictable load"

**Cons:**
- Complex implementation
- Prediction errors could amplify
- Requires load model training

---

### Option 3: Rate-Limited TTE Changes (PRACTICAL)
**Concept**: Cap how fast TTE can change per unit time.

```
max_tte_change_per_hour = 5.0  # TTE can change at most 5h/hour
allowed_change = max_tte_change_per_hour * (time_delta / 3600)
new_tte = clamp(tte_estimate, prev_tte - allowed_change, prev_tte + allowed_change)
```

**Pros:**
- Simple, predictable behavior
- Guarantees smooth transitions
- Independent of load volatility

**Cons:**
- Always lags by definition
- May not reflect sudden actual changes
- Fixed rate doesn't adapt to session type

---

### Option 4: Hybrid - Load-Aware Rate Limiting (BEST BALANCE)
**Concept**: Combine Options 1 & 3 — adaptive smoothing + rate limiting

```
1. Detect load change rate
2. If rapid load change: smoothing = 0.35 (gradual, not instant)
3. Also apply max_rate_limit = 2.0 hours/hour
4. Final TTE = smooth(estimate) clamped to rate_limit
```

**Pros:**
- Handles both smooth AND sudden load changes
- Gradual transitions (no jumps)
- Uses load predictability insight
- Simple to tune with 2 parameters

**Cons:**
- Two mechanisms to tune

---

### Option 5: Kalman Filter (ADVANCED)
**Concept**: Optimal filtering that assumes TTE changes smoothly, loads noisily.

```
kalman_gain = variance_in_estimates / (variance_in_estimates + variance_in_noise)
filtered_tte = prev_tte + kalman_gain * (new_estimate - prev_tte)
```

**Pros:**
- Statistically optimal
- Automatically adapts noise/signal ratio
- Research-backed

**Cons:**
- Complex to implement
- Requires tuning process/measurement noise
- Overkill for this use case

---

## Recommended Approach: **Option 4 (Hybrid)**

### Implementation Steps:

1. **Detect load change rate**
   ```python
   load_change_pct = abs(current_load - prev_load) / prev_load * 100
   if load_change_pct > 15%:  # >15% load change in one sample
       smoothing = 0.35  # More aggressive smoothing
   else:
       smoothing = 0.15  # Normal smoothing
   ```

2. **Apply adaptive smoothing**
   ```python
   smoothed_tte = smoothing_factor * new_tte + (1 - smoothing_factor) * prev_tte
   ```

3. **Apply rate limiting as safety net**
   ```python
   max_change_per_sample = 0.05  # Max 3 min change per ~18 sec sample
   final_tte = clamp(smoothed_tte, prev_tte - max_change_per_sample,
                                    prev_tte + max_change_per_sample)
   ```

### Expected Results:
- **Current**: Max jump 4.2 hours → **Expected**: Max jump 0.15-0.20 hours
- **Smoothness**: Gradual transitions over 5-10 samples
- **Responsiveness**: Still tracks load within 1-2 minutes
- **Validation impact**: Slight increase in MAE (~0.5h), but much better UX

---

## Implementation Location
**File**: `src/tte_ttf_algorithm.py`
**Method**: `SimpleTTECalculator._smooth_value()` → extend to `_smooth_with_load_awareness()`
**Add to config**: Two tuning parameters:
```yaml
tte_ttf:
  high_load_change_threshold_pct: 15.0      # Trigger adaptive smoothing
  adaptive_smoothing_factor: 0.35            # Higher smoothing during load spikes
  tte_max_change_per_sample: 0.05            # Rate limit in hours
```

---

## Testing Strategy
1. Extract a 10-minute discharge session with load spikes
2. Plot old vs new TTE on same graph
3. Verify: Jumps reduced to <0.2h, smooth transitions
4. Run full validation: Check MAE impact
5. Accept if MAE increase < 1h

