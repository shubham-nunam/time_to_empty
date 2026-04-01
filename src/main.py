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
from pathlib import Path
from typing import Optional, Tuple

import pandas as pd

# Add src and utils to path for imports
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / 'utils'))

from tte_ttf_algorithm import TTETTFCalculator
from pattern_manager import PatternManager
from battery_manager import BatteryManager
from data_splitter import DataSplitter
from metrics_calculator import MetricsCalculator
from comparison_reporter import ComparisonReporter
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
    df['current_a'] = df['pack_current_net'].abs() / 1000.0  # convert mA → A

    print(f"    [STATE] State distribution:")
    print(f"      - Charging: {(df['state'] == 'charging').sum()}")
    print(f"      - Discharging: {(df['state'] == 'discharging').sum()}")
    print(f"      - Rest: {(df['state'] == 'rest').sum()}")
    print(f"      - NaN: {df['state'].isna().sum()}")

    # Rename timestamp column for consistency with algorithm
    if 'ts' not in df.columns and 'timestamp' in df.columns:
        df = df.rename(columns={'timestamp': 'ts'})

    return df


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


def run_train_test_split_REMOVED(config: dict, data_df: pd.DataFrame, project_root: Path) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    TRAIN_TEST_SPLIT mode: Split data by date, train on one period, test on another.

    Parameters:
    -----------
    config : dict
        Configuration
    data_df : pd.DataFrame
        Full preprocessed data
    project_root : Path
        Project root directory

    Returns:
    --------
    (train_results, test_results) : tuple of DataFrames
    """
    print("\n" + "="*80)
    print("MODE: TRAIN_TEST_SPLIT")
    print("="*80)

    # Split data by date
    exec_cfg = config['execution']
    splitter = DataSplitter(data_df)
    train_df, test_df = splitter.split_by_date(
        exec_cfg['train_date_start'],
        exec_cfg['train_date_end'],
        exec_cfg['test_date_start'],
        exec_cfg['test_date_end']
    )

    # Train on first period
    print(f"\n[TRAINING] Learning patterns from {exec_cfg['train_date_start']} to {exec_cfg['train_date_end']}...")
    tte_cfg = config.get('tte_ttf', {})
    calculator = TTETTFCalculator(
        session_min_duration_minutes=tte_cfg.get('session_min_duration_minutes', 15.0),
        session_min_energy_ah=tte_cfg.get('session_min_energy_ah', 1.0),
        tte_ttf_smoothing_factor=tte_cfg.get('tte_ttf_smoothing_factor', 0.15),
        current_thresholds=tte_cfg.get('current_thresholds_a', [0.5, 2.0, 5.0])
    )

    print("    [TRAINING] Learning SOC decay patterns and load profiles from training data...")
    calculator.train(
        train_df,
        soc_col='soc',
        current_col='current_a',
        voltage_col='lv',
        status_col='state',
        timestamp_col='ts'
    )

    # Estimate on both train and test
    train_results = estimate_and_save(
        calculator, train_df, config,
        str(project_root / config['output']['output_dir'] / 'tte_ttf_train_results.csv'),
        "Training"
    )

    test_results = estimate_and_save(
        calculator, test_df, config,
        str(project_root / config['output']['output_dir'] / 'tte_ttf_test_results.csv'),
        "Testing"
    )

    # Save patterns for later use
    if exec_cfg.get('save_patterns', True):
        pattern_mgr = PatternManager(str(project_root / config['output']['output_dir'] / 'patterns'))
        pattern_mgr.save_patterns(calculator, exec_cfg.get('patterns_label', 'train_test_split'))

    # Compare metrics
    train_metrics = MetricsCalculator(train_results).compute_all()
    test_metrics = MetricsCalculator(test_results).compute_all()

    reporter = ComparisonReporter(str(project_root / config['output']['output_dir']))
    comparison = reporter.compare_train_test(train_metrics, test_metrics, "Training", "Testing")
    print(comparison)

    # Save comparison
    reporter.save_comparison_csv(train_results, test_results)

    return train_results, test_results


def run_train_only(config: dict, data_df: pd.DataFrame, project_root: Path) -> pd.DataFrame:
    """
    TRAIN_ONLY mode: Train on all data, save patterns.

    Parameters:
    -----------
    config : dict
        Configuration
    data_df : pd.DataFrame
        Full preprocessed data
    project_root : Path
        Project root directory

    Returns:
    --------
    pd.DataFrame : Results
    """
    print("\n" + "="*80)
    print("MODE: TRAIN_ONLY")
    print("="*80)

    print(f"\n[TRAINING] Learning patterns from all {len(data_df):,} samples...")
    tte_cfg = config.get('tte_ttf', {})
    calculator = TTETTFCalculator(
        session_min_duration_minutes=tte_cfg.get('session_min_duration_minutes', 15.0),
        session_min_energy_ah=tte_cfg.get('session_min_energy_ah', 1.0),
        tte_ttf_smoothing_factor=tte_cfg.get('tte_ttf_smoothing_factor', 0.15),
        current_thresholds=tte_cfg.get('current_thresholds_a', [0.5, 2.0, 5.0])
    )

    print("    [TRAINING] Learning SOC decay patterns and load profiles...")
    calculator.train(
        data_df,
        soc_col='soc',
        current_col='current_a',
        voltage_col='lv',
        status_col='state',
        timestamp_col='ts'
    )

    results_df = estimate_and_save(
        calculator, data_df, config,
        str(project_root / config['output']['output_dir'] / 'tte_ttf_results_full.csv'),
        "Full Dataset"
    )

    # Save patterns
    exec_cfg = config['execution']
    if exec_cfg.get('save_patterns', True):
        pattern_mgr = PatternManager(str(project_root / config['output']['output_dir'] / 'patterns'))
        pattern_mgr.save_patterns(calculator, exec_cfg.get('patterns_label', 'train_only'))

    return results_df


def run_apply(config: dict, data_df: pd.DataFrame, project_root: Path) -> pd.DataFrame:
    """
    APPLY mode: Apply previously trained patterns to new data (no retraining).

    Parameters:
    -----------
    config : dict
        Configuration
    data_df : pd.DataFrame
        New preprocessed data
    project_root : Path
        Project root directory

    Returns:
    --------
    pd.DataFrame : Results
    """
    print("\n" + "="*80)
    print("MODE: APPLY")
    print("="*80)

    exec_cfg = config['execution']

    # Find pattern path
    pattern_path = exec_cfg.get('pattern_path')
    if not pattern_path:
        # Try to find latest pattern with label filter
        pattern_mgr = PatternManager(str(project_root / config['output']['output_dir'] / 'patterns'))
        pattern_path = pattern_mgr.get_latest_pattern(
            exec_cfg.get('pattern_label_filter', '')
        )
        if not pattern_path:
            raise FileNotFoundError("No patterns found. Train first with TRAIN_ONLY mode.")

    print(f"\n[LOADING PATTERNS] From: {pattern_path}")

    # Create calculator and load patterns
    tte_cfg = config.get('tte_ttf', {})
    calculator = TTETTFCalculator(
        session_min_duration_minutes=tte_cfg.get('session_min_duration_minutes', 15.0),
        session_min_energy_ah=tte_cfg.get('session_min_energy_ah', 1.0),
        tte_ttf_smoothing_factor=tte_cfg.get('tte_ttf_smoothing_factor', 0.15),
        current_thresholds=tte_cfg.get('current_thresholds_a', [0.5, 2.0, 5.0])
    )

    pattern_mgr = PatternManager(str(project_root / config['output']['output_dir'] / 'patterns'))
    if not pattern_mgr.load_patterns(pattern_path, calculator):
        raise RuntimeError("Failed to load patterns")

    print(f"\n[APPLYING] Estimating TTE/TTF on {len(data_df):,} new samples...")

    results_df = estimate_and_save(
        calculator, data_df, config,
        str(project_root / config['output']['output_dir'] / 'tte_ttf_results_applied.csv'),
        "Applied"
    )

    return results_df


def run_monthly(config: dict, data_df: pd.DataFrame, project_root: Path) -> pd.DataFrame:
    """
    MONTHLY mode: Filter by month and process.

    Parameters:
    -----------
    config : dict
        Configuration
    data_df : pd.DataFrame
        Full preprocessed data
    project_root : Path
        Project root directory

    Returns:
    --------
    pd.DataFrame : Results
    """
    print("\n" + "="*80)
    print("MODE: MONTHLY")
    print("="*80)

    exec_cfg = config['execution']
    month_filter = exec_cfg.get('month', '2025-09')

    print(f"\n[FILTERING] Filtering to month {month_filter}...")
    data_df['year_month'] = data_df['utc_time'].dt.strftime('%Y-%m')
    rows_before = len(data_df)
    data_df = data_df[data_df['year_month'] == month_filter].copy()
    print(f"    Filtered {rows_before:,} -> {len(data_df):,} rows")
    data_df = data_df.drop('year_month', axis=1)

    tte_cfg = config.get('tte_ttf', {})
    calculator = TTETTFCalculator(
        session_min_duration_minutes=tte_cfg.get('session_min_duration_minutes', 15.0),
        session_min_energy_ah=tte_cfg.get('session_min_energy_ah', 1.0),
        tte_ttf_smoothing_factor=tte_cfg.get('tte_ttf_smoothing_factor', 0.15),
        current_thresholds=tte_cfg.get('current_thresholds_a', [0.5, 2.0, 5.0])
    )

    print("    [TRAINING] Learning SOC decay patterns and load profiles from data...")
    calculator.train(
        data_df,
        soc_col='soc',
        current_col='current_a',
        voltage_col='lv',
        status_col='state',
        timestamp_col='ts'
    )

    results_df = estimate_and_save(
        calculator, data_df, config,
        str(project_root / config['output']['output_dir'] / f'tte_ttf_results_{month_filter}.csv'),
        f"Month {month_filter}"
    )

    return results_df


def run_full(config: dict, data_df: pd.DataFrame, project_root: Path) -> pd.DataFrame:
    """
    FULL mode: Process entire dataset.

    Parameters:
    -----------
    config : dict
        Configuration
    data_df : pd.DataFrame
        Full preprocessed data
    project_root : Path
        Project root directory

    Returns:
    --------
    pd.DataFrame : Results
    """
    print("\n" + "="*80)
    print("MODE: FULL")
    print("="*80)

    tte_cfg = config.get('tte_ttf', {})
    calculator = TTETTFCalculator(
        session_min_duration_minutes=tte_cfg.get('session_min_duration_minutes', 15.0),
        session_min_energy_ah=tte_cfg.get('session_min_energy_ah', 1.0),
        tte_ttf_smoothing_factor=tte_cfg.get('tte_ttf_smoothing_factor', 0.15),
        current_thresholds=tte_cfg.get('current_thresholds_a', [0.5, 2.0, 5.0])
    )

    print("    [TRAINING] Learning SOC decay patterns and load profiles from all data...")
    calculator.train(
        data_df,
        soc_col='soc',
        current_col='current_a',
        voltage_col='lv',
        status_col='state',
        timestamp_col='ts'
    )

    results_df = estimate_and_save(
        calculator, data_df, config,
        str(project_root / config['output']['output_dir'] / 'tte_ttf_results_full.csv'),
        "Full Dataset"
    )

    return results_df


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
            timestamp_col='ts'
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
            tte_ttf_smoothing_factor=tte_cfg.get('tte_ttf_smoothing_factor', 0.15)
        )

        if not battery_mgr.load_battery_patterns(battery_id, calculator, patterns_label):
            print(f"    [WARN] Patterns not found for {battery_id} (skipping)")
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


def main():
    """Main entry point - Multi-battery support only."""
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

    else:
        raise ValueError(f"Unknown mode: {exec_mode}. Use: train_all_batteries, apply_battery")

    print("\n" + "="*80)
    print("[SUCCESS] Complete")
    print("="*80)


if __name__ == "__main__":
    main()
