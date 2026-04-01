"""
Data Splitter - Handle train-test data splits
==============================================

Enables reproducible train-test splits:
- By date range (e.g., Sept 1-25 for training, Sept 26-30 for testing)
- By percentage split (e.g., 80-20)
- With optional stratification by state
"""

import pandas as pd
from pathlib import Path
from typing import Tuple, Optional


class DataSplitter:
    """Manages data train-test splits."""

    def __init__(self, data_df: pd.DataFrame):
        """
        Initialize splitter with data.

        Parameters:
        -----------
        data_df : pd.DataFrame
            Full dataset with 'utc_time' or 'ts' column for date-based splits
        """
        self.data_df = data_df.copy()
        self._ensure_datetime()

    def _ensure_datetime(self):
        """Ensure data has proper datetime column."""
        if 'utc_time' not in self.data_df.columns:
            if 'ts' in self.data_df.columns:
                self.data_df['utc_time'] = pd.to_datetime(
                    self.data_df['ts'], unit='ms', utc=True
                )
            else:
                raise ValueError("Data must have 'utc_time' or 'ts' column")

    def split_by_date(self, train_start: str, train_end: str,
                      test_start: str, test_end: str) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        Split data by date ranges.

        Parameters:
        -----------
        train_start : str
            Start date (e.g., "2025-09-01")
        train_end : str
            End date (e.g., "2025-09-25")
        test_start : str
            Test start (e.g., "2025-09-26")
        test_end : str
            Test end (e.g., "2025-09-30")

        Returns:
        --------
        (train_df, test_df) : tuple of DataFrames
        """
        # Convert date strings to datetime
        train_start = pd.to_datetime(train_start, utc=True)
        train_end = pd.to_datetime(train_end, utc=True)
        test_start = pd.to_datetime(test_start, utc=True)
        test_end = pd.to_datetime(test_end, utc=True)

        # Filter data
        train_df = self.data_df[
            (self.data_df['utc_time'] >= train_start) &
            (self.data_df['utc_time'] <= train_end)
        ].copy()

        test_df = self.data_df[
            (self.data_df['utc_time'] >= test_start) &
            (self.data_df['utc_time'] <= test_end)
        ].copy()

        print(f"[SPLIT BY DATE]")
        print(f"  Training: {train_start.date()} to {train_end.date()} = {len(train_df):,} rows")
        print(f"  Testing:  {test_start.date()} to {test_end.date()} = {len(test_df):,} rows")

        return train_df, test_df

    def split_by_month(self, data_df: pd.DataFrame, train_month: str,
                       test_month: str) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        Split data by month.

        Parameters:
        -----------
        train_month : str
            Training month (e.g., "2025-09")
        test_month : str
            Testing month (e.g., "2025-10")

        Returns:
        --------
        (train_df, test_df) : tuple of DataFrames
        """
        train_df = data_df[
            data_df['utc_time'].dt.strftime('%Y-%m') == train_month
        ].copy()

        test_df = data_df[
            data_df['utc_time'].dt.strftime('%Y-%m') == test_month
        ].copy()

        print(f"[SPLIT BY MONTH]")
        print(f"  Training: {train_month} = {len(train_df):,} rows")
        print(f"  Testing:  {test_month} = {len(test_df):,} rows")

        return train_df, test_df

    def split_by_percentage(self, train_fraction: float = 0.8) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        Split data by percentage (chronological).

        Parameters:
        -----------
        train_fraction : float
            Fraction for training (e.g., 0.8 = 80% train, 20% test)

        Returns:
        --------
        (train_df, test_df) : tuple of DataFrames
        """
        self.data_df = self.data_df.sort_values('utc_time').reset_index(drop=True)
        split_idx = int(len(self.data_df) * train_fraction)

        train_df = self.data_df.iloc[:split_idx].copy()
        test_df = self.data_df.iloc[split_idx:].copy()

        print(f"[SPLIT BY PERCENTAGE]")
        print(f"  Training: {len(train_df):,} rows ({train_fraction*100:.0f}%)")
        print(f"  Testing:  {len(test_df):,} rows ({(1-train_fraction)*100:.0f}%)")

        return train_df, test_df

    def get_date_range(self) -> Tuple[str, str]:
        """Get min-max dates in dataset."""
        min_date = self.data_df['utc_time'].min()
        max_date = self.data_df['utc_time'].max()
        return str(min_date.date()), str(max_date.date())
