"""
Data Adapter Layer - Normalize JSON and Parquet to unified format
==================================================================

Converts MongoDB Extended JSON format to match Parquet data structure.
Handles type unwrapping, column naming, and timestamp normalization.

Minimal adapter layer that doesn't change existing algorithm logic.
"""

from typing import Any, Dict, List, Union
import json
from pathlib import Path
import pandas as pd


def unwrap_mongo_extended_json(value: Any) -> Any:
    """
    Unwrap MongoDB Extended JSON scalar types.

    Examples:
        {"$numberLong": "123"} → 123
        {"$numberDouble": "1.5"} → 1.5
        {"$date": "2026-03-30T08:11:46.591Z"} → milliseconds (int)
        {"$oid": "507f1f77bcf86cd799439011"} → "507f1f77bcf86cd799439011"

    Plain values are returned unchanged.
    """
    if not isinstance(value, dict):
        return value

    # MongoDB Extended JSON numeric types
    if "$numberLong" in value:
        return int(value["$numberLong"])
    if "$numberInt" in value:
        return int(value["$numberInt"])
    if "$numberDouble" in value:
        return float(value["$numberDouble"])

    # ObjectId
    if "$oid" in value:
        return str(value["$oid"])

    # Timestamp (ISO string or nested $numberLong)
    if "$date" in value:
        date_val = value["$date"]
        if isinstance(date_val, dict) and "$numberLong" in date_val:
            return int(date_val["$numberLong"])
        # If it's an ISO string, leave as-is (will be converted to ms later)
        return date_val

    return value


def parse_mongo_json_records(raw_data: Union[list, dict]) -> List[Dict[str, Any]]:
    """
    Parse MongoDB Extended JSON array/object into Python dictionaries.

    Unwraps all MongoDB Extended JSON types ($numberLong, $date, $oid, etc).
    Returns list of flat dictionaries ready for DataFrame.
    """
    if isinstance(raw_data, dict):
        raw_data = [raw_data]

    records = []
    for item in raw_data:
        if not isinstance(item, dict):
            continue

        # Unwrap all values in this record
        unwrapped = {
            key: unwrap_mongo_extended_json(val)
            for key, val in item.items()
        }
        records.append(unwrapped)

    return records


def normalize_timestamp_column(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normalize timestamp representation across data sources.

    Priority:
    1. 'timestamp' column (Parquet default) - already in ms
    2. 'ts' column (JSON alt name) - already in ms
    3. 'CreatedAt' column (MongoDB) - ISO string, convert to ms

    Result: 'timestamp' column in milliseconds (int64)
    """
    df = df.copy()

    # Case 1: Use existing 'timestamp' if available (Parquet)
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_numeric(df["timestamp"], errors="coerce").astype("int64")
        return df

    # Case 2: Rename 'ts' to 'timestamp' if present (JSON alternative)
    if "ts" in df.columns:
        df = df.rename(columns={"ts": "timestamp"})
        df["timestamp"] = pd.to_numeric(df["timestamp"], errors="coerce").astype("int64")
        return df

    # Case 3: Convert 'CreatedAt' ISO string to milliseconds
    if "CreatedAt" in df.columns:
        # Parse ISO format and convert to milliseconds since epoch
        ts_ms = (
            pd.to_datetime(df["CreatedAt"], utc=True, errors="coerce")
            .astype("int64") // 1_000_000
        ).astype("int64")
        df["timestamp"] = ts_ms
        df = df.drop(columns=["CreatedAt"])
        return df

    # No timestamp column found - raise error
    raise ValueError(
        "No timestamp column found. Expected: 'timestamp', 'ts', or 'CreatedAt'"
    )


def normalize_battery_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Align column naming quirks between Parquet and JSON sources.

    Renames:
        PackCapacity → FullCap (canonical name)

    Converts numeric string columns to appropriate types.
    """
    df = df.copy()

    # Column name normalization
    if "FullCap" not in df.columns and "PackCapacity" in df.columns:
        df = df.rename(columns={"PackCapacity": "FullCap"})

    # Ensure numeric columns are properly typed (not object strings)
    # Common numeric columns in battery data
    numeric_cols = [
        "Tamb", "SoC", "Ip", "BmsErr", "SoH", "Battstate", "BmsID", "TMax",
        "Vp", "BalStat", "CyCnt", "HwErr", "V1", "V2", "V3", "V4", "BT1",
        "V5", "V6", "BT3", "V7", "BT2", "V8", "V9", "BT4", "IpMax",
        "TemperatureProbes", "FullCap", "BattWarning", "PwrT", "IpMin",
        "MOSstate", "V10", "V12", "V11", "V14", "TMin", "V13", "V16", "V15",
        "CellNumber", "PackCapacity"
    ]

    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


def load_json_battery_data(json_path: Union[str, Path]) -> pd.DataFrame:
    """
    Load battery data from MongoDB Extended JSON file.

    Steps:
    1. Load JSON file
    2. Parse MongoDB Extended JSON records
    3. Convert to DataFrame
    4. Normalize timestamps to milliseconds
    5. Normalize column names and types

    Returns DataFrame matching Parquet format.
    """
    json_path = Path(json_path)

    if not json_path.exists():
        raise FileNotFoundError(f"JSON file not found: {json_path}")

    # Load JSON
    with open(json_path, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    # Parse and unwrap MongoDB Extended JSON
    records = parse_mongo_json_records(raw_data)

    if not records:
        raise ValueError(f"No valid records found in {json_path}")

    # Convert to DataFrame
    df = pd.DataFrame(records)

    # Drop MongoDB internal _id column (optional, kept if user needs it)
    if "_id" in df.columns:
        df = df.drop(columns=["_id"])

    # Normalize timestamps
    df = normalize_timestamp_column(df)

    # Normalize column names and types
    df = normalize_battery_columns(df)

    return df
