# Battery Simulation GUI

A Streamlit-based real-time visualization and simulation tool for battery behavior prediction, displaying Time to Empty (TTE) and Time to Full (TTF) metrics with live SOC and current monitoring.

## Features

- **Real-Time Simulation**: Play button to step through historical battery data at configurable speeds
- **TTE/TTF Tracking**: Automatically displays Time to Empty during discharging and Time to Full during charging
- **Dynamic Visualization**:
  - State of Charge (SOC) trend
  - Current draw over time
  - Battery voltage monitoring
- **Interactive Controls**:
  - Play/Pause/Reset buttons for simulation control
  - Speed adjustment (1-100× real-time)
  - Batch size control for processing frequency
  - Timeline scrubber to jump to any point in the dataset
- **Status Monitoring**: Color-coded status indicator (🟢 charging, 🔴 discharging, 🔵 rest)
- **Detailed Metrics**: KPI cards showing current SOC, voltage, current draw, and time estimates

## Installation

1. Install Streamlit and dependencies:
```bash
pip install -r requirements.txt
```

Or install into the existing virtual environment:
```bash
.venv/Scripts/pip install streamlit plotly
```

## Usage

### Run the Application

```bash
streamlit run gui/app.py
```

The app will open in your browser at `http://localhost:8501`

### How to Use the Simulator

1. **Select a CSV File**: Choose a results CSV from the sidebar (e.g., `tte_ttf_results_2025-09.csv`)
2. **Configure Settings**:
   - **Speed Factor**: Control simulation speed (10× = 10 times real-time)
   - **Rows per Update**: Number of data points to process between screen updates (default: 5)
3. **Play the Simulation**:
   - Click **▶️ Play** to start stepping through the data
   - Click **⏸️ Pause** to pause the simulation
   - Click **🔄 Reset** to restart from the beginning
4. **Navigate**:
   - Use the **Jump to Time** slider to jump to any point in the dataset
   - Watch the charts update in real-time as the simulation progresses

### Interface Sections

#### Left Sidebar
- File selection and data statistics
- Simulation speed and batch size controls
- Play/Pause/Reset buttons
- Progress indicator and timeline scrubber

#### Main Dashboard

**Top Metrics**:
- **Status**: Current charging state (charging/discharging/rest)
- **Time Estimate**: TTE during discharge, TTF during charge
- **SOC**: Current state of charge (0-100%)
- **Current**: Absolute current draw in Amps
- **Voltage**: Battery pack voltage in Volts

**Time Series Charts**:
- **State of Charge**: SOC trend over the simulation window
- **Current Draw**: Current consumption/supply over time
- **Battery Voltage**: Pack voltage trend

**Detailed Information**: Expandable section with raw values, capacity, confidence metrics, and time estimates

## Data Format

The app expects CSV files in the `outputs/` directory with the following columns:

```
timestamp       - ISO datetime (YYYY-MM-DD HH:MM:SS.mmm)
voltage_v       - Battery voltage in Volts
current_a       - Current in Amps (positive = charging, negative = discharging)
status          - 'charging', 'discharging', or 'rest'
tte_hours       - Time to Empty estimate (hours, NaN if not discharging)
ttf_hours       - Time to Full estimate (hours, NaN if not charging)
soc             - State of Charge (0-100%)
capacity_ah     - Battery capacity in Amp-hours
confidence      - Prediction confidence level (low/medium/high)
num_samples     - Number of samples used in calculation
```

## Configuration

The simulation reads battery parameters from `../config.yaml`:
- `tte_ttf.tte_ttf_smoothing_factor`: Controls output smoothness (0.1 = smooth, 0.3 = responsive)
- `tte_ttf.session_min_duration_minutes`: Minimum session duration for valid estimates
- `tte_ttf.session_min_energy_ah`: Minimum energy change per session
- `tte_ttf.ema_window_minutes`: EMA window for current smoothing

## Tips for Best Results

### If TTE/TTF values seem jumpy:
- Reduce the **Speed Factor** for slower, smoother updates
- Increase the **Rows per Update** to process more data between visualizations

### If you want to analyze a specific period:
- Use the **Jump to Time** slider to navigate quickly
- Adjust the **Rows per Update** to control chart granularity

### For monitoring long-term trends:
- The charts display the last 100 rows, automatically scrolling as simulation progresses
- Use the detailed information panel to see raw values at any point

## Architecture

- **Data Loading**: Lazy loads CSV files with pandas
- **Streamlit Session State**: Maintains simulation state across reruns (current index, playback status)
- **Plotly Visualization**: Interactive charts with hover tooltips and zoom capabilities
- **Real-Time Updates**: Uses Streamlit's reruns to drive the simulation loop

## Troubleshooting

**"No CSV files found"**
- Ensure the TTE/TTF calculation has been run and output files exist in the `outputs/` directory
- Run `python src/main.py` to generate results

**Charts not updating**
- Check the Speed Factor setting (may be very slow)
- Verify the CSV file contains valid data

**App is slow**
- Reduce the **Speed Factor** or increase **Rows per Update**
- Close other applications to free up system resources

## Future Enhancements

- Export simulation session as video or GIF
- Save/load custom simulation bookmarks
- Comparison mode for multiple battery packs
- Predictive overlays (forecast of SOC/current)
- Battery health metrics dashboard
