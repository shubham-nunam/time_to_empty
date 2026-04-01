"""
Comparison Reporter - Generate side-by-side metric comparisons
==============================================================

Compares algorithm performance across:
- Training vs testing datasets
- Different time periods
- Multiple pattern versions
"""

import pandas as pd
from typing import Dict, Any, Optional
from pathlib import Path


class ComparisonReporter:
    """Generates comparison reports between datasets."""

    def __init__(self, output_dir: str = "outputs"):
        """
        Initialize reporter.

        Parameters:
        -----------
        output_dir : str
            Directory for saving reports
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def compare_train_test(self, train_metrics: Dict[str, Any],
                          test_metrics: Dict[str, Any],
                          train_label: str = "Training",
                          test_label: str = "Testing") -> str:
        """
        Generate train vs test comparison report.

        Parameters:
        -----------
        train_metrics : dict
            Metrics from training dataset
        test_metrics : dict
            Metrics from testing dataset
        train_label : str
            Label for training dataset
        test_label : str
            Label for testing dataset

        Returns:
        --------
        str : Report text
        """
        report = []
        report.append("\n" + "="*80)
        report.append("TRAIN vs TEST COMPARISON REPORT")
        report.append("="*80)

        # Coverage comparison
        report.append(f"\n[COVERAGE]")
        report.append(f"{'Metric':<30} {train_label:<20} {test_label:<20}")
        report.append("-"*70)

        train_cov = train_metrics.get('coverage', {})
        test_cov = test_metrics.get('coverage', {})

        report.append(f"{'Total samples':<30} {train_cov.get('total_samples', 0):>18,}  "
                     f"{test_cov.get('total_samples', 0):>18,}")
        report.append(f"{'TTE coverage':<30} {train_cov.get('tte_valid_pct', 0):>17.1f}%  "
                     f"{test_cov.get('tte_valid_pct', 0):>17.1f}%")
        report.append(f"{'TTF coverage':<30} {train_cov.get('ttf_valid_pct', 0):>17.1f}%  "
                     f"{test_cov.get('ttf_valid_pct', 0):>17.1f}%")

        # Stability comparison
        report.append(f"\n[STABILITY - TTE]")
        report.append(f"{'Metric':<30} {train_label:<20} {test_label:<20}")
        report.append("-"*70)

        train_tte = train_metrics.get('stability', {}).get('tte', {})
        test_tte = test_metrics.get('stability', {}).get('tte', {})

        report.append(f"{'Mean TTE (hours)':<30} {train_tte.get('mean', 0):>19.2f}  "
                     f"{test_tte.get('mean', 0):>19.2f}")
        report.append(f"{'Std TTE (hours)':<30} {train_tte.get('std', 0):>19.2f}  "
                     f"{test_tte.get('std', 0):>19.2f}")
        report.append(f"{'TTE range (hours)':<30} "
                     f"{train_tte.get('min', 0):.2f}–{train_tte.get('max', 0):.2f}     "
                     f"{test_tte.get('min', 0):.2f}–{test_tte.get('max', 0):.2f}")

        if 'mean_change_per_sample' in train_tte:
            report.append(f"{'Mean change/sample':<30} {train_tte['mean_change_per_sample']:>18.6f}  "
                         f"{test_tte.get('mean_change_per_sample', 0):>18.6f}")
            report.append(f"{'Std change/sample':<30} {train_tte['std_change_per_sample']:>18.6f}  "
                         f"{test_tte.get('std_change_per_sample', 0):>18.6f}")

        # Temporal drift
        train_drift = train_metrics.get('temporal_drift', {})
        test_drift = test_metrics.get('temporal_drift', {})

        if train_drift or test_drift:
            report.append(f"\n[TEMPORAL DRIFT]")
            report.append(f"{'Metric':<30} {train_label:<20} {test_label:<20}")
            report.append("-"*70)

            if 'tte_drift_hours' in train_drift:
                report.append(f"{'TTE drift (hours)':<30} {train_drift['tte_drift_hours']:+19.2f}  "
                             f"{test_drift.get('tte_drift_hours', 0):+19.2f}")

        # Confidence
        train_conf = train_metrics.get('confidence', {})
        test_conf = test_metrics.get('confidence', {})

        if train_conf or test_conf:
            report.append(f"\n[CONFIDENCE DISTRIBUTION]")
            report.append(f"{'Level':<30} {train_label:<20} {test_label:<20}")
            report.append("-"*70)

            report.append(f"{'High confidence':<30} {train_conf.get('high', 0):>18,}  "
                         f"{test_conf.get('high', 0):>18,}")
            report.append(f"{'Medium confidence':<30} {train_conf.get('medium', 0):>18,}  "
                         f"{test_conf.get('medium', 0):>18,}")
            report.append(f"{'Low confidence':<30} {train_conf.get('low', 0):>18,}  "
                         f"{test_conf.get('low', 0):>18,}")

        report.append("\n" + "="*80)

        return "\n".join(report)

    def save_comparison_csv(self, train_results: pd.DataFrame,
                           test_results: pd.DataFrame,
                           output_file: str = "train_test_comparison.csv"):
        """
        Save detailed comparison CSV (side-by-side stats).

        Parameters:
        -----------
        train_results : pd.DataFrame
            Training results
        test_results : pd.DataFrame
            Testing results
        output_file : str
            Output CSV filename
        """
        # Extract TTE statistics
        stats_rows = []

        # Training stats
        tte_train = train_results['tte_hours'].dropna()
        stats_rows.append({
            'Dataset': 'Training',
            'Total_Samples': len(train_results),
            'TTE_Valid': len(tte_train),
            'TTE_Valid_Pct': len(tte_train) / len(train_results) * 100,
            'TTE_Mean': tte_train.mean(),
            'TTE_Std': tte_train.std(),
            'TTE_Min': tte_train.min(),
            'TTE_Max': tte_train.max(),
            'TTE_Median': tte_train.median(),
        })

        # Testing stats
        tte_test = test_results['tte_hours'].dropna()
        stats_rows.append({
            'Dataset': 'Testing',
            'Total_Samples': len(test_results),
            'TTE_Valid': len(tte_test),
            'TTE_Valid_Pct': len(tte_test) / len(test_results) * 100,
            'TTE_Mean': tte_test.mean(),
            'TTE_Std': tte_test.std(),
            'TTE_Min': tte_test.min(),
            'TTE_Max': tte_test.max(),
            'TTE_Median': tte_test.median(),
        })

        stats_df = pd.DataFrame(stats_rows)
        output_path = self.output_dir / output_file
        stats_df.to_csv(output_path, index=False)
        print(f"\n[SAVED] Comparison CSV: {output_path}")

        return stats_df
