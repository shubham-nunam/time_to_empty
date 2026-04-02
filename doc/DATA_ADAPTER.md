# Data Adapter Layer

## Overview

The data adapter layer provides a unified interface for loading battery data from multiple sources:
- **Parquet files** (training data) - direct numerical storage
- **JSON files** (testing data) - MongoDB Extended JSON format

The adapter ensures both formats produce identical DataFrames before processing, enabling seamless switching between training and testing workflows.

## Architecture

### Location
- **Adapter module:** `src/data_adapter.py`
- **Integration point:** `src/battery_manager.py` → `load_battery_table()`

### Design Principle

**Minimal invasion:** The adapter is a new layer that doesn't modify existing algorithm logic. It sits between raw data loading and normalization:

```
Raw File (.parquet or .json)
         ↓
   load_battery_table()
         ↓
  [Parquet: direct read] [JSON: adapter layer]
         ↓
normalize_ness_battery_columns()
         ↓
Unified DataFrame (same columns, types)
```

## Data Format Differences

### Parquet Format
- **Source:** Training data in `data/training_data/*.parquet`
- **Schema:** Battery telemetry columns (SoC, Ip, Vp, timestamps, etc.)
- **Timestamp:** `timestamp` column as int64 (milliseconds since epoch)
- **Types:** Raw numeric columns as object (string) initially, converted to numeric during normalization
- **Row count:** Full dataset (e.g., 539,150 rows for LSE18B260667)

### JSON Format (MongoDB Extended JSON)
- **Source:** Testing data in `data/testing_data/*.json`
- **Format:** MongoDB Extended JSON (wrapped types: `$numberLong`, `$numberInt`, `$date`, `$oid`)
- **Timestamp:** Available as `ts` column (with `$numberLong` wrapper) OR `CreatedAt` (ISO string)
- **Types:** All numeric values wrapped in MongoDB type objects
- **Row count:** Subset of data (e.g., 36,677 rows for LSE18B260667)
- **Internal ID:** `_id` field with MongoDB ObjectId (dropped after parsing)

### Example JSON Record
```json
{
  "_id": {"$oid": "507f1f77bcf86cd799439011"},
  "ts": {"$numberLong": "1774858212502"},
  "SoC": {"$numberLong": "100"},
  "Ip": {"$numberLong": "0"},
  "Vp": {"$numberLong": "54750"},
  "FullCap": {"$numberLong": "9000"},
  "CreatedAt": {"$date": "2026-03-30T08:11:46.591Z"},
  "BPackID": "LSE18B260667"
}
```

## Adapter Functions

### Core Conversion Functions

#### `unwrap_mongo_extended_json(value: Any) → Any`
Unwraps MongoDB Extended JSON scalar types:
- `{"$numberLong": "123"}` → `123` (int)
- `{"$numberInt": "42"}` → `42` (int)
- `{"$numberDouble": "3.14"}` → `3.14` (float)
- `{"$oid": "..."}` → `"..."` (string)
- `{"$date": "2026-03-30T..."}` → milliseconds (int)

Plain values are returned unchanged.

#### `parse_mongo_json_records(raw_data: Union[list, dict]) → List[Dict]`
Parses raw MongoDB JSON array/object into flat Python dictionaries.
- Handles both array and single-object inputs
- Unwraps all MongoDB Extended JSON types
- Returns list of clean dictionaries ready for DataFrame conversion

#### `normalize_timestamp_column(df: pd.DataFrame) → pd.DataFrame`
Normalizes timestamp representation to milliseconds (int64):

**Priority order:**
1. `timestamp` column (Parquet default) - use as-is
2. `ts` column (JSON alternative name) - rename and use
3. `CreatedAt` column (MongoDB ISO format) - parse and convert to ms, then drop

Result: DataFrame with `timestamp` column in milliseconds, any source column removed.

#### `normalize_battery_columns(df: pd.DataFrame) → pd.DataFrame`
Aligns column naming and ensures proper data types:

**Column name normalization:**
- `PackCapacity` → `FullCap` (canonical name used by algorithm)

**Type normalization:**
- All numeric columns (SoC, Ip, Vp, Tamb, voltages, etc.) → int64 or float64
- Handles missing columns gracefully (errors="coerce")

#### `load_json_battery_data(json_path: Union[str, Path]) → pd.DataFrame`
High-level function to load a complete JSON battery file:

**Steps:**
1. Load JSON from file
2. Parse MongoDB Extended JSON records
3. Convert to DataFrame
4. Drop MongoDB internal `_id` column
5. Normalize timestamps
6. Normalize column names and types

**Returns:** DataFrame matching Parquet format exactly.

### Integration Point

`battery_manager.py`:
```python
def load_battery_table(path: Union[str, Path]) -> pd.DataFrame:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".parquet":
        df = pd.read_parquet(path)
    elif suffix == ".json":
        df = load_json_battery_data(path)  # Adapter layer
    else:
        raise ValueError(f"Unsupported format: {path}")

    return normalize_ness_battery_columns(df)  # Final normalization
```

## Usage Example

```python
from battery_manager import load_battery_table

# Load Parquet (training)
df_train = load_battery_table("data/training_data/LSE18B260667.parquet")

# Load JSON (testing) - uses adapter automatically
df_test = load_battery_table("data/testing_data/LSE18B260667.json")

# Both DataFrames now have:
# - Same 43 columns
# - Same data types (int64 for numeric columns, object for strings)
# - Same `timestamp` format (milliseconds since epoch, int64)
# Ready for unified processing
```

## Data Type Consistency

After adapter processing, all numeric columns are converted to int64:

| Column | Parquet Type | JSON Type | After Adapter |
|--------|--------------|-----------|---------------|
| timestamp | int64 | int64 | int64 |
| SoC | object → int64 | int64 | int64 |
| Ip | object → int64 | int64 | int64 |
| Vp | object → int64 | int64 | int64 |
| Tamb | object → int64 | int64 | int64 |
| BT1-BT4 | object → int64 | int64 | int64 |
| V1-V16 | object → int64 | int64 | int64 |
| BPackID | object | object | object |

## Workflow: Training vs Testing

### Training (Parquet)
```yaml
execution:
  mode: "train_all_batteries"
  patterns_label: "march_2025"
  training_month: "2025-03"
```

1. Discovers `data/training_data/*.parquet`
2. Loads via Parquet reader (no adapter needed)
3. Normalizes columns and types
4. Trains LoadClassifier + SOCDecayAnalyzer
5. Saves patterns to SQLite

### Testing (JSON)
```yaml
execution:
  mode: "apply_battery"
  patterns_label: "march_2025"
  apply_month: "2025-04"
```

1. Discovers `data/testing_data/*.json`
2. Loads via adapter layer
3. Normalizes columns and types (same as Parquet)
4. Applies learned patterns
5. Outputs TTE/TTF estimates

Both produce identical DataFrame structure before algorithm processing.

## Minimal Changes Philosophy

The adapter follows strict principles to avoid disrupting existing code:

- ✅ **Added:** New `data_adapter.py` module with pure functions
- ✅ **Added:** Import of adapter in `battery_manager.py`
- ✅ **Modified:** `load_battery_table()` to use adapter for JSON (2 lines changed)
- ✅ **Enhanced:** `normalize_ness_battery_columns()` to handle all numeric types uniformly
- ❌ **NOT changed:** Core algorithm logic, database interactions, configuration parsing
- ❌ **NOT changed:** Any other existing functions

## Error Handling

The adapter raises clear errors for common issues:

```python
# Missing file
FileNotFoundError: "JSON file not found: data/testing_data/missing.json"

# Empty file
ValueError: "No valid records found in data/testing_data/empty.json"

# Missing timestamp
ValueError: "No timestamp column found. Expected: 'timestamp', 'ts', or 'CreatedAt'"
```

## Performance

- **JSON loading:** ~0.5-1.5s per file (depends on size and record count)
- **Parquet loading:** ~0.1-0.3s per file (native binary format)
- **Total pipeline:** Negligible overhead added by adapter

## Future Extensions

The adapter layer can be extended for additional data sources without changing core algorithm:

```python
# Potential future sources
if suffix == ".csv":
    df = load_csv_battery_data(path)
elif suffix == ".feather":
    df = load_feather_battery_data(path)
elif suffix == ".arrow":
    df = load_arrow_battery_data(path)
```

Each would follow the same pattern: parse → unwrap types → normalize columns/timestamps.

## Summary

| Aspect | Parquet | JSON | Unified |
|--------|---------|------|---------|
| Source | `data/training_data/` | `data/testing_data/` | - |
| Format | Binary parquet | MongoDB Extended JSON | Identical DataFrame |
| Parsing | Built-in `pd.read_parquet()` | Custom `data_adapter.py` | - |
| Columns | 43 | 44 (with _id, CreatedAt) | 43 (cleaned) |
| Types | Mixed (object/int64) | Properly typed | All normalized |
| Timestamp | `timestamp` (ms) | `ts` or `CreatedAt` | `timestamp` (ms, int64) |
| Ready for algorithm | ✓ | ✓ (after adapter) | ✓ |
