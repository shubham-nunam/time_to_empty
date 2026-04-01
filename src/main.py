#!/usr/bin/env python3
"""
TTE/TTF Main Runner - Train/Test/Apply Modes
==============================================

Supports three operational modes:
  1. TRAIN_TEST_SPLIT - Split data by date, train on one period, test on another
  2. TRAIN_ONLY - Train on all data, save patterns for later use
  3. APPLY - Apply previously trained patterns to new data (no retraining)
  4. FULL - Process entire dataset
  5. MONTHLY - Filter by month and process

Usage:
  python src/main.py                    # Runs mode from config.yaml
"""

import sys
import yaml
import time
import numpy as np
import argparse
import logging
from pathlib import Path
from typing import Optional
from datetime import datetime

import pandas as pd

# Add src and utils to path for imports
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / 'utils'))

from tte_ttf_algorithm import TTETTFCalculator
from battery_manager import BatteryManager
from db import DatabaseManager
from dto_classes import dto_ness_parquet


def load_config():
    """Load configuration from config.yaml"""
    config_file = Path(__file__).parent.parent / 'config.yaml'
    if not config_file.exists():
        raise FileNotFoundError(f"Config file not found: {config_file}")

    with open(config_file, 'r') as f:
        return yaml.safe_load(f)


def get_load_status_vectorized(current_series):
    """
    Vectorized state detection (1M rows in <1ms vs 16s with apply()).

    State detection with 50 mA noise floor:
    - Charging: current > 50 mA
    - Discharging: current < -50 mA
    - Rest: -50 <= current <= 50 mA
    """
    state = np.where(current_series > 50, 'charging',
            np.where(current_series < -50, 'discharging', 'rest'))
    return pd.Series(state, index=current_series.index)


def add_time_columns(data_df):
    """
    Add UTC and local time columns, plus time differences.
    Following notebook pattern from ness_utils.
    """
    data_df = data_df.sort_values(by='ts', ignore_index=True)
    data_df['utc_time'] = pd.to_datetime(data_df['ts'], unit='ms', utc=True)
    # Calculate time differences and pad with initial value
    diff_vals = np.diff(data_df['utc_time']).astype('timedelta64[s]').astype(np.int32)
    data_df['diff_time_secs'] = np.insert(diff_vals, 0, 1.0)
    return data_df


def preprocess_data(df):
    """
    Convert parquet data to algorithm format following notebook workflow.

    Steps:
    1. Apply dto_ness_parquet transformation (type conversion, ic/id split, etc.)
    2. Add time columns (UTC, time differences)
    3. Calculate net current and determine load_status (charging/discharging/rest)
    4. Return formatted data with load_status column for state determination
    """
    # Step 1: Apply DTO transformation
    print("    [DTO] Transforming data with dto_ness_parquet...")
    df = dto_ness_parquet(df).df
    print(f"    [DTO] Columns after DTO: {df.columns.tolist()}")

    # Step 2: Add time columns
    print("    [TIME] Adding time columns...")
    df = add_time_columns(df)

    # Step 3: Calculate net current (ic - id) and determine load_status
    print("    [STATE] Determining charging/discharging/rest states...")
    df['pack_current_net'] = df['ic'] - df['id']
    df['state'] = get_load_status_vectorized(df['pack_current_net'].astype(float))
    df['current_a'] = df['pack_current_net'].abs() / 1000.0  # convert mA -> A

    print(f"    [STATE] State distribution:")
    print(f"      - Charging: {(df['state'] == 'charging').sum()}")
    print(f"      - Discharging: {(df['state'] == 'discharging').sum()}")
    print(f"      - Rest: {(df['state'] == 'rest').sum()}")
    print(f"      - NaN: {df['state'].isna().sum()}")

    # Rename timestamp column for consistency with algorithm
    if 'ts' not in df.columns and 'timestamp' in df.columns:
        df = df.rename(columns={'timestamp': 'ts'})

    return df


def merge_short_discharge_sessions(df: pd.DataFrame, max_gap_minutes: float = 5.0, min_soc_change: float = 0.5) -> pd.DataFrame:
    """
    Merge short discharge sessions separated by rest/charging into continuous sessions.

    Problem: State detection is noisy, creating many short discharge bursts.
    When training decay rates from these short bursts, we learn artificially high rates.

    Solution: Merge discharge periods <max_gap_minutes apart into one continuous session.
    This results in more realistic (lower) decay rates from longer, merged sessions.

    Parameters:
    -----------
    df : pd.DataFrame
        Data with 'state' and 'soc' columns
    max_gap_minutes : float
        Merge discharge periods separated by <= this gap (default 5 minutes)
    min_soc_change : float
        Only merge sessions with > this % SOC change (default 0.5%)

    Returns:
    --------
    pd.DataFrame : Data with merged discharge sessions marked as 'discharging'
    """
    result = df.copy()

    # Ensure ts is datetime
    if result['ts'].dtype != 'datetime64[ns]':
        result['ts'] = pd.to_datetime(result['ts'], unit='ms', utc=True)

    # Get discharge rows
    discharge_mask = result['state'] == 'discharging'
    discharge_indices = result[discharge_mask].index.tolist()

    if len(discharge_indices) < 2:
        return result  # Nothing to merge

    # Find gaps in discharge periods and mark which should be merged
    indices_to_merge = set()  # Indices where we should change 'rest'/'charging' to 'discharging'

    for i in range(len(discharge_indices) - 1):
        curr_idx = discharge_indices[i]
        next_idx = discharge_indices[i + 1]

        # Time between last discharge and next discharge
        time_gap_min = (result.loc[next_idx, 'ts'] - result.loc[curr_idx, 'ts']).total_seconds() / 60.0

        # If gap is small, merge: change all rows between curr_idx and next_idx to 'discharging'
        if 0 < time_gap_min <= max_gap_minutes:
            # Check if this merge makes sense (must have enough SOC change across the full merged range)
            merged_soc_start = result.loc[curr_idx, 'soc']
            merged_soc_end = result.loc[next_idx, 'soc']
            merged_soc_change = abs(merged_soc_start - merged_soc_end)

            if merged_soc_change > min_soc_change:
                # Mark indices between curr_idx and next_idx for merging
                for j in range(curr_idx + 1, next_idx):
                    indices_to_merge.add(j)

    # Apply merges: change marked rows from 'rest'/'charging' to 'discharging'
    for idx in indices_to_merge:
        if result.loc[idx, 'state'] in ['rest', 'charging']:
            result.loc[idx, 'state'] = 'discharging'

    # Log what we did
    merged_count = len(indices_to_merge)
    if merged_count > 0:
        print(f"    [MERGE] Merged {merged_count} rows from rest/charging into discharge sessions")
        print(f"    [MERGE] Now: Discharging: {(result['state'] == 'discharging').sum()}, "
              f"Rest: {(result['state'] == 'rest').sum()}, "
              f"Charging: {(result['state'] == 'charging').sum()}")

    return result


def estimate_and_save(calculator: TTETTFCalculator, data_df: pd.DataFrame, config: dict,
                      output_file: str, label: str = "Results") -> pd.DataFrame:
    """
    Run TTE/TTF estimation and save results.

    Parameters:
    -----------
    calculator : TTETTFCalculator
        Trained calculator
    data_df : pd.DataFrame
        Preprocessed data
    config : dict
        Configuration
    output_file : str
        Output file path
    label : str
        Label for output (e.g., "Training", "Testing")

    Returns:
    --------
    pd.DataFrame : Results
    """
    print(f"\n[3] Running TTE/TTF estimation ({label})...")

    tte_params = config.get('tte_ttf', {})
    print("    [Config] TTE/TTF Parameters:")
    print(f"      - Current threshold: {tte_params.get('current_threshold_ma', 50.0)} mA")
    print(f"      - EMA window: {tte_params.get('ema_window_minutes', 20)} minutes")
    print(f"      - Session min duration: {tte_params.get('session_min_duration_minutes', 15.0)} minutes")
    print(f"      - Session min energy: {tte_params.get('session_min_energy_ah', 1.0)} Ah")
    print(f"      - TTE/TTF smoothing: {tte_params.get('tte_ttf_smoothing_factor', 0.15)}")

    tte_start = time.time()
    results_df = calculator.estimate_batch(
        data_df,
        soc_col='soc',
        capacity_col='FullCap',
        discharge_current_col='id',
        charge_current_col='ic',
        timestamp_col='ts',
        voltage_col='lv',
        state_col='state',
        batch_size=2000
    )
    tte_time = time.time() - tte_start
    print(f"    TTE/TTF estimation time: {tte_time:.2f}s")

    # Add rolling average discharge power (kW) over configurable time window
    window_min = tte_params.get('usage_window_minutes', 30)
    discharge_mask = data_df['state'] == 'discharging'

    # Instantaneous power in kW: V(V) × I(A) / 1000
    power_kw = (data_df['lv'] / 1000.0) * (data_df['id'] / 1000.0) / 1000.0
    power_kw = power_kw.where(discharge_mask, 0.0)

    # Time-based rolling mean (average power)
    power_kw.index = pd.to_datetime(data_df['ts'], unit='ms', utc=True)
    rolling_power_kw = power_kw.rolling(f'{window_min}min').mean()
    rolling_power_kw.index = results_df.index  # realign index

    results_df['average_usage_kw'] = rolling_power_kw.values.round(6)

    # Summary
    print(f"\n[4] Results Summary ({label})")
    print(f"    Generated: {len(results_df):,} rows")
    print(f"\n    Status Distribution:")
    print(results_df['status'].value_counts().to_string().replace('\n', '\n    '))

    print(f"\n    TTE/TTF Coverage:")
    print(f"    TTE populated: {results_df['tte_hours'].notna().sum():,} / {len(results_df):,}")
    print(f"    TTF populated: {results_df['ttf_hours'].notna().sum():,} / {len(results_df):,}")

    print(f"\n    Sample Output (first 5 rows):")
    cols_to_show = ['timestamp', 'voltage_v', 'current_a', 'status', 'tte_hours', 'ttf_hours']
    print(results_df[cols_to_show].head().to_string().replace('\n', '\n    '))

    # Save
    print(f"\n[5] Saving {label} results to {output_file}...")
    Path(output_file).parent.mkdir(parents=True, exist_ok=True)
    results_df.to_csv(output_file, index=False)
    print(f"    [OK] Saved {len(results_df):,} results")

    return results_df



def _build_global_fleet_model(db, label: str = "", min_count: int = 5) -> None:
    """
    Build a global fleet model by aggregating patterns across all batteries.

    This creates a '__global__' model as a cold-start fallback for batteries
    with no training data.

    Parameters:
    -----------
    db : DatabaseManager
        Database manager instance
    label : str
        Pattern label to aggregate
    min_count : int
        Minimum observation count for a pattern to be included in global model
    """
    try:
        conn = db._get_connection()
        cursor = conn.cursor()

        # Query all non-global patterns
        cursor.execute("""
            SELECT phase, soc_window, load_class, current_range,
                   rate_median, count
            FROM battery_patterns
            WHERE battery_id != '__global__' AND label = ? AND count >= ?
            ORDER BY phase, soc_window, load_class, current_range
        """, (label, min_count))

        rows = cursor.fetchall()
        if not rows:
            print(f"    [WARN] Not enough data to build global model (need count >= {min_count})")
            conn.close()
            return

        # Aggregate by (phase, soc_window, load_class, current_range)
        global_patterns = {}
        for row in rows:
            key = (row['phase'], row['soc_window'], row['load_class'], row['current_range'])
            if key not in global_patterns:
                global_patterns[key] = []
            global_patterns[key].append(row['rate_median'])

        # Compute weighted average of rate_median across all batteries
        global_stats = {}
        for key, rates in global_patterns.items():
            phase, soc_window, load_class, current_range = key
            global_stats[key] = {
                'rate_median': float(np.median(rates)),
                'rate_mean': float(np.mean(rates)),
                'rate_std': float(np.std(rates)) if len(rates) > 1 else 0.0,
                'count': len(rates)  # count = number of batteries contributing
            }

        # Split into discharge and charge
        discharge_stats = {}
        charge_stats = {}
        for (phase, soc_window, load_class, current_range), stats in global_stats.items():
            key = (soc_window, load_class, current_range)
            if phase == 'discharge':
                discharge_stats[key] = stats
            elif phase == 'charge':
                charge_stats[key] = stats

        # Save global model
        db.save_patterns('__global__', discharge_stats, charge_stats, label)
        print(f"    [OK] Global fleet model saved ({len(discharge_stats)} discharge patterns)")
        conn.close()

    except Exception as e:
        print(f"    [ERROR] Failed to build global model: {e}")


def run_train_all_batteries(config: dict, project_root: Path):
    """
    TRAIN_ALL_BATTERIES mode: Train on all battery files in data folder.

    Discovers all .parquet files, trains each separately, saves patterns per battery.
    """
    print("\n" + "="*80)
    print("MODE: TRAIN_ALL_BATTERIES")
    print("="*80)

    data_dir = project_root / "data"
    output_dir = project_root / config['output']['output_dir']
    training_data_dir = project_root / config['output']['training_data_dir']
    output_dir.mkdir(parents=True, exist_ok=True)
    training_data_dir.mkdir(parents=True, exist_ok=True)

    # Get database path from config or use default
    db_path = project_root / config.get('database', {}).get('path', 'battery_patterns.db')
    battery_mgr = BatteryManager(str(data_dir), str(training_data_dir), str(db_path))

    # Discover all batteries
    batteries = battery_mgr.discover_batteries()
    if not batteries:
        print("[ERROR] No battery files found in data/ folder")
        return

    print(f"\n[DISCOVERED] {len(batteries)} battery files:")
    for battery_id, file_path in batteries.items():
        print(f"  [OK] {battery_id}: {file_path.name}")

    # Train each battery
    tte_cfg = config.get('tte_ttf', {})
    patterns_label = config['execution'].get('patterns_label', 'multi_battery')

    for battery_id, data_file in batteries.items():
        print(f"\n{'='*80}")
        print(f"[TRAINING] Battery: {battery_id}")
        print(f"{'='*80}")

        # Load data
        print(f"[1] Loading {battery_id} data...")
        data_df = pd.read_parquet(data_file)
        print(f"    Loaded {len(data_df):,} rows")

        # Filter by month if specified
        training_month = config['execution'].get('training_month', '')
        if training_month:
            print(f"    Filtering to month: {training_month}...")
            data_df['month'] = pd.to_datetime(data_df['timestamp'], unit='ms', utc=True).dt.strftime('%Y-%m')
            data_df = data_df[data_df['month'] == training_month]
            print(f"    Filtered to {len(data_df):,} rows for {training_month}")

        # Preprocess
        print("[2] Preprocessing...")
        data_df = preprocess_data(data_df)

        # Merge short discharge sessions to avoid learning inflated decay rates
        print("[2b] Merging short discharge sessions...")
        data_df = merge_short_discharge_sessions(data_df, max_gap_minutes=5.0, min_soc_change=0.5)

        # Level 2 fallback: Check minimum discharge rows before training
        discharge_rows = (data_df['state'] == 'discharging').sum()
        min_discharge_rows = tte_cfg.get('min_discharge_rows', 100)
        if discharge_rows < min_discharge_rows:
            print(f"    [WARN] Only {discharge_rows} discharge rows — below minimum {min_discharge_rows} for reliable training")

        # Train
        print(f"[3] Training algorithm on {battery_id}...")
        calculator = TTETTFCalculator(
            session_min_duration_minutes=tte_cfg.get('session_min_duration_minutes', 15.0),
            session_min_energy_ah=tte_cfg.get('session_min_energy_ah', 1.0),
            tte_ttf_smoothing_factor=tte_cfg.get('tte_ttf_smoothing_factor', 0.15)
        )

        print(f"    Learning SOC decay patterns and load profiles...")
        calculator.train(
            data_df,
            soc_col='soc',
            current_col='current_a',
            voltage_col='lv',
            status_col='state',
            timestamp_col='ts',
            window_minutes=60.0  # Use 1-hour windows instead of 5-min to capture long-term decay
        )

        # Estimate
        print(f"[4] Estimating TTE/TTF for {battery_id}...")
        output_file = output_dir / f'tte_ttf_{battery_id}.csv'
        results_df = estimate_and_save(
            calculator, data_df, config,
            str(output_file),
            f"Battery {battery_id}"
        )

        # Save patterns
        print(f"[5] Saving patterns for {battery_id}...")
        battery_mgr.save_battery_patterns(battery_id, calculator, patterns_label)

    # Build global fleet model from all trained batteries (for cold-start fallback)
    print("\n[GLOBAL MODEL] Aggregating patterns across all batteries...")
    _build_global_fleet_model(battery_mgr.db, patterns_label, min_count=5)

    print("\n" + "="*80)
    print("[SUCCESS] All Batteries Trained")
    print("="*80)
    battery_mgr.print_available_batteries()


def run_apply_battery(config: dict, project_root: Path):
    """
    APPLY_BATTERY mode: Auto-discover all batteries in data/, apply saved patterns.

    For each battery found:
    - Check if patterns exist
    - If yes, apply them (no retraining)
    - Save results
    """
    print("\n" + "="*80)
    print("MODE: APPLY_BATTERY (Auto-discover all)")
    print("="*80)

    data_dir = project_root / "data"
    output_dir = project_root / config['output']['output_dir']
    training_data_dir = project_root / config['output']['training_data_dir']
    output_dir.mkdir(parents=True, exist_ok=True)
    training_data_dir.mkdir(parents=True, exist_ok=True)

    # Get database path from config or use default
    db_path = project_root / config.get('database', {}).get('path', 'battery_patterns.db')
    battery_mgr = BatteryManager(str(data_dir), str(training_data_dir), str(db_path))

    # Discover all batteries
    batteries = battery_mgr.discover_batteries()
    if not batteries:
        print("[ERROR] No battery files found in data/ folder")
        return

    print(f"\n[DISCOVERED] {len(batteries)} batteries in data/:")
    for battery_id, file_path in batteries.items():
        print(f"  [OK] {battery_id}: {file_path.name}")

    # Apply patterns to each battery
    tte_cfg = config.get('tte_ttf', {})
    patterns_label = config['execution'].get('patterns_label', '')

    for battery_id, data_file in batteries.items():
        print(f"\n{'='*80}")
        print(f"[APPLYING] Battery: {battery_id}")
        print(f"{'='*80}")

        # Load data
        print(f"[1] Loading {battery_id} data...")
        try:
            data_df = pd.read_parquet(data_file)
            print(f"    Loaded {len(data_df):,} rows")

            # Filter by month if specified
            apply_month = config['execution'].get('apply_month', '')
            if apply_month:
                print(f"    Filtering to month: {apply_month}...")
                data_df['month'] = pd.to_datetime(data_df['timestamp'], unit='ms', utc=True).dt.strftime('%Y-%m')
                data_df = data_df[data_df['month'] == apply_month]
                print(f"    Filtered to {len(data_df):,} rows for {apply_month}")

        except Exception as e:
            print(f"    [ERROR] Error loading data: {e}")
            continue

        # Preprocess
        print("[2] Preprocessing...")
        try:
            data_df = preprocess_data(data_df)
        except Exception as e:
            print(f"    [ERROR] Error preprocessing: {e}")
            continue

        # Load patterns
        print(f"[3] Loading patterns...")
        calculator = TTETTFCalculator(
            session_min_duration_minutes=tte_cfg.get('session_min_duration_minutes', 15.0),
            session_min_energy_ah=tte_cfg.get('session_min_energy_ah', 1.0),
            tte_ttf_smoothing_factor=tte_cfg.get('tte_ttf_smoothing_factor', 0.15),
            current_thresholds=tte_cfg.get('current_thresholds_a', [0.5, 2.0, 5.0]),
            session_high_confidence_minutes=tte_cfg.get('session_high_confidence_minutes', 15.0),
            session_high_confidence_energy_ah=tte_cfg.get('session_high_confidence_energy_ah', 1.0)
        )

        default_rate = tte_cfg.get('default_discharge_rate_pct_per_min', 0.15)
        if not battery_mgr.load_battery_patterns(battery_id, calculator, patterns_label, default_rate):
            print(f"    [WARN] Patterns not found for {battery_id} and Level 4 fallback unavailable (skipping)")
            continue

        # Estimate
        print(f"[4] Estimating TTE/TTF...")
        output_file = output_dir / f'tte_ttf_{battery_id}_applied.csv'
        try:
            estimate_and_save(calculator, data_df, config, str(output_file), f"Battery {battery_id} (Applied)")
        except Exception as e:
            print(f"    [ERROR] Error estimating: {e}")
            continue

    print("\n" + "="*80)
    print("[SUCCESS] All Batteries Applied")
    print("="*80)


def compute_actual_tte(results_df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute actual TTE by merging short discharge sessions into continuous sessions.

    Problem: State detection (charging/discharging/rest) can be noisy, creating many
    short 20-second "sessions" with 0% SOC change. These are validation noise.

    Solution: Merge consecutive discharge periods separated by <5 min rest/charging
    into one continuous session.

    Parameters:
    -----------
    results_df : pd.DataFrame
        Results with columns: timestamp, status, soc, tte_hours

    Returns:
    --------
    pd.DataFrame : With added columns:
        - actual_tte_hours: actual time remaining until meaningful session ended
        - error_hours: predicted_tte - actual_tte
        - error_pct: (error / actual) * 100
    """
    results = results_df.copy()
    results['actual_tte_hours'] = np.nan
    results['error_hours'] = np.nan
    results['error_pct'] = np.nan

    # Sort by timestamp
    results = results.sort_values('timestamp').reset_index(drop=True)

    discharge_mask = results['status'] == 'discharging'
    discharge_indices = results[discharge_mask].index.tolist()

    if not discharge_indices:
        return results

    # Group discharge periods into continuous sessions (merge those < 5 min apart)
    sessions = []  # List of (start_idx, end_idx, start_soc, end_soc, duration_hours)
    current_session_start = discharge_indices[0]
    current_session_start_soc = results.loc[current_session_start, 'soc']

    for i in range(1, len(discharge_indices)):
        prev_idx = discharge_indices[i-1]
        curr_idx = discharge_indices[i]

        time_gap_hours = (results.loc[curr_idx, 'timestamp'] - results.loc[prev_idx, 'timestamp']).total_seconds() / 3600.0

        # If gap > 5 minutes, end current session
        if time_gap_hours > 5/60:  # 5 minutes
            # End session
            session_end_idx = prev_idx
            session_end_soc = results.loc[session_end_idx, 'soc']
            session_duration = (results.loc[session_end_idx, 'timestamp'] - results.loc[current_session_start, 'timestamp']).total_seconds() / 3600.0
            soc_change = current_session_start_soc - session_end_soc

            # Only keep if meaningful duration and SOC change
            if session_duration > 0.1 and soc_change > 0.5:
                sessions.append((current_session_start, session_end_idx, current_session_start_soc, session_end_soc))

            # Start new session
            current_session_start = curr_idx
            current_session_start_soc = results.loc[curr_idx, 'soc']

    # Don't forget the last session
    last_idx = discharge_indices[-1]
    session_end_soc = results.loc[last_idx, 'soc']
    session_duration = (results.loc[last_idx, 'timestamp'] - results.loc[current_session_start, 'timestamp']).total_seconds() / 3600.0
    soc_change = current_session_start_soc - session_end_soc
    if session_duration > 0.1 and soc_change > 0.5:
        sessions.append((current_session_start, last_idx, current_session_start_soc, session_end_soc))

    # For each valid session, compute actual_tte for all discharge rows in it
    for session_start_idx, session_end_idx, session_start_soc, session_end_soc in sessions:
        session_duration = (results.loc[session_end_idx, 'timestamp'] - results.loc[session_start_idx, 'timestamp']).total_seconds() / 3600.0
        decay_rate = (session_start_soc - session_end_soc) / session_duration if session_duration > 0 else 0

        if decay_rate <= 0:
            continue

        # For each discharge row in this session
        for idx in discharge_indices:
            if not (session_start_idx <= idx <= session_end_idx):
                continue

            row_ts = results.loc[idx, 'timestamp']
            row_soc = results.loc[idx, 'soc']

            # Time to session end
            time_to_end = (results.loc[session_end_idx, 'timestamp'] - row_ts).total_seconds() / 3600.0

            # Extrapolate from session end to 0%
            extrapolated = session_end_soc / decay_rate if decay_rate > 0.001 else 0

            actual_tte = max(0, time_to_end + extrapolated)
            results.loc[idx, 'actual_tte_hours'] = actual_tte

    # Compute errors
    valid_mask = results['tte_hours'].notna() & results['actual_tte_hours'].notna()
    results.loc[valid_mask, 'error_hours'] = \
        results.loc[valid_mask, 'tte_hours'] - results.loc[valid_mask, 'actual_tte_hours']

    # Percentage error
    nonzero_actual = (results['actual_tte_hours'] > 0.001) & valid_mask
    results.loc[nonzero_actual, 'error_pct'] = \
        (results.loc[nonzero_actual, 'error_hours'] / results.loc[nonzero_actual, 'actual_tte_hours']) * 100.0

    return results


def compute_validation_metrics(results_df: pd.DataFrame) -> dict:
    """
    Compute comprehensive validation metrics including Gaussian distribution analysis.

    Parameters:
    -----------
    results_df : pd.DataFrame
        Results with columns: error_hours, tte_hours, ttf_hours, status, soc, confidence, ...

    Returns:
    --------
    dict : Metrics including:
        - error_distribution: mean, std, min, max, percentiles
        - accuracy_metrics: MAE, RMSE, MAPE, coverage
        - gaussian_analysis: normality test, sigma intervals
        - stratified: by confidence, soc_range, current
        - temporal_consistency: monotonicity violations
    """
    metrics = {}

    # Filter to discharge rows with valid errors
    discharge = results_df[results_df['status'] == 'discharging'].copy()
    valid_errors = discharge[discharge['error_hours'].notna()]['error_hours']

    if len(valid_errors) == 0:
        return {"error": "No valid discharge errors to analyze"}

    # ========== ERROR DISTRIBUTION ==========
    metrics['error_distribution'] = {
        'count': len(valid_errors),
        'mean': float(valid_errors.mean()),
        'std': float(valid_errors.std()),
        'min': float(valid_errors.min()),
        'max': float(valid_errors.max()),
        'p5': float(valid_errors.quantile(0.05)),
        'p25': float(valid_errors.quantile(0.25)),
        'p50': float(valid_errors.quantile(0.50)),
        'p75': float(valid_errors.quantile(0.75)),
        'p95': float(valid_errors.quantile(0.95)),
    }

    # ========== GAUSSIAN ANALYSIS ==========
    from scipy import stats

    mean_err = valid_errors.mean()
    std_err = valid_errors.std()

    # Normality test
    if len(valid_errors) > 20:
        stat_val, p_value = stats.normaltest(valid_errors)
        is_normal = p_value > 0.05
    else:
        stat_val, p_value = stats.shapiro(valid_errors)
        is_normal = p_value > 0.05

    metrics['gaussian_analysis'] = {
        'is_normal': is_normal,
        'normality_p_value': float(p_value),
        'mean_error_hours': float(mean_err),
        'std_dev_hours': float(std_err),
        'mean_error_minutes': float(mean_err * 60),
        'interval_1sigma': {
            'low': float(mean_err - std_err),
            'high': float(mean_err + std_err),
            'coverage_pct': float((np.abs(valid_errors - mean_err) <= std_err).sum() / len(valid_errors) * 100)
        },
        'interval_2sigma': {
            'low': float(mean_err - 2*std_err),
            'high': float(mean_err + 2*std_err),
            'coverage_pct': float((np.abs(valid_errors - mean_err) <= 2*std_err).sum() / len(valid_errors) * 100)
        },
        'interval_3sigma': {
            'low': float(mean_err - 3*std_err),
            'high': float(mean_err + 3*std_err),
            'coverage_pct': float((np.abs(valid_errors - mean_err) <= 3*std_err).sum() / len(valid_errors) * 100)
        }
    }

    # ========== ACCURACY METRICS ==========
    valid_pred = discharge[(discharge['tte_hours'].notna()) & (discharge['actual_tte_hours'].notna())]

    if len(valid_pred) > 0:
        abs_errors = np.abs(valid_pred['error_hours'])
        abs_pct_errors = np.abs(valid_pred['error_pct'].dropna())

        mae = float(abs_errors.mean())
        rmse = float(np.sqrt((valid_pred['error_hours'] ** 2).mean()))
        mape = float(abs_pct_errors.mean()) if len(abs_pct_errors) > 0 else np.nan

        metrics['accuracy_metrics'] = {
            'MAE_hours': mae,
            'MAE_minutes': mae * 60,
            'RMSE_hours': rmse,
            'MAPE_pct': mape,
            'within_1h_pct': float((abs_errors <= 1.0).sum() / len(abs_errors) * 100),
            'within_30min_pct': float((abs_errors <= 0.5).sum() / len(abs_errors) * 100),
            'within_15min_pct': float((abs_errors <= 0.25).sum() / len(abs_errors) * 100),
        }

    # ========== CALIBRATION BY CONFIDENCE ==========
    metrics['by_confidence'] = {}
    for conf in ['high', 'medium', 'low']:
        conf_data = discharge[(discharge['confidence'] == conf) & (discharge['error_hours'].notna())]
        if len(conf_data) > 0:
            errors = conf_data['error_hours']
            abs_errors = np.abs(errors)
            metrics['by_confidence'][conf] = {
                'count': len(conf_data),
                'MAE_hours': float(abs_errors.mean()),
                'std_hours': float(errors.std()),
                'mean_bias_hours': float(errors.mean()),
            }

    # ========== STRATIFIED BY SOC RANGE ==========
    metrics['by_soc_range'] = {}
    soc_bins = [(80, 100), (50, 80), (20, 50), (0, 20)]
    for low, high in soc_bins:
        soc_data = discharge[(discharge['soc'] >= low) & (discharge['soc'] < high) &
                             (discharge['error_hours'].notna())]
        if len(soc_data) > 0:
            errors = soc_data['error_hours']
            abs_errors = np.abs(errors)
            metrics['by_soc_range'][f'{low}-{high}%'] = {
                'count': len(soc_data),
                'MAE_hours': float(abs_errors.mean()),
                'std_hours': float(errors.std()),
            }

    # ========== TEMPORAL CONSISTENCY ==========
    discharge_sorted = discharge.sort_values('timestamp')
    discharge_valid = discharge_sorted[discharge_sorted['tte_hours'].notna()]

    if len(discharge_valid) > 1:
        time_diffs = discharge_valid['timestamp'].diff().dt.total_seconds() / 3600.0
        tte_diffs = discharge_valid['tte_hours'].diff()

        # Expected: tte_diffs ≈ -time_diffs (TTE decreases by time elapsed)
        expected_decrease = -time_diffs

        # Count monotonicity violations (TTE increased when it shouldn't)
        violations = (tte_diffs > -time_diffs / 2).sum()  # Allow some tolerance
        violation_pct = violations / len(tte_diffs) * 100 if len(tte_diffs) > 0 else 0

        metrics['temporal_consistency'] = {
            'total_rows': len(discharge_valid),
            'monotonicity_violations': int(violations),
            'violation_pct': float(violation_pct),
            'mean_tte_change_rate': float(tte_diffs.mean() / time_diffs.mean()) if time_diffs.mean() > 0 else 0,
        }

    return metrics


def generate_validation_charts(battery_id: str, results_df: pd.DataFrame, validation_dir: Path):
    """
    Generate visualization charts for validation results.

    Creates:
    1. Error distribution histogram with Gaussian fit
    2. Box plots by confidence level and SOC range
    3. Error over time scatter plot
    4. Calibration curve (confidence vs actual error)
    5. Summary statistics table
    """
    try:
        import matplotlib.pyplot as plt
        import seaborn as sns
        from scipy import stats
    except ImportError:
        print("    [WARN] matplotlib/seaborn not available, skipping charts")
        return

    validation_dir.mkdir(parents=True, exist_ok=True)

    # Filter to discharge with valid errors
    discharge = results_df[results_df['status'] == 'discharging'].copy()
    valid_errors = discharge[discharge['error_hours'].notna()]['error_hours'].values

    if len(valid_errors) == 0:
        return

    # Set style
    sns.set_style("whitegrid")
    plt.rcParams['figure.figsize'] = (12, 6)

    # ========== Chart 1: Error Distribution with Gaussian Fit ==========
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.hist(valid_errors, bins=50, density=True, alpha=0.7, color='steelblue', edgecolor='black', label='Prediction errors')

    # Fit Gaussian
    mu, sigma = valid_errors.mean(), valid_errors.std()
    x = np.linspace(valid_errors.min(), valid_errors.max(), 100)
    gaussian = stats.norm.pdf(x, mu, sigma)
    ax.plot(x, gaussian, 'r-', linewidth=2, label=f'Gaussian fit (μ={mu:.2f}, σ={sigma:.2f})')

    ax.set_xlabel('Prediction Error (hours)', fontsize=11)
    ax.set_ylabel('Density', fontsize=11)
    ax.set_title(f'{battery_id} — Error Distribution', fontsize=13, fontweight='bold')
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(validation_dir / f'01_error_distribution_{battery_id}.png', dpi=150)
    plt.close(fig)

    # ========== Chart 2: Error by Confidence Level ==========
    fig, ax = plt.subplots(figsize=(10, 6))
    confidence_data = []
    confidence_labels = []
    for conf in ['high', 'medium', 'low']:
        conf_errors = discharge[(discharge['confidence'] == conf) & (discharge['error_hours'].notna())]['error_hours']
        if len(conf_errors) > 0:
            confidence_data.append(conf_errors)
            confidence_labels.append(f'{conf.upper()}\n(n={len(conf_errors)})')

    bp = ax.boxplot(confidence_data, labels=confidence_labels, patch_artist=True)
    for patch, color in zip(bp['boxes'], ['lightgreen', 'lightyellow', 'lightcoral']):
        patch.set_facecolor(color)
    ax.axhline(y=0, color='red', linestyle='--', linewidth=1.5, alpha=0.7, label='Perfect prediction')
    ax.set_ylabel('Prediction Error (hours)', fontsize=11)
    ax.set_title(f'{battery_id} — Error by Confidence Level', fontsize=13, fontweight='bold')
    ax.grid(True, alpha=0.3, axis='y')
    ax.legend()
    fig.tight_layout()
    fig.savefig(validation_dir / f'02_error_by_confidence_{battery_id}.png', dpi=150)
    plt.close(fig)

    # ========== Chart 3: Error by SOC Range ==========
    fig, ax = plt.subplots(figsize=(10, 6))
    soc_data = []
    soc_labels = []
    soc_ranges = [(0, 20), (20, 50), (50, 80), (80, 100)]
    for low, high in soc_ranges:
        soc_errors = discharge[(discharge['soc'] >= low) & (discharge['soc'] < high) &
                              (discharge['error_hours'].notna())]['error_hours']
        if len(soc_errors) > 0:
            soc_data.append(soc_errors)
            soc_labels.append(f'{low}-{high}%\n(n={len(soc_errors)})')

    bp = ax.boxplot(soc_data, labels=soc_labels, patch_artist=True)
    colors = ['lightcoral', 'lightyellow', 'lightblue', 'lightgreen']
    for patch, color in zip(bp['boxes'], colors):
        patch.set_facecolor(color)
    ax.axhline(y=0, color='red', linestyle='--', linewidth=1.5, alpha=0.7)
    ax.set_ylabel('Prediction Error (hours)', fontsize=11)
    ax.set_title(f'{battery_id} — Error by SOC Range', fontsize=13, fontweight='bold')
    ax.grid(True, alpha=0.3, axis='y')
    fig.tight_layout()
    fig.savefig(validation_dir / f'03_error_by_soc_{battery_id}.png', dpi=150)
    plt.close(fig)

    # ========== Chart 4: Error Over Time ==========
    fig, ax = plt.subplots(figsize=(14, 6))
    discharge_sorted = discharge.sort_values('timestamp')
    discharge_valid = discharge_sorted[discharge_sorted['error_hours'].notna()]

    scatter = ax.scatter(discharge_valid['timestamp'], discharge_valid['error_hours'],
                        c=discharge_valid['soc'], cmap='RdYlGn_r', alpha=0.5, s=10)
    ax.axhline(y=0, color='red', linestyle='--', linewidth=2, label='Perfect prediction')
    ax.set_xlabel('Time', fontsize=11)
    ax.set_ylabel('Prediction Error (hours)', fontsize=11)
    ax.set_title(f'{battery_id} — Error Over Time (colored by SOC)', fontsize=13, fontweight='bold')
    cbar = plt.colorbar(scatter, ax=ax)
    cbar.set_label('SOC (%)', fontsize=10)
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(validation_dir / f'04_error_over_time_{battery_id}.png', dpi=150)
    plt.close(fig)

    # ========== Chart 5: Calibration Curve ==========
    fig, ax = plt.subplots(figsize=(10, 6))
    confidence_bins = {'high': [], 'medium': [], 'low': []}
    for conf in ['high', 'medium', 'low']:
        conf_data = discharge[discharge['confidence'] == conf]
        if len(conf_data) > 0:
            abs_errors = np.abs(conf_data['error_hours'].dropna())
            within_1h = (abs_errors <= 1.0).sum() / len(abs_errors) * 100 if len(abs_errors) > 0 else 0
            confidence_bins[conf] = within_1h

    confs = list(confidence_bins.keys())
    within_1h_pcts = list(confidence_bins.values())
    colors = ['green', 'orange', 'red']
    bars = ax.bar(confs, within_1h_pcts, color=colors, alpha=0.7, edgecolor='black')
    ax.set_ylabel('% Within ±1 Hour', fontsize=11)
    ax.set_title(f'{battery_id} — Calibration (% Predictions Within ±1h)', fontsize=13, fontweight='bold')
    ax.set_ylim(0, 100)
    for bar, pct in zip(bars, within_1h_pcts):
        height = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2., height,
               f'{pct:.1f}%', ha='center', va='bottom', fontsize=11, fontweight='bold')
    ax.grid(True, alpha=0.3, axis='y')
    fig.tight_layout()
    fig.savefig(validation_dir / f'05_calibration_{battery_id}.png', dpi=150)
    plt.close(fig)

    print(f"    [OK] Generated 5 validation charts")


def print_validation_report(battery_id: str, metrics: dict, results_df: pd.DataFrame):
    """Pretty-print validation metrics."""
    print("\n" + "="*80)
    print(f"  TTE/TTF VALIDATION REPORT — {battery_id}")
    print("="*80)

    if "error" in metrics:
        print(f"  ⚠ {metrics['error']}")
        return

    # Summary
    discharge = results_df[results_df['status'] == 'discharging']
    valid_tte = discharge[discharge['tte_hours'].notna()]
    valid_errors = discharge[discharge['error_hours'].notna()]

    print(f"\n  Validation Data:")
    print(f"    Total discharge rows:       {len(discharge):>10,}")
    print(f"    Rows with TTE:              {len(valid_tte):>10,} ({100*len(valid_tte)/max(1,len(discharge)):.1f}%)")
    print(f"    Rows with actual_tte:       {len(valid_errors):>10,} ({100*len(valid_errors)/max(1,len(discharge)):.1f}%)")

    # Error distribution
    if 'error_distribution' in metrics:
        ed = metrics['error_distribution']
        print(f"\n  ERROR DISTRIBUTION (predicted - actual):")
        print(f"    Mean bias:          {ed['mean']:>+8.2f} hours ({ed['mean']*60:>+7.1f} min)")
        print(f"    Std deviation:       {ed['std']:>8.2f} hours")
        print(f"    Range:          [{ed['min']:>7.2f}, {ed['max']:>7.2f}] hours")
        print(f"    Percentiles: p50={ed['p50']:>6.2f}h, p25={ed['p25']:>6.2f}h, p75={ed['p75']:>6.2f}h")

    # Gaussian analysis
    if 'gaussian_analysis' in metrics:
        ga = metrics['gaussian_analysis']
        normal_str = "[OK] Gaussian" if ga['is_normal'] else "[!] Non-normal"
        print(f"\n  GAUSSIAN ANALYSIS:")
        print(f"    Normality test (p>0.05):    {normal_str} (p={ga['normality_p_value']:.3f})")
        print(f"    Mean +/- Std:               {ga['mean_error_hours']:>+7.2f} +/- {ga['std_dev_hours']:>6.2f} hours")
        print(f"    68% within +/-1sigma:       [{ga['interval_1sigma']['low']:>7.2f}, {ga['interval_1sigma']['high']:>7.2f}] ({ga['interval_1sigma']['coverage_pct']:.1f}%)")
        print(f"    95% within +/-2sigma:       [{ga['interval_2sigma']['low']:>7.2f}, {ga['interval_2sigma']['high']:>7.2f}] ({ga['interval_2sigma']['coverage_pct']:.1f}%)")

    # Accuracy metrics
    if 'accuracy_metrics' in metrics:
        am = metrics['accuracy_metrics']
        print(f"\n  ACCURACY METRICS:")
        print(f"    MAE (Mean Absolute Error):   {am['MAE_hours']:>8.2f} hours ({am['MAE_minutes']:>6.1f} min)")
        print(f"    RMSE:                        {am['RMSE_hours']:>8.2f} hours")
        if not np.isnan(am['MAPE_pct']):
            print(f"    MAPE:                        {am['MAPE_pct']:>8.1f}%")
        print(f"    Within ±1 hour:              {am['within_1h_pct']:>8.1f}%")
        print(f"    Within ±30 min:              {am['within_30min_pct']:>8.1f}%")
        print(f"    Within ±15 min:              {am['within_15min_pct']:>8.1f}%")

    # By confidence
    if 'by_confidence' in metrics:
        print(f"\n  BY CONFIDENCE LEVEL:")
        for conf in ['high', 'medium', 'low']:
            if conf in metrics['by_confidence']:
                bc = metrics['by_confidence'][conf]
                print(f"    {conf.upper():>7}: MAE={bc['MAE_hours']:>6.2f}h, bias={bc['mean_bias_hours']:>+6.2f}h, n={bc['count']:>6,}")

    # By SOC range
    if 'by_soc_range' in metrics:
        print(f"\n  BY SOC RANGE:")
        for soc_range, data in sorted(metrics['by_soc_range'].items()):
            print(f"    {soc_range:>8}: MAE={data['MAE_hours']:>6.2f}h, n={data['count']:>6,}")

    # Temporal consistency
    if 'temporal_consistency' in metrics:
        tc = metrics['temporal_consistency']
        print(f"\n  TEMPORAL CONSISTENCY:")
        print(f"    Monotonicity violations:     {tc['violation_pct']:>8.1f}% ({tc['monotonicity_violations']:>5,} / {tc['total_rows']:>6,})")
        print(f"    Mean TTE change rate:        {tc['mean_tte_change_rate']:>8.2f} (ideal ~= -1.0)")

    print("\n" + "="*80)


def run_validate(config: dict, project_root: Path):
    """
    Validate TTE/TTF predictions by comparing with actual outcomes.

    Requires:
    1. Output CSV files from train_all_batteries or apply_battery mode
    2. Patterns already trained and saved

    Outputs to: output/validation/ folder
    """
    output_dir = project_root / config['output'].get('output_dir', 'output')
    validation_dir = output_dir / 'validation'
    validation_dir.mkdir(parents=True, exist_ok=True)

    battery_mgr = BatteryManager(
        data_dir=str(project_root / "data"),
        patterns_dir=str(project_root / config['output'].get('training_data_dir', 'training_data')),
        db_path=str(project_root / config['database'].get('path', 'battery_patterns.db'))
    )

    print("\n[VALIDATION] Starting TTE/TTF validation...")

    batteries = battery_mgr.discover_batteries()
    if not batteries:
        print("[ERROR] No battery files found in data/ folder")
        return

    print(f"\n[DISCOVERED] {len(batteries)} batteries in data/:")
    for battery_id, file_path in batteries.items():
        print(f"  [OK] {battery_id}: {file_path.name}")

    validate_month = config['execution'].get('validate_month', '')

    for battery_id, data_file in batteries.items():
        print(f"\n{'='*80}")
        print(f"[VALIDATING] Battery: {battery_id}")
        print(f"{'='*80}")

        # Load data
        print(f"[1] Loading {battery_id} data...")
        try:
            data_df = pd.read_parquet(data_file)
            print(f"    Loaded {len(data_df):,} rows")

            if validate_month:
                print(f"    Filtering to month: {validate_month}...")
                data_df['month'] = pd.to_datetime(data_df['timestamp'], unit='ms', utc=True).dt.strftime('%Y-%m')
                data_df = data_df[data_df['month'] == validate_month]
                print(f"    Filtered to {len(data_df):,} rows for {validate_month}")
        except Exception as e:
            print(f"    [ERROR] Error loading data: {e}")
            continue

        # Preprocess
        print("[2] Preprocessing...")
        try:
            data_df = preprocess_data(data_df)
        except Exception as e:
            print(f"    [ERROR] Error preprocessing: {e}")
            continue

        # Load output CSV (try multiple filename patterns)
        output_file = None
        for pattern in [f'tte_ttf_results_{battery_id}.csv',
                       f'tte_ttf_{battery_id}_applied.csv',
                       f'tte_ttf_{battery_id}.csv']:
            candidate = output_dir / pattern
            if candidate.exists():
                output_file = candidate
                break

        if output_file is None:
            print(f"[3] Loading predictions...")
            print(f"    [ERROR] No output file found for {battery_id}")
            print(f"    Tried: tte_ttf_results_{battery_id}.csv")
            print(f"           tte_ttf_{battery_id}_applied.csv")
            print(f"           tte_ttf_{battery_id}.csv")
            print(f"    Run train_all_batteries or apply_battery mode first")
            continue

        print(f"[3] Loading predictions from {output_file.name}...")
        try:
            results_df = pd.read_csv(output_file)
            print(f"    Loaded {len(results_df):,} predictions")
        except Exception as e:
            print(f"    [ERROR] Error loading CSV: {e}")
            continue

        # Compute actual TTE
        print("[4] Computing actual TTE...")
        try:
            # Handle ISO8601 timestamps with timezone info
            if isinstance(results_df['timestamp'].iloc[0], str):
                results_df['timestamp'] = pd.to_datetime(results_df['timestamp'], format='ISO8601', utc=True)
            else:
                results_df['timestamp'] = pd.to_datetime(results_df['timestamp'])
            results_with_actual = compute_actual_tte(results_df)
            valid_count = results_with_actual[results_with_actual['actual_tte_hours'].notna()].shape[0]
            print(f"    Computed actual TTE for {valid_count:,} rows")
        except Exception as e:
            print(f"    [ERROR] Error computing actual TTE: {e}")
            continue

        # PATH 3: Filter to "big" discharge sessions (>5 min, >0.5% SOC change)
        print("[4b] PATH 3: Filtering to big discharge sessions (>5 min, >0.5% SOC)...")
        discharge_mask = results_with_actual['status'] == 'discharging'
        discharge_indices = results_with_actual[discharge_mask].index.tolist()
        big_session_indices = []

        if discharge_indices:
            current_session_start = discharge_indices[0]
            current_session_start_soc = results_with_actual.loc[current_session_start, 'soc']

            for i in range(1, len(discharge_indices)):
                prev_idx = discharge_indices[i-1]
                curr_idx = discharge_indices[i]
                time_gap_hours = (results_with_actual.loc[curr_idx, 'timestamp'] - results_with_actual.loc[prev_idx, 'timestamp']).total_seconds() / 3600.0

                if time_gap_hours > 5/60:  # 5 minutes
                    session_end_idx = prev_idx
                    session_end_soc = results_with_actual.loc[session_end_idx, 'soc']
                    session_duration = (results_with_actual.loc[session_end_idx, 'timestamp'] - results_with_actual.loc[current_session_start, 'timestamp']).total_seconds() / 3600.0
                    soc_change = current_session_start_soc - session_end_soc

                    if session_duration > 5/60 and soc_change > 0.5:  # >5 min and >0.5% SOC
                        for idx in range(current_session_start, session_end_idx + 1):
                            if idx in discharge_indices:
                                big_session_indices.append(idx)

                    current_session_start = curr_idx
                    current_session_start_soc = results_with_actual.loc[curr_idx, 'soc']

            # Handle last session
            if len(discharge_indices) > 0:
                session_end_idx = discharge_indices[-1]
                session_end_soc = results_with_actual.loc[session_end_idx, 'soc']
                session_duration = (results_with_actual.loc[session_end_idx, 'timestamp'] - results_with_actual.loc[current_session_start, 'timestamp']).total_seconds() / 3600.0
                soc_change = current_session_start_soc - session_end_soc

                if session_duration > 5/60 and soc_change > 0.5:
                    for idx in range(current_session_start, session_end_idx + 1):
                        if idx in discharge_indices:
                            big_session_indices.append(idx)

        results_big_sessions = results_with_actual.loc[big_session_indices].copy() if big_session_indices else results_with_actual.iloc[0:0]
        print(f"    Filtered to {len(results_big_sessions):,} rows in big sessions ({100*len(results_big_sessions)/len(results_with_actual):.1f}% of discharge rows)")

        # Compute metrics
        print("[5] Computing validation metrics...")
        try:
            metrics = compute_validation_metrics(results_big_sessions if len(results_big_sessions) > 0 else results_with_actual)
        except Exception as e:
            print(f"    [ERROR] Error computing metrics: {e}")
            continue

        # Print report (on big sessions)
        print_validation_report(battery_id, metrics, results_big_sessions if len(results_big_sessions) > 0 else results_with_actual)

        # Generate charts (on big sessions)
        print(f"[6] Generating validation charts...")
        try:
            generate_validation_charts(battery_id, results_big_sessions if len(results_big_sessions) > 0 else results_with_actual, validation_dir)
        except Exception as e:
            print(f"    [WARN] Error generating charts: {e}")

        # Save validation CSV to validation folder
        val_output_file = validation_dir / f'validation_{battery_id}.csv'
        print(f"[7] Saving validation CSV to validation/{val_output_file.name}...")
        cols_to_save = ['timestamp', 'soc', 'status', 'tte_hours', 'actual_tte_hours',
                       'error_hours', 'error_pct', 'confidence']
        cols_exist = [c for c in cols_to_save if c in results_with_actual.columns]
        try:
            results_with_actual[cols_exist].to_csv(val_output_file, index=False)
            print(f"    [OK] Saved {len(results_with_actual):,} validation rows")
        except Exception as e:
            print(f"    [ERROR] Error saving CSV: {e}")

    print("\n" + "="*80)
    print("[SUCCESS] All Batteries Validated")
    print("="*80)


def setup_logging(project_root: Path):
    """
    Configure logging to save output to logs/ folder with timestamped file.

    Logs are saved to: logs/execution_YYYYMMDD_HHMMSS.log
    Output also goes to console.

    Parameters:
    -----------
    project_root : Path
        Root directory of the project
    """
    log_dir = project_root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"execution_{timestamp}.log"

    # Create logger
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)

    # File handler - logs everything
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.DEBUG)

    # Console handler - logs everything (print statements redirected via sys.stdout)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)

    # Formatter
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)

    # Add handlers to logger
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    # Redirect stdout to log file (tee-style output to both console and file)
    class TeeOutput:
        def __init__(self, log_file):
            self.log_file = log_file
            self.stdout = sys.stdout

        def write(self, message):
            self.stdout.write(message)
            with open(self.log_file, 'a') as f:
                f.write(message)

        def flush(self):
            self.stdout.flush()

    sys.stdout = TeeOutput(log_file)

    return log_file


def main():
    """Main entry point - Multi-battery support only."""
    # Setup logging (must be first)
    project_root = Path(__file__).parent.parent
    log_file = setup_logging(project_root)

    print("\n" + "="*80)
    print(f"TTE/TTF Pipeline Started - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Log file: {log_file}")
    print("="*80)

    # Load configuration
    config = load_config()
    project_root = Path(__file__).parent.parent

    # Determine execution mode
    exec_mode = config['execution'].get('mode', 'train_all_batteries')

    print("\n" + "="*80)
    print(f"TTE/TTF Pipeline - Mode: {exec_mode.upper()}")
    print("="*80)

    if exec_mode == 'train_all_batteries':
        run_train_all_batteries(config, project_root)

    elif exec_mode == 'apply_battery':
        run_apply_battery(config, project_root)

    elif exec_mode == 'validate':
        run_validate(config, project_root)

    else:
        raise ValueError(f"Unknown mode: {exec_mode}. Use: train_all_batteries, apply_battery, validate")

    print("\n" + "="*80)
    print("[SUCCESS] Complete")
    print("="*80)


if __name__ == "__main__":
    main()
