# Battery TTE/TTF Analysis GUI

Interactive Streamlit dashboard for visualizing Time To Empty (TTE) and Time To Full (TTF) estimates from battery test data.

## Quick Start

### Run the GUI

```bash
cd gui
streamlit run app.py
```

Or use the provided script:
```bash
# Windows
run.bat

# Linux/Mac
./run.sh
```

The app will open at `http://localhost:8501`

## Features

### 1. Test Results Summary (Expander)
Automatic statistics display showing:
- **Total Rows:** Number of data points processed
- **TTE Estimates:** Count and percentage of rows with Time To Empty predictions
- **TTF Estimates:** Count and percentage of rows with Time To Full predictions
- **High Confidence:** Number of high-confidence estimates
- **TTE Range:** Min, Max, Mean hours to empty
- **Source File:** Name of the CSV being displayed

### 2. Interactive Player (Top Controls)

#### Buttons
- **Play:** Auto-advance through data at configurable speed
- **Pause:** Stop the playback
- **Rest:** Reset to the beginning (row 1)

#### Real-time Status Bar
Shows current position with:
- Current row number and total rows
- Battery status (charging/discharging/rest)
- Current TTE estimate (formatted: "5h 30m" or "2d 3h")
- Current TTF estimate
- Timestamp of current sample

#### Progress Bar
Visual indicator of position in the dataset (0-100%)

### 3. Real-time Visualization (2x2 Panel)

Four synchronized plots with a cursor line at the current timestamp:

1. **SOC (%)** - Top Left
   - Battery state of charge percentage over time
   - Blue line

2. **Current (A)** - Top Right
   - Discharge/charge current in Amperes
   - Orange line (positive = discharge, negative = charge)

3. **Voltage (V)** - Bottom Left
   - Battery pack voltage in volts
   - Green line

4. **TTE & TTF (h)** - Bottom Right
   - Time To Empty (red line)
   - Time To Full (purple line)
   - Both plotted on same axes
   - NaN values shown as gaps (not interpolated)

**Interactions:**
- Hover over any line to see exact values
- Click legend items to show/hide traces
- Zoom, pan, and use zoom controls
- The cursor line shows your current position across all four panels

### 4. Data Explorer (Bottom Section)

#### Filters
Choose what data to view:
- **Status Filter:** Show charging, discharging, rest, or any combination
- **Confidence Filter:** Show high, medium, low confidence estimates, or mix
- **TTE-Only Toggle:** Show only rows with actual TTE predictions

#### Data Table
Display filtered results with columns:
- timestamp
- soc (%)
- voltage_v
- current_a
- status
- tte_hours
- ttf_hours
- confidence

Shows first 100 rows of filtered data with scrolling.

## Configuration

Edit values in `app.py` to customize behavior:

```python
VIEW_ROWS = 800              # How many rows to show in the rolling window
PLAY_STEP = 12               # Advance N rows per play step
PLAY_DELAY = 0.2             # Delay between steps (seconds) - reduce for faster playback
MAX_DRAW_POINTS = 1600       # Max points to draw on charts (for performance)
OUTPUT_DIR = ...             # Directory to watch for CSV files
```

## How It Works

1. **Auto-detection:** GUI automatically detects the most recently modified CSV file in `output/`
2. **Live sync:** If you run the algorithm again, the GUI will detect the new results and load them
3. **Cursor tracking:** As you play through the data, the cursor line shows exactly where you are across all four measurements
4. **Intelligent formatting:** TTE/TTF values display as human-readable time (e.g., "5h 30m" or "2d 3h")
5. **Special cases:**
   - At SOC < 5% with TTE = 0: Shows "⚠️ PLUG CHARGER"
   - At SOC > 99% with negative TTF: Shows "⚠️ UNPLUG CHARGER"

## Data Interpretation

### TTE (Time To Empty)
- Shows estimated hours until battery reaches 0% SOC
- Only populated during discharging states
- NaN (gap) during charging or rest
- Red line in TTE/TTF panel

### TTF (Time To Full)
- Shows estimated hours until battery reaches 100% SOC
- Only populated during charging states
- NaN (gap) during discharging or rest
- Purple line in TTE/TTF panel

### Confidence Levels
- **High:** Strict validation gates met (>15min session + 1Ah+ charge change)
- **Medium:** Relaxed gates met (allows earlier estimates)
- **Low:** No validation gates met (opportunistic estimate on every sample)

### Status Codes
- **charging:** Net current > +50 mA (battery taking charge)
- **discharging:** Net current < -50 mA (battery providing power)
- **rest:** Net current between ±50 mA (idle/standby state)

## Example Workflow

1. **Train the algorithm** on Parquet files:
   ```bash
   python src/main.py  # with mode: train_all_batteries
   ```

2. **Apply to test data** (JSON files):
   ```bash
   # Update config.yaml to mode: apply_battery
   python src/main.py
   ```

3. **View results** in GUI:
   ```bash
   cd gui
   streamlit run app.py
   ```

4. **Explore the data:**
   - Click "Play" to auto-advance
   - Watch TTE/TTF estimates change with battery state
   - Filter by confidence to see reliability distribution
   - Use the table to find specific samples

## Troubleshooting

### "Put at least one CSV in the output folder"
- Run the algorithm: `python src/main.py`
- Make sure `config.yaml` is set to `mode: apply_battery`
- Verify output files are in `output/` directory

### GUI doesn't update when I run new tests
- The app auto-detects new files
- If it doesn't update, try refreshing the browser (F5)
- Or restart the app and reload

### Performance is slow with large datasets
- Reduce `MAX_DRAW_POINTS` in `app.py` (default: 1600)
- Increase `PLAY_DELAY` to slow down playback
- Use Data Explorer filters to reduce table rows shown

### Cursor line doesn't align perfectly
- This is expected if timestamps have irregular intervals
- The line shows the exact timestamp of the current row

## Tips & Tricks

- **Full screen:** Press `F` while hovering over a chart to expand
- **Download data:** Use the "Download" button in the data table to export filtered results
- **Share snapshots:** Use Streamlit's built-in screenshot feature
- **Replay speeds:** Adjust `PLAY_STEP` and `PLAY_DELAY` for slower/faster playback

## Technical Details

- **Framework:** Streamlit (interactive web app)
- **Plotting:** Plotly (interactive charts)
- **Data:** Pandas DataFrames
- **Caching:** Streamlit caches CSV reads for performance
- **File detection:** Watches `output/` for most recently modified CSV
