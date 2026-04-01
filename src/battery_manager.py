"""
Battery Manager - Handle multiple batteries in data folder
===========================================================

Supports workflows with multiple battery packs:
- Auto-discover all battery files in data folder
- Train on each battery separately
- Save patterns per battery (SQLite database)
- Load correct battery patterns for testing/apply
"""

from pathlib import Path
from typing import Dict, List, Optional, Tuple
import pandas as pd
from db import DatabaseManager


class BatteryManager:
    """Manages multiple battery data and patterns."""

    def __init__(self, data_dir: str = "data", patterns_dir: str = "training_data", db_path: str = "battery_patterns.db"):
        """
        Initialize battery manager.

        Parameters:
        -----------
        data_dir : str
            Directory containing parquet files (one per battery)
        patterns_dir : str
            Directory to store battery patterns (kept for backwards compatibility)
        db_path : str
            Path to SQLite database file
        """
        self.data_dir = Path(data_dir)
        self.patterns_dir = Path(patterns_dir)
        self.patterns_dir.mkdir(parents=True, exist_ok=True)
        self.db = DatabaseManager(db_path)

    def _create_default_decay_stats(self, default_rate: float) -> Tuple[Dict, Dict]:
        """
        Level 4 fallback: Create default decay statistics when no training data available.

        Uses a conservative flat rate across all bins so TTE is still produced (but with low confidence).

        Parameters:
        -----------
        default_rate : float
            Default discharge rate (%SOC/min) from config

        Returns:
        --------
        (discharge_stats, charge_stats) : Both populated with default conservative rates
        """
        # Create default stats for all (soc_window, load_class, current_range) combinations
        default_stats = {}
        soc_windows = range(0, 100, 5)  # 0, 5, 10, ..., 95
        load_classes = ['idle', 'steady', 'cyclic', 'transient']
        current_ranges = ['low', 'medium', 'high', 'very_high']

        for soc_window in soc_windows:
            for load_class in load_classes:
                for current_range in current_ranges:
                    key = (soc_window, load_class, current_range)
                    default_stats[key] = {
                        'rate_mean': default_rate,
                        'rate_std': default_rate * 0.3,  # conservative std dev
                        'rate_median': default_rate,
                        'count': 0  # count=0 signals "default, not learned"
                    }

        # Return same defaults for both discharge and charge (conservative fallback)
        return default_stats, default_stats

    def discover_batteries(self) -> Dict[str, Path]:
        """
        Auto-discover all battery files in data folder.

        Returns:
        --------
        dict : {battery_id: file_path}
            Example: {'SE0100000092': 'data/SE0100000092.parquet', ...}
        """
        batteries = {}

        if not self.data_dir.exists():
            print(f"[ERROR] Data directory not found: {self.data_dir}")
            return batteries

        parquet_files = list(self.data_dir.glob("*.parquet"))

        if not parquet_files:
            print(f"[WARN] No parquet files found in {self.data_dir}")
            return batteries

        for file in sorted(parquet_files):
            # Extract battery ID from filename (e.g., SE0100000092.parquet)
            battery_id = file.stem
            batteries[battery_id] = file

        return batteries

    def get_battery_pattern_path(self, battery_id: str, label: str = "") -> Path:
        """
        Get pattern directory path for a battery.

        Parameters:
        -----------
        battery_id : str
            Battery ID (e.g., SE0100000092)
        label : str
            Optional label (e.g., "september_2025")

        Returns:
        --------
        Path : Pattern directory path
        """
        pattern_name = f"{battery_id}_{label}" if label else battery_id
        return self.patterns_dir / pattern_name

    def save_battery_patterns(self, battery_id: str, calculator_obj, label: str = "") -> Path:
        """
        Save patterns for a specific battery to SQLite database.

        Parameters:
        -----------
        battery_id : str
            Battery ID
        calculator_obj : TTETTFCalculator
            Trained calculator
        label : str
            Optional label (e.g., "september_2025")

        Returns:
        --------
        Path : Pattern directory path (kept for backwards compatibility)
        """
        # Extract decay rate statistics from calculator
        soc_decay = getattr(calculator_obj, 'soc_decay', None)

        if soc_decay is None:
            print(f"    [{battery_id}] [ERROR] No SOC decay analyzer found")
            return self.get_battery_pattern_path(battery_id, label)

        discharge_stats = getattr(soc_decay, 'discharge_stats', {})
        charge_stats = getattr(soc_decay, 'charge_stats', {})

        # Prepare metadata
        metadata = {
            "session_min_duration_minutes": getattr(calculator_obj, 'session_min_duration_minutes', 15.0),
            "session_min_energy_ah": getattr(calculator_obj, 'session_min_energy_ah', 1.0),
            "tte_ttf_smoothing_factor": getattr(calculator_obj, 'tte_ttf_smoothing_factor', 0.15)
        }

        # Save to database
        self.db.save_patterns(battery_id, discharge_stats, charge_stats, label, metadata)
        print(f"    [{battery_id}] Saved to database (label: {label or 'default'})")

        # Keep pattern_dir for backwards compatibility
        pattern_dir = self.get_battery_pattern_path(battery_id, label)
        pattern_dir.mkdir(parents=True, exist_ok=True)

        return pattern_dir

    def load_battery_patterns(self, battery_id: str, calculator_obj,
                            label: str = "", default_discharge_rate: Optional[float] = None) -> bool:
        """
        Load patterns for a specific battery from SQLite database with Level 4 fallback.

        Fallback chain:
        1. Try DB with battery_id + label
        2. [FALLBACK-A] Try DB with battery_id + any label (in db.py)
        3. [FALLBACK-B] Try DB with global fleet model (in db.py)
        4. [FALLBACK-C] Seed with default rates from config

        Parameters:
        -----------
        battery_id : str
            Battery ID
        calculator_obj : TTETTFCalculator
            Calculator instance to load into
        label : str
            Optional label
        default_discharge_rate : float
            Default discharge rate (%SOC/min) for Level 4 fallback

        Returns:
        --------
        bool : True if patterns found (from DB or Level 4 default), False if all fallbacks fail
        """
        try:
            # Levels 1-3: Try database with fallback chain
            discharge_stats, charge_stats, metadata = self.db.load_patterns(battery_id, label)

            if discharge_stats is None or charge_stats is None:
                # Level 4: Seed with default rates
                if default_discharge_rate is not None and default_discharge_rate > 0:
                    print(f"    [FALLBACK-C] [{battery_id}] Using hardcoded default rate ({default_discharge_rate}%/min)")
                    discharge_stats, charge_stats = self._create_default_decay_stats(default_discharge_rate)
                    # Mark as using defaults so confidence will be low
                    if hasattr(calculator_obj, 'soc_decay') and calculator_obj.soc_decay is not None:
                        calculator_obj.soc_decay.discharge_stats = discharge_stats
                        calculator_obj.soc_decay.charge_stats = charge_stats
                        calculator_obj.soc_decay.is_trained = True
                    print(f"    [OK] [{battery_id}] Seeded with default rates (confidence will be low)")
                    return True
                else:
                    print(f"[ERROR] [{battery_id}] Patterns not found in database (label: {label or 'default'})")
                    return False

            # DB lookup succeeded (Levels 1-3)
            # Restore discharge and charge stats to the soc_decay analyzer
            if hasattr(calculator_obj, 'soc_decay') and calculator_obj.soc_decay is not None:
                calculator_obj.soc_decay.discharge_stats = discharge_stats
                calculator_obj.soc_decay.charge_stats = charge_stats
                calculator_obj.soc_decay.is_trained = True

            # Restore metadata if available
            if metadata:
                calculator_obj.session_min_duration_minutes = metadata['session_min_duration_minutes']
                calculator_obj.session_min_energy_ah = metadata['session_min_energy_ah']
                calculator_obj.tte_ttf_smoothing_factor = metadata['tte_ttf_smoothing_factor']

            print(f"    [OK] [{battery_id}] Loaded from database (label: {label or 'default'})")
            return True

        except Exception as e:
            print(f"[ERROR] [{battery_id}] Failed to load patterns: {e}")
            return False

    def list_battery_patterns(self) -> Dict[str, List[str]]:
        """
        List all saved patterns by battery from database.

        Returns:
        --------
        dict : {battery_id: [pattern_labels]}
        """
        return self.db.list_batteries()

    def print_available_batteries(self):
        """Print all discovered batteries and their patterns."""
        print("\n[AVAILABLE BATTERIES]")

        # Discover files
        batteries = self.discover_batteries()
        if not batteries:
            print("  No battery files found in data folder")
            return

        for battery_id, file_path in batteries.items():
            file_size = file_path.stat().st_size / (1024 * 1024)  # MB
            print(f"  [OK] {battery_id}: {file_path.name} ({file_size:.1f} MB)")

        # Show saved patterns from database
        patterns = self.list_battery_patterns()
        if patterns:
            print("\n[SAVED PATTERNS] (in database)")
            for battery_id, pattern_labels in patterns.items():
                if pattern_labels:
                    print(f"  {battery_id}:")
                    for label in pattern_labels:
                        print(f"    - {label if label else '(default)'}")
        else:
            print("\n[SAVED PATTERNS] None found in database")
