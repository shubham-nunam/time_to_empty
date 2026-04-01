"""
Time To Empty (TTE) and Time To Refill (TTF) Algorithm - Data-Driven SOC Decay Rates
======================================================================================

Core Principle: TTE/TTF based on historical SOC decay RATES, not instantaneous current

Architecture:
1. LoadClassifier: Categorize load pattern (idle, steady, transient, cyclic)
2. SOCDecayRateAnalyzer: Learn SOC % per minute for (SOC_level, load_class, current_range, state)
3. SimpleTTECalculator: Runtime estimation using actual current + decay rates + smoothing

Example:
- Training: "At SOC 24%, steady discharge, 2-4A current → SOC drops at 0.85%/min"
- Training: "At SOC 24%, steady discharge, 4-6A current → SOC drops at 1.2%/min"
- Runtime: "Current SOC=24%, load=steady, current=3.5A → use 0.85%/min rate → TTE = 24 / 0.85 = 28 min"

Key advantage: TTE is stable because it's based on actual historical decay rates, not reactive filtering
"""

import numpy as np
import pandas as pd
from typing import Dict, Tuple, Optional, List
from dataclasses import dataclass
from collections import deque
import time


@dataclass
class TTEResult:
    """Result container for TTE/TTF estimation"""
    timestamp: pd.Timestamp
    current_soc: float
    estimated_capacity_ah: float
    tte_hours: Optional[float]
    ttf_hours: Optional[float]
    confidence: str
    status: str
    ema_current_a: float
    effective_current_a: float
    voltage_v: Optional[float]
    num_samples: int
    time_hhmmss: str


class LoadClassifier:
    """Classify load pattern into meaningful categories"""

    def __init__(self, window_samples: int = 30):
        self.window_samples = window_samples
        self.current_history = deque(maxlen=window_samples)

    def update(self, current_a: float) -> str:
        """Classify current based on recent history"""
        if pd.isna(current_a):
            return 'unknown'

        self.current_history.append(abs(current_a))

        if len(self.current_history) < 5:
            return 'unknown'

        current_mean = np.mean(list(self.current_history))
        current_std = np.std(list(self.current_history))

        if current_mean < 0.1:
            return 'idle'
        elif current_std / (current_mean + 0.001) < 0.15:
            return 'steady'
        elif current_std / (current_mean + 0.001) > 0.5:
            return 'transient'
        else:
            return 'cyclic'

    def reset(self):
        self.current_history.clear()


class SOCDecayRateAnalyzer:
    """
    Learn historical SOC decay RATES (% per minute) indexed by:
    (SOC_window, load_class, current_range, state) → decay_rate

    This is much simpler and more physical than window-based lookup:
    - TTE = remaining_SOC / decay_rate
    - Current directly informs rate selection
    """

    def __init__(self, soc_step: int = 5, current_thresholds: list = None):
        """
        Parameters:
        -----------
        soc_step : SOC window size (5% = 0-5, 5-10, ... 95-100)
        current_thresholds : list of boundary values in Amperes for bucketing
                            E.g., [0.5, 2.0, 5.0] → low, medium, high, very_high
        """
        self.soc_step = soc_step
        self.current_thresholds = current_thresholds or [0.5, 2.0, 5.0]
        # Structure: [state][load_class][soc_start][current_range] = [decay_rates]
        self.discharge_rates = {}  # soc_window, load_class, current_range → [%/min values]
        self.charge_rates = {}
        self.discharge_stats = {}
        self.charge_stats = {}
        self.is_trained = False

    def train(self, data_df: pd.DataFrame,
              soc_col: str = 'soc',
              current_col: str = 'current_a',
              voltage_col: str = 'voltage_v',
              status_col: str = 'state',
              timestamp_col: str = 'ts',
              window_minutes: float = 5.0) -> None:
        """
        Analyze historical sessions and learn decay rates.

        Uses rolling windows (default 5 min) instead of sample-to-sample transitions
        to avoid learning from noise and session boundaries.

        For each window: decay_rate = % SOC change / window time, averaged by (SOC_level, load_class, current_range)
        """
        print("    [DECAY_RATE] Learning SOC decay rates from historical data...")
        start_time = time.time()

        df = data_df.copy()

        # Ensure timestamp is datetime
        if df[timestamp_col].dtype != 'datetime64[ns]':
            df[timestamp_col] = pd.to_datetime(df[timestamp_col], unit='ms', utc=True)

        df = df.sort_values(by=timestamp_col, ignore_index=True)

        # Classify load for each row (vectorized)
        classifier = LoadClassifier()
        load_classes = []
        for current in df[current_col]:
            load_classes.append(classifier.update(current))
        df['load_class'] = load_classes

        # Segment into sessions using vectorized session detection
        df_valid = df[df[status_col].notna()].copy()
        if len(df_valid) == 0:
            return

        # Detect session changes (where state changes from previous row)
        state_changes = df_valid[status_col] != df_valid[status_col].shift()
        state_changes.iloc[0] = True
        session_ids = state_changes.cumsum()

        sessions = []
        for session_id, group in df_valid.groupby(session_ids):
            if len(group) > 1:
                rows = list(zip(group[soc_col], group[current_col],
                               group[voltage_col], group['load_class'],
                               group[timestamp_col]))
                sessions.append({
                    'state': group[status_col].iloc[0],
                    'rows': rows
                })

        # Analyze each session using rolling windows
        discharge_data = {}
        charge_data = {}

        for session in sessions:
            state = session['state']
            rows = session['rows']

            # Use rolling window approach
            for i in range(len(rows)):
                soc_start, curr_start, volt_start, load_start, ts_start = rows[i]

                if pd.isna(soc_start):
                    continue

                # Find the end of the window (window_minutes from start)
                window_end_time = ts_start + pd.Timedelta(minutes=window_minutes)
                j = i + 1
                while j < len(rows) and rows[j][4] <= window_end_time:
                    j += 1

                if j <= i + 1:  # Not enough data in window
                    continue

                soc_end, curr_end, volt_end, load_end, ts_end = rows[j - 1]

                if pd.isna(soc_end):
                    continue

                # Calculate decay over window
                soc_delta = soc_end - soc_start
                time_delta_min = (ts_end - ts_start).total_seconds() / 60.0

                if time_delta_min < 0.5:  # Need at least 30 seconds of data
                    continue

                if time_delta_min == 0:
                    continue

                # Only use if SOC actually changed meaningfully
                if abs(soc_delta) < 0.01:  # Less than 0.01% change
                    continue

                # Filter out crazy decay rates (outliers from data quality issues)
                decay_rate = abs(soc_delta) / time_delta_min
                if decay_rate > 0.5:  # Skip if > 0.5 %/min (too fast)
                    continue

                # Determine which SOC window we're starting in
                soc_window = int(soc_start // self.soc_step) * self.soc_step
                load_class = load_start if load_start != 'unknown' else 'steady'

                # Use average current in window
                window_currents = [abs(rows[k][1]) for k in range(i, j) if not pd.isna(rows[k][1])]
                current_avg = np.mean(window_currents) if window_currents else abs(curr_start)
                current_range = self._get_current_range_key(current_avg)

                if state == 'discharging' and soc_delta < 0:
                    # SOC decreasing
                    key = (soc_window, load_class, current_range)
                    if key not in discharge_data:
                        discharge_data[key] = []
                    discharge_data[key].append(decay_rate)

                elif state == 'charging' and soc_delta > 0:
                    # SOC increasing
                    key = (soc_window, load_class, current_range)
                    if key not in charge_data:
                        charge_data[key] = []
                    charge_data[key].append(decay_rate)

        # Compute statistics for each pattern
        self.discharge_stats = {}
        for key, rates in discharge_data.items():
            if len(rates) > 1:
                self.discharge_stats[key] = {
                    'rate_median': float(np.median(rates)),
                    'rate_mean': float(np.mean(rates)),
                    'rate_std': float(np.std(rates)),
                    'count': len(rates)
                }

        self.charge_stats = {}
        for key, rates in charge_data.items():
            if len(rates) > 1:
                self.charge_stats[key] = {
                    'rate_median': float(np.median(rates)),
                    'rate_mean': float(np.mean(rates)),
                    'rate_std': float(np.std(rates)),
                    'count': len(rates)
                }

        # Only mark as trained if we actually learned discharge patterns
        self.is_trained = bool(self.discharge_stats)
        if not self.is_trained:
            print(f"    [DECAY_RATE] [WARN] No discharge patterns learned — insufficient data")

        elapsed = time.time() - start_time
        print(f"    [DECAY_RATE] Trained in {elapsed:.0f}ms")
        print(f"    [DECAY_RATE] Discharge patterns: {len(self.discharge_stats)}, Charge patterns: {len(self.charge_stats)}")

    @property
    def pattern_count(self) -> int:
        """Return number of learned discharge patterns (for diagnostics)."""
        return len(self.discharge_stats)

    def estimate_tte_from_rate(self, current_soc: float, current_a: float,
                               load_class: str, state: str) -> Optional[float]:
        """
        Estimate TTE using historical decay rates.

        TTE = remaining_SOC / decay_rate (where decay_rate is %/min, result in hours)
        """
        if not self.is_trained:
            return None

        if load_class == 'unknown':
            load_class = 'steady'

        stats_dict = self.discharge_stats if state == 'discharging' else self.charge_stats
        if not stats_dict:
            return None

        # Find matching pattern: (SOC_window, load_class, current_range)
        soc_window = int(current_soc // self.soc_step) * self.soc_step
        current_range = self._get_current_range_key(current_a)
        key = (soc_window, load_class, current_range)

        # Try to find matching pattern, with fallbacks
        decay_rate = None

        if key in stats_dict:
            decay_rate = stats_dict[key]['rate_median']
        else:
            # Fallback 1: same SOC and load, different current range
            matching_keys = [k for k in stats_dict if k[0] == soc_window and k[1] == load_class]
            if matching_keys:
                rates = [stats_dict[k]['rate_median'] for k in matching_keys]
                decay_rate = float(np.mean(rates))
            else:
                # Fallback 2: same load, any SOC
                matching_keys = [k for k in stats_dict if k[1] == load_class]
                if matching_keys:
                    rates = [stats_dict[k]['rate_median'] for k in matching_keys]
                    decay_rate = float(np.mean(rates))
                else:
                    # Fallback 3: any pattern in this state
                    rates = [v['rate_median'] for v in stats_dict.values()]
                    if rates:
                        decay_rate = float(np.mean(rates))

        if decay_rate is None or decay_rate < 0.001:
            return None

        # Calculate TTE
        if state == 'discharging':
            remaining_soc = current_soc  # Assume min_soc = 0
            tte_minutes = remaining_soc / decay_rate
        elif state == 'charging':
            remaining_soc = 100 - current_soc  # Assume max_soc = 100
            tte_minutes = remaining_soc / decay_rate
        else:
            return None

        # Cap at 24 hours
        tte_hours = tte_minutes / 60.0
        if tte_hours > 24.0:
            tte_hours = 24.0

        return tte_hours if tte_hours > 0 else None

    def _get_current_range_key(self, current_a: float) -> str:
        """Bin current into ranges based on configurable thresholds (in Amperes)."""
        labels = ['low', 'medium', 'high', 'very_high', 'extreme', 'critical']

        # Find which threshold bin this current falls into
        for i, threshold in enumerate(self.current_thresholds):
            if current_a < threshold:
                return labels[i]

        # If current >= highest threshold, return the last label
        return labels[len(self.current_thresholds)]


class EnergySession:
    """Track a single charge/discharge session for validation purposes"""

    def __init__(self, session_type: str, start_time: pd.Timestamp, start_soc: float, accumulated_energy_ah: float = 0.0):
        self.session_type = session_type
        self.start_time = start_time
        self.start_soc = start_soc
        self.accumulated_energy_ah = accumulated_energy_ah
        self.is_valid = False
        self.current_tte = None
        self.current_ttf = None

    def duration_minutes(self, current_time: pd.Timestamp) -> float:
        """Get session duration in minutes"""
        return (current_time - self.start_time).total_seconds() / 60.0

    def meets_validation_criteria(self, current_time: pd.Timestamp,
                                   min_duration_minutes: float = 15.0,
                                   min_energy_ah: float = 1.0) -> bool:
        """Check if session meets minimum duration and energy criteria"""
        duration = self.duration_minutes(current_time)
        energy = abs(self.accumulated_energy_ah)
        return duration >= min_duration_minutes and energy >= min_energy_ah


class SimpleTTECalculator:
    """
    TTE/TTF calculator using empirical SOC decay rates.

    Key: Current directly informs decay rate selection, making TTE responsive to actual load
    while remaining stable because rates are historically grounded.
    """

    def __init__(self,
                 session_min_duration_minutes: float = 15.0,
                 session_min_energy_ah: float = 1.0,
                 tte_ttf_smoothing_factor: float = 0.2,
                 current_thresholds: list = None,
                 session_high_confidence_minutes: float = 15.0,
                 session_high_confidence_energy_ah: float = 1.0):
        """
        Parameters:
        -----------
        session_min_duration_minutes : minimum session duration for medium confidence TTE/TTF (default 15 → 3.0 with relaxed config)
        session_min_energy_ah : minimum energy change for medium confidence TTE/TTF (default 1.0 → 0.2 with relaxed config)
        tte_ttf_smoothing_factor : smoothing factor for TTE/TTF (0-1, default 0.2 for stability)
        current_thresholds : list of current range thresholds in Amperes (default [0.5, 2.0, 5.0])
        session_high_confidence_minutes : session duration threshold for high confidence (default 15.0)
        session_high_confidence_energy_ah : session energy threshold for high confidence (default 1.0)
        """
        self.session_min_duration_minutes = session_min_duration_minutes
        self.session_min_energy_ah = session_min_energy_ah
        self.session_high_conf_minutes = session_high_confidence_minutes
        self.session_high_conf_energy_ah = session_high_confidence_energy_ah
        self.smoothing_factor = tte_ttf_smoothing_factor

        self.soc_decay = SOCDecayRateAnalyzer(soc_step=5, current_thresholds=current_thresholds)
        self.load_classifier = LoadClassifier(window_samples=30)

        self._current_session: Optional[EnergySession] = None
        self._last_soc = None
        self._previous_tte = None
        self._previous_ttf = None
        self._last_valid_tte: Optional[float] = None  # carry-forward for gap filling
        self._last_valid_ts: Optional[pd.Timestamp] = None  # timestamp of last valid TTE
        self.min_soc = 0.0
        self.max_soc = 100.0

    def train(self, data_df: pd.DataFrame,
              soc_col: str = 'soc',
              current_col: str = 'current_a',
              voltage_col: str = 'voltage_v',
              status_col: str = 'state',
              timestamp_col: str = 'ts') -> None:
        """Train the calculator from historical data"""
        self.soc_decay.train(data_df, soc_col, current_col, voltage_col, status_col, timestamp_col)

    def estimate_tte(self,
                     current_soc: float,
                     capacity_ah: float,
                     discharge_current_ma: float,
                     charge_current_ma: float,
                     timestamp: pd.Timestamp,
                     voltage_v: Optional[float] = None,
                     state: Optional[str] = None,
                     num_samples: int = 1) -> TTEResult:
        """
        Estimate TTE and TTF using empirical decay rates.

        Process:
        1. Convert currents and ensure timestamp is datetime
        2. Determine state (discharging/charging/rest)
        3. Classify load pattern
        4. Lookup historical decay rate for (SOC, load_class, current_range)
        5. Calculate TTE = SOC / decay_rate
        6. Apply smoothing and confidence adjustment
        """

        # Ensure timestamp is a Timestamp object
        if not isinstance(timestamp, pd.Timestamp):
            if isinstance(timestamp, (int, float)) and timestamp > 1e10:
                timestamp = pd.to_datetime(timestamp, unit='ms')
            else:
                timestamp = pd.Timestamp(timestamp)

        # Convert currents
        discharge_a = discharge_current_ma / 1000.0
        charge_a = charge_current_ma / 1000.0

        # Determine state
        if state is None:
            if discharge_current_ma > charge_current_ma and discharge_current_ma > 50:
                state = 'discharging'
            elif charge_current_ma > discharge_current_ma and charge_current_ma > 50:
                state = 'charging'
            else:
                state = 'rest'

        # Transition session if state changed
        if self._current_session is None or self._current_session.session_type != state:
            self._transition_session(state, timestamp, current_soc)

        # Accumulate energy
        if self._last_soc is not None:
            soc_change = current_soc - self._last_soc
            energy_change = (soc_change / 100.0) * capacity_ah
            self._current_session.accumulated_energy_ah += energy_change

        self._last_soc = current_soc

        # Classify load
        ema_current = discharge_a if state == 'discharging' else (charge_a if state == 'charging' else 0.0)
        load_class = self.load_classifier.update(ema_current)

        # Initialize results
        tte_hours = float('nan')
        ttf_hours = float('nan')
        confidence = 'low'

        # Check session validity
        session_valid = self._current_session.meets_validation_criteria(
            timestamp,
            min_duration_minutes=self.session_min_duration_minutes,
            min_energy_ah=self.session_min_energy_ah
        )

        # TTE: Empirical decay rate for discharge
        if state == 'discharging' and session_valid and self.soc_decay.is_trained:
            tte_empirical = self.soc_decay.estimate_tte_from_rate(current_soc, ema_current, load_class, 'discharging')
            if tte_empirical is not None and 0 < tte_empirical <= 24.0:
                # Apply smoothing
                tte_smoothed = self._smooth_value(tte_empirical, self._previous_tte)
                tte_hours = tte_smoothed
                self._previous_tte = tte_hours

                # Determine confidence based on session thresholds (relaxed and strict)
                session_duration = self._current_session.duration_minutes(timestamp)
                session_energy = abs(self._current_session.accumulated_energy_ah)

                if session_duration >= self.session_high_conf_minutes and session_energy >= self.session_high_conf_energy_ah:
                    confidence = 'high'
                elif session_duration >= self.session_min_duration_minutes and session_energy >= self.session_min_energy_ah:
                    confidence = 'medium'
                else:
                    confidence = 'low'

                # Update carry-forward only if medium or high confidence
                if confidence in ['high', 'medium']:
                    self._last_valid_tte = tte_hours
                    self._last_valid_ts = timestamp
        # Carry-forward: if session not yet valid, use last known TTE (decremented by elapsed time)
        elif state == 'discharging' and not session_valid and self._last_valid_tte is not None and self.soc_decay.is_trained:
            elapsed_hours = (timestamp - self._last_valid_ts).total_seconds() / 3600.0
            carried_tte = max(0.0, self._last_valid_tte - elapsed_hours)
            if carried_tte > 0:
                tte_hours = carried_tte
                confidence = 'low'  # signal that this is carried, not freshly computed

        # TTF: Empirical decay rate for charge
        if state == 'charging' and session_valid and self.soc_decay.is_trained:
            ttf_empirical = self.soc_decay.estimate_tte_from_rate(current_soc, ema_current, load_class, 'charging')
            if ttf_empirical is not None and 0 < ttf_empirical <= 24.0:
                # Apply smoothing
                ttf_smoothed = self._smooth_value(ttf_empirical, self._previous_ttf)
                ttf_hours = ttf_smoothed
                self._previous_ttf = ttf_hours

                # Determine confidence based on session thresholds (relaxed and strict)
                session_duration = self._current_session.duration_minutes(timestamp)
                session_energy = abs(self._current_session.accumulated_energy_ah)

                if session_duration >= self.session_high_conf_minutes and session_energy >= self.session_high_conf_energy_ah:
                    confidence = 'high'
                elif session_duration >= self.session_min_duration_minutes and session_energy >= self.session_min_energy_ah:
                    confidence = 'medium'
                else:
                    confidence = 'low'

                # Update carry-forward only if medium or high confidence
                if confidence in ['high', 'medium']:
                    self._last_valid_tte = ttf_hours
                    self._last_valid_ts = timestamp
        # Carry-forward: if session not yet valid, use last known TTF (decremented by elapsed time)
        elif state == 'charging' and not session_valid and self._last_valid_tte is not None and self.soc_decay.is_trained:
            elapsed_hours = (timestamp - self._last_valid_ts).total_seconds() / 3600.0
            carried_ttf = max(0.0, self._last_valid_tte - elapsed_hours)
            if carried_ttf > 0:
                ttf_hours = carried_ttf
                confidence = 'low'  # signal that this is carried, not freshly computed

        # Format time
        time_hours = tte_hours if not np.isnan(tte_hours) else (ttf_hours if not np.isnan(ttf_hours) else float('inf'))
        if time_hours == float('inf'):
            time_hhmmss = "infinite"
        elif np.isnan(time_hours):
            time_hhmmss = "N/A"
        else:
            hours = int(time_hours)
            remaining = (time_hours - hours) * 60
            minutes = int(remaining)
            seconds = int((remaining - minutes) * 60)
            time_hhmmss = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

        return TTEResult(
            timestamp=timestamp,
            current_soc=current_soc,
            estimated_capacity_ah=capacity_ah,
            tte_hours=tte_hours if not np.isnan(tte_hours) else None,
            ttf_hours=ttf_hours if not np.isnan(ttf_hours) else None,
            confidence=confidence,
            status=state,
            ema_current_a=ema_current,
            effective_current_a=ema_current,
            voltage_v=voltage_v,
            num_samples=num_samples,
            time_hhmmss=time_hhmmss
        )

    def estimate_batch(self, data_df: pd.DataFrame,
                      soc_col: str = 'soc',
                      capacity_col: str = 'FullCap',
                      discharge_current_col: str = 'id',
                      charge_current_col: str = 'ic',
                      timestamp_col: str = 'ts',
                      voltage_col: str = 'lv',
                      state_col: str = 'state',
                      batch_size: int = 2000) -> pd.DataFrame:
        """Process batch of data and return TTE/TTF results"""
        results = []

        for idx, row in data_df.iterrows():
            result = self.estimate_tte(
                current_soc=row[soc_col],
                capacity_ah=row[capacity_col] / 1000.0,
                discharge_current_ma=row[discharge_current_col],
                charge_current_ma=row[charge_current_col],
                timestamp=row[timestamp_col],
                voltage_v=row[voltage_col] if voltage_col in row and not pd.isna(row[voltage_col]) else None,
                state=row[state_col] if state_col in row else None,
                num_samples=1
            )
            results.append(result)

            if (idx + 1) % batch_size == 0:
                print(f"  Processed {idx + 1:,} rows")

        # Convert results to DataFrame
        results_df = pd.DataFrame([
            {
                'timestamp': r.timestamp,
                'soc': r.current_soc,
                'voltage_v': r.voltage_v,
                'current_a': r.ema_current_a,
                'status': r.status,
                'tte_hours': r.tte_hours,
                'ttf_hours': r.ttf_hours,
                'confidence': r.confidence,
                'time_hhmmss': r.time_hhmmss,
                'num_samples': r.num_samples
            }
            for r in results
        ])

        return results_df

    def _smooth_value(self, new_value: Optional[float], old_value: Optional[float]) -> Optional[float]:
        """Apply exponential smoothing to prevent abrupt changes"""
        if new_value is None or np.isnan(new_value):
            return old_value
        if old_value is None or np.isnan(old_value):
            return new_value
        return self.smoothing_factor * new_value + (1 - self.smoothing_factor) * old_value

    def _transition_session(self, new_state: str, timestamp: pd.Timestamp, soc: float) -> None:
        """Transition to a new session when state changes"""
        self.load_classifier.reset()
        self._current_session = EnergySession(
            session_type=new_state,
            start_time=timestamp,
            start_soc=soc,
            accumulated_energy_ah=0.0
        )
        self._last_soc = soc


# Backward compatibility: expose original interface
TTETTFCalculator = SimpleTTECalculator
