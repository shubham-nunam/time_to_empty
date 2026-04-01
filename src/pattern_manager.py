"""
Pattern Manager - Save and load trained TTE/TTF patterns
=========================================================

Enables train-once, apply-everywhere workflow:
- Save trained decay rates, load classifications, and stats to disk
- Load patterns for batch processing without retraining
- Supports version tracking and metadata
"""

import json
import pickle
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional


class PatternManager:
    """Manages persistence of trained TTE/TTF patterns."""

    def __init__(self, patterns_dir: str = "outputs/patterns"):
        """
        Initialize pattern manager.

        Parameters:
        -----------
        patterns_dir : str
            Directory to store/load patterns (e.g., "outputs/patterns/sept_2025")
        """
        self.patterns_dir = Path(patterns_dir)
        self.patterns_dir.mkdir(parents=True, exist_ok=True)

    def save_patterns(self, calculator_obj: Any, label: str = "") -> Dict[str, Any]:
        """
        Extract and save trained patterns from calculator.

        Parameters:
        -----------
        calculator_obj : TTETTFCalculator
            Trained calculator instance
        label : str
            Optional label for this pattern set (e.g., "sept_1_25_training")

        Returns:
        --------
        dict with saved file paths
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        pattern_name = f"{label}_{timestamp}" if label else timestamp
        pattern_subdir = self.patterns_dir / pattern_name
        pattern_subdir.mkdir(parents=True, exist_ok=True)

        saved_files = {}

        # Save SOC decay analyzer state
        if hasattr(calculator_obj, '_soc_decay_analyzer'):
            analyzer_file = pattern_subdir / "soc_decay_analyzer.pkl"
            with open(analyzer_file, 'wb') as f:
                pickle.dump(calculator_obj._soc_decay_analyzer, f)
            saved_files['soc_decay_analyzer'] = str(analyzer_file)
            print(f"    Saved SOC decay analyzer: {analyzer_file.name}")

        # Save load classifier state
        if hasattr(calculator_obj, '_load_classifier'):
            classifier_file = pattern_subdir / "load_classifier.pkl"
            with open(classifier_file, 'wb') as f:
                pickle.dump(calculator_obj._load_classifier, f)
            saved_files['load_classifier'] = str(classifier_file)
            print(f"    Saved load classifier: {classifier_file.name}")

        # Save metadata
        metadata = {
            "label": label,
            "timestamp": timestamp,
            "saved_at": datetime.now().isoformat(),
            "files": saved_files,
            "calculator_params": {
                "session_min_duration_minutes": getattr(calculator_obj, 'session_min_duration_minutes', 15.0),
                "session_min_energy_ah": getattr(calculator_obj, 'session_min_energy_ah', 1.0),
                "tte_ttf_smoothing_factor": getattr(calculator_obj, 'tte_ttf_smoothing_factor', 0.15)
            }
        }

        metadata_file = pattern_subdir / "metadata.json"
        with open(metadata_file, 'w') as f:
            json.dump(metadata, f, indent=2)
        saved_files['metadata'] = str(metadata_file)
        print(f"    Saved metadata: {metadata_file.name}")

        print(f"\n[PATTERNS SAVED] {pattern_subdir}")
        return saved_files

    def load_patterns(self, pattern_path: str, calculator_obj: Any) -> bool:
        """
        Load saved patterns into calculator.

        Parameters:
        -----------
        pattern_path : str
            Path to pattern directory (e.g., "outputs/patterns/sept_2025_20260331_120000")
        calculator_obj : TTETTFCalculator
            Calculator instance to load patterns into

        Returns:
        --------
        bool : True if successful, False otherwise
        """
        pattern_dir = Path(pattern_path)

        if not pattern_dir.exists():
            print(f"ERROR: Pattern directory not found: {pattern_dir}")
            return False

        # Load metadata
        metadata_file = pattern_dir / "metadata.json"
        if metadata_file.exists():
            with open(metadata_file, 'r') as f:
                metadata = json.load(f)
            print(f"[PATTERNS LOADING] Label: {metadata.get('label', 'unknown')}")
            print(f"                   Saved: {metadata.get('saved_at')}")

        # Load SOC decay analyzer
        analyzer_file = pattern_dir / "soc_decay_analyzer.pkl"
        if analyzer_file.exists():
            with open(analyzer_file, 'rb') as f:
                calculator_obj._soc_decay_analyzer = pickle.load(f)
            print(f"    Loaded SOC decay analyzer")

        # Load load classifier
        classifier_file = pattern_dir / "load_classifier.pkl"
        if classifier_file.exists():
            with open(classifier_file, 'rb') as f:
                calculator_obj._load_classifier = pickle.load(f)
            print(f"    Loaded load classifier")

        return True

    def list_patterns(self) -> list:
        """List all available pattern sets."""
        if not self.patterns_dir.exists():
            return []

        patterns = []
        for item in sorted(self.patterns_dir.iterdir()):
            if item.is_dir():
                metadata_file = item / "metadata.json"
                if metadata_file.exists():
                    with open(metadata_file, 'r') as f:
                        metadata = json.load(f)
                    patterns.append({
                        "path": str(item),
                        "label": metadata.get('label'),
                        "saved_at": metadata.get('saved_at')
                    })

        return patterns

    def get_latest_pattern(self, label_filter: str = "") -> Optional[str]:
        """
        Get path to most recently saved pattern.

        Parameters:
        -----------
        label_filter : str
            Optional label filter (e.g., "september")

        Returns:
        --------
        str : Path to latest pattern, or None if none found
        """
        patterns = self.list_patterns()
        if label_filter:
            patterns = [p for p in patterns if label_filter.lower() in p['label'].lower()]

        if not patterns:
            return None

        # Sort by saved_at timestamp, get most recent
        latest = max(patterns, key=lambda p: p['saved_at'])
        return latest['path']
