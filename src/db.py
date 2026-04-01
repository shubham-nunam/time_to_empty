"""
Simple SQLite wrapper for battery pattern storage.
Replaces pickle file storage with database.
"""

import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime


class DatabaseManager:
    """Manage SQLite database for battery patterns."""

    def __init__(self, db_path: str = "battery_patterns.db"):
        """
        Initialize database connection.

        Parameters:
        -----------
        db_path : str
            Path to SQLite database file
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_tables()

    def _get_connection(self):
        """Get database connection."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_tables(self):
        """Create tables if they don't exist."""
        conn = self._get_connection()
        cursor = conn.cursor()

        # Table for decay rate statistics
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS battery_patterns (
                battery_id TEXT NOT NULL,
                label TEXT NOT NULL,
                phase TEXT NOT NULL,
                soc_window INTEGER NOT NULL,
                load_class TEXT NOT NULL,
                current_range TEXT NOT NULL,
                rate_mean REAL NOT NULL,
                rate_std REAL NOT NULL,
                rate_median REAL NOT NULL,
                count INTEGER NOT NULL,
                PRIMARY KEY (battery_id, label, phase, soc_window, load_class, current_range)
            )
        """)

        # Table for battery metadata
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS battery_metadata (
                battery_id TEXT NOT NULL,
                label TEXT NOT NULL,
                session_min_duration_minutes REAL NOT NULL,
                session_min_energy_ah REAL NOT NULL,
                tte_ttf_smoothing_factor REAL NOT NULL,
                trained_at TIMESTAMP NOT NULL,
                PRIMARY KEY (battery_id, label)
            )
        """)

        conn.commit()
        conn.close()

    def save_patterns(self, battery_id: str, discharge_stats: Dict, charge_stats: Dict,
                      label: str = "", metadata: Optional[Dict] = None) -> None:
        """
        Save decay rate statistics to database.

        Parameters:
        -----------
        battery_id : str
            Battery ID (e.g., SE0100000092)
        discharge_stats : dict
            Discharge statistics: {(soc_window, load_class, current_range): {rate_mean, rate_std, rate_median, count}}
        charge_stats : dict
            Charge statistics: same structure as discharge_stats
        label : str
            Optional pattern label
        metadata : dict
            Metadata: {session_min_duration_minutes, session_min_energy_ah, tte_ttf_smoothing_factor}
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        # Clear existing data for this battery+label
        cursor.execute(
            "DELETE FROM battery_patterns WHERE battery_id = ? AND label = ?",
            (battery_id, label)
        )
        cursor.execute(
            "DELETE FROM battery_metadata WHERE battery_id = ? AND label = ?",
            (battery_id, label)
        )

        # Insert discharge stats
        for (soc_window, load_class, current_range), stats in discharge_stats.items():
            cursor.execute("""
                INSERT INTO battery_patterns
                (battery_id, label, phase, soc_window, load_class, current_range,
                 rate_mean, rate_std, rate_median, count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                battery_id, label, 'discharge',
                int(soc_window), str(load_class), str(current_range),
                float(stats.get('rate_mean', 0)),
                float(stats.get('rate_std', 0)),
                float(stats.get('rate_median', 0)),
                int(stats.get('count', 0))
            ))

        # Insert charge stats
        for (soc_window, load_class, current_range), stats in charge_stats.items():
            cursor.execute("""
                INSERT INTO battery_patterns
                (battery_id, label, phase, soc_window, load_class, current_range,
                 rate_mean, rate_std, rate_median, count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                battery_id, label, 'charge',
                int(soc_window), str(load_class), str(current_range),
                float(stats.get('rate_mean', 0)),
                float(stats.get('rate_std', 0)),
                float(stats.get('rate_median', 0)),
                int(stats.get('count', 0))
            ))

        # Insert metadata
        if metadata:
            cursor.execute("""
                INSERT OR REPLACE INTO battery_metadata
                (battery_id, label, session_min_duration_minutes, session_min_energy_ah,
                 tte_ttf_smoothing_factor, trained_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                battery_id, label,
                float(metadata.get('session_min_duration_minutes', 15.0)),
                float(metadata.get('session_min_energy_ah', 1.0)),
                float(metadata.get('tte_ttf_smoothing_factor', 0.15)),
                datetime.now()
            ))

        conn.commit()
        conn.close()

    def load_patterns(self, battery_id: str, label: str = "") -> tuple[Optional[Dict], Optional[Dict], Optional[Dict]]:
        """
        Load decay rate statistics from database.

        Parameters:
        -----------
        battery_id : str
            Battery ID
        label : str
            Optional pattern label

        Returns:
        --------
        (discharge_stats, charge_stats, metadata) or (None, None, None) if not found
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        # Load pattern data
        cursor.execute("""
            SELECT phase, soc_window, load_class, current_range,
                   rate_mean, rate_std, rate_median, count
            FROM battery_patterns
            WHERE battery_id = ? AND label = ?
            ORDER BY phase, soc_window, load_class, current_range
        """, (battery_id, label))

        rows = cursor.fetchall()
        if not rows:
            conn.close()
            return None, None, None

        discharge_stats = {}
        charge_stats = {}

        for row in rows:
            key = (row['soc_window'], row['load_class'], row['current_range'])
            stats = {
                'rate_mean': row['rate_mean'],
                'rate_std': row['rate_std'],
                'rate_median': row['rate_median'],
                'count': row['count']
            }

            if row['phase'] == 'discharge':
                discharge_stats[key] = stats
            elif row['phase'] == 'charge':
                charge_stats[key] = stats

        # Load metadata
        cursor.execute("""
            SELECT session_min_duration_minutes, session_min_energy_ah, tte_ttf_smoothing_factor
            FROM battery_metadata
            WHERE battery_id = ? AND label = ?
        """, (battery_id, label))

        meta_row = cursor.fetchone()
        metadata = None
        if meta_row:
            metadata = {
                'session_min_duration_minutes': meta_row['session_min_duration_minutes'],
                'session_min_energy_ah': meta_row['session_min_energy_ah'],
                'tte_ttf_smoothing_factor': meta_row['tte_ttf_smoothing_factor']
            }

        conn.close()
        return discharge_stats, charge_stats, metadata

    def battery_exists(self, battery_id: str, label: str = "") -> bool:
        """Check if battery patterns exist in database."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT COUNT(*) as count FROM battery_patterns
            WHERE battery_id = ? AND label = ?
        """, (battery_id, label))

        result = cursor.fetchone()
        conn.close()
        return result['count'] > 0

    def list_batteries(self) -> Dict[str, List[str]]:
        """
        List all batteries and their labels in database.

        Returns:
        --------
        dict : {battery_id: [label1, label2, ...]}
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT DISTINCT battery_id, label FROM battery_patterns
            ORDER BY battery_id, label
        """)

        rows = cursor.fetchall()
        conn.close()

        battery_labels = {}
        for row in rows:
            battery_id = row['battery_id']
            label = row['label']
            if battery_id not in battery_labels:
                battery_labels[battery_id] = []
            battery_labels[battery_id].append(label)

        return battery_labels

    def delete_patterns(self, battery_id: str, label: str = "") -> None:
        """Delete patterns for a specific battery and label."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute(
            "DELETE FROM battery_patterns WHERE battery_id = ? AND label = ?",
            (battery_id, label)
        )
        cursor.execute(
            "DELETE FROM battery_metadata WHERE battery_id = ? AND label = ?",
            (battery_id, label)
        )

        conn.commit()
        conn.close()
