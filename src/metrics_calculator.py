"""
Metrics Calculator - Compute TTE/TTF quality metrics
====================================================

Evaluates algorithm performance:
- Coverage: % of samples with valid TTE/TTF estimates
- Stability: Std dev and rate of change in TTE/TTF values
- Accuracy: Correlation with actual discharge times (if available)
"""

import pandas as pd
import numpy as np
from typing import Dict, Any


class MetricsCalculator:
    """Computes TTE/TTF quality metrics."""

    def __init__(self, results_df: pd.DataFrame):
        """
        Initialize with results.

        Parameters:
        -----------
        results_df : pd.DataFrame
            DataFrame with TTE/TTF results from algorithm
        """
        self.results_df = results_df
        self.metrics = {}

    def compute_all(self) -> Dict[str, Any]:
        """Compute all standard metrics."""
        self.metrics = {
            'coverage': self._compute_coverage(),
            'stability': self._compute_stability(),
            'temporal_drift': self._compute_temporal_drift(),
            'confidence': self._compute_confidence_stats()
        }
        return self.metrics

    def _compute_coverage(self) -> Dict[str, Any]:
        """
        Compute TTE/TTF coverage (% with valid values).

        Returns:
        --------
        dict with coverage stats
        """
        total = len(self.results_df)

        tte_valid = self.results_df['tte_hours'].notna().sum() if 'tte_hours' in self.results_df else 0
        ttf_valid = self.results_df['ttf_hours'].notna().sum() if 'ttf_hours' in self.results_df else 0

        # By status
        discharge = (self.results_df['status'] == 'discharging').sum()
        charging = (self.results_df['status'] == 'charging').sum()
        rest = (self.results_df['status'] == 'rest').sum()

        tte_discharge = (
            ((self.results_df['status'] == 'discharging') & (self.results_df['tte_hours'].notna())).sum()
            if 'tte_hours' in self.results_df else 0
        )
        ttf_charging = (
            ((self.results_df['status'] == 'charging') & (self.results_df['ttf_hours'].notna())).sum()
            if 'ttf_hours' in self.results_df else 0
        )

        return {
            'total_samples': total,
            'tte_valid_count': tte_valid,
            'tte_valid_pct': (tte_valid / total * 100) if total > 0 else 0,
            'ttf_valid_count': ttf_valid,
            'ttf_valid_pct': (ttf_valid / total * 100) if total > 0 else 0,
            'discharge_samples': discharge,
            'charging_samples': charging,
            'rest_samples': rest,
            'tte_during_discharge': tte_discharge,
            'ttf_during_charging': ttf_charging,
        }

    def _compute_stability(self) -> Dict[str, Any]:
        """
        Compute TTE/TTF stability (std dev, rate of change).

        Returns:
        --------
        dict with stability metrics
        """
        tte_col = 'tte_hours' if 'tte_hours' in self.results_df else None
        ttf_col = 'ttf_hours' if 'ttf_hours' in self.results_df else None

        tte_stats = {}
        if tte_col:
            tte_valid = self.results_df[tte_col].dropna()
            if len(tte_valid) > 0:
                tte_stats = {
                    'mean': tte_valid.mean(),
                    'std': tte_valid.std(),
                    'min': tte_valid.min(),
                    'max': tte_valid.max(),
                    'median': tte_valid.median(),
                }

                # Rate of change (per sample)
                tte_diff = tte_valid.diff().dropna()
                if len(tte_diff) > 0:
                    tte_stats['mean_change_per_sample'] = tte_diff.mean()
                    tte_stats['std_change_per_sample'] = tte_diff.std()
                    tte_stats['max_change_per_sample'] = tte_diff.abs().max()
                    tte_stats['samples_with_change'] = (tte_diff != 0).sum()

        ttf_stats = {}
        if ttf_col:
            ttf_valid = self.results_df[ttf_col].dropna()
            if len(ttf_valid) > 0:
                ttf_stats = {
                    'mean': ttf_valid.mean(),
                    'std': ttf_valid.std(),
                    'min': ttf_valid.min(),
                    'max': ttf_valid.max(),
                    'median': ttf_valid.median(),
                }

                # Rate of change
                ttf_diff = ttf_valid.diff().dropna()
                if len(ttf_diff) > 0:
                    ttf_stats['mean_change_per_sample'] = ttf_diff.mean()
                    ttf_stats['std_change_per_sample'] = ttf_diff.std()
                    ttf_stats['max_change_per_sample'] = ttf_diff.abs().max()
                    ttf_stats['samples_with_change'] = (ttf_diff != 0).sum()

        return {
            'tte': tte_stats,
            'ttf': ttf_stats
        }

    def _compute_temporal_drift(self) -> Dict[str, Any]:
        """
        Compute how TTE/TTF values drift over time.

        Returns:
        --------
        dict with temporal drift metrics
        """
        tte_col = 'tte_hours' if 'tte_hours' in self.results_df else None
        ttf_col = 'ttf_hours' if 'ttf_hours' in self.results_df else None

        # Divide into temporal bins (quartiles)
        n = len(self.results_df)
        q = n // 4

        drift_stats = {}

        if tte_col:
            tte_valid = self.results_df[tte_col].dropna()
            if len(tte_valid) > 10:
                tte_q1 = tte_valid.iloc[:len(tte_valid)//2].mean()
                tte_q2 = tte_valid.iloc[len(tte_valid)//2:].mean()
                drift_stats['tte_first_half_mean'] = tte_q1
                drift_stats['tte_second_half_mean'] = tte_q2
                drift_stats['tte_drift_hours'] = tte_q2 - tte_q1

        if ttf_col:
            ttf_valid = self.results_df[ttf_col].dropna()
            if len(ttf_valid) > 10:
                ttf_q1 = ttf_valid.iloc[:len(ttf_valid)//2].mean()
                ttf_q2 = ttf_valid.iloc[len(ttf_valid)//2:].mean()
                drift_stats['ttf_first_half_mean'] = ttf_q1
                drift_stats['ttf_second_half_mean'] = ttf_q2
                drift_stats['ttf_drift_hours'] = ttf_q2 - ttf_q1

        return drift_stats

    def _compute_confidence_stats(self) -> Dict[str, Any]:
        """Compute confidence level distribution."""
        if 'confidence' not in self.results_df:
            return {}

        return {
            'low': (self.results_df['confidence'] == 'low').sum(),
            'medium': (self.results_df['confidence'] == 'medium').sum(),
            'high': (self.results_df['confidence'] == 'high').sum(),
        }

    def print_summary(self):
        """Print readable summary of metrics."""
        if not self.metrics:
            self.compute_all()

        cov = self.metrics['coverage']
        stab = self.metrics['stability']
        drift = self.metrics['temporal_drift']
        conf = self.metrics['confidence']

        print("\n" + "="*70)
        print("METRICS SUMMARY")
        print("="*70)

        print(f"\n[COVERAGE]")
        print(f"  Total samples:       {cov['total_samples']:,}")
        print(f"  TTE valid:           {cov['tte_valid_count']:,} ({cov['tte_valid_pct']:.1f}%)")
        print(f"  TTF valid:           {cov['ttf_valid_count']:,} ({cov['ttf_valid_pct']:.1f}%)")
        print(f"  Status distribution: {cov['discharge_samples']:,} discharge, "
              f"{cov['charging_samples']:,} charge, {cov['rest_samples']:,} rest")

        if stab.get('tte'):
            print(f"\n[TTE STABILITY]")
            tte = stab['tte']
            print(f"  Mean:               {tte['mean']:.2f} hours")
            print(f"  Std:                {tte['std']:.2f} hours")
            print(f"  Range:              {tte['min']:.2f} - {tte['max']:.2f} hours")
            if 'mean_change_per_sample' in tte:
                print(f"  Mean change/sample: {tte['mean_change_per_sample']:.4f} hours")
                print(f"  Std change/sample:  {tte['std_change_per_sample']:.4f} hours")
                print(f"  Samples with change: {tte['samples_with_change']:,}")

        if drift:
            print(f"\n[TEMPORAL DRIFT]")
            if 'tte_drift_hours' in drift:
                print(f"  TTE first half:  {drift['tte_first_half_mean']:.2f} hours")
                print(f"  TTE second half: {drift['tte_second_half_mean']:.2f} hours")
                print(f"  TTE drift:       {drift['tte_drift_hours']:+.2f} hours")

        if conf:
            print(f"\n[CONFIDENCE DISTRIBUTION]")
            total = sum(conf.values())
            if total > 0:
                print(f"  Low:    {conf.get('low', 0):,} ({conf.get('low', 0)/total*100:.1f}%)")
                print(f"  Medium: {conf.get('medium', 0):,} ({conf.get('medium', 0)/total*100:.1f}%)")
                print(f"  High:   {conf.get('high', 0):,} ({conf.get('high', 0)/total*100:.1f}%)")

        print("\n" + "="*70)
