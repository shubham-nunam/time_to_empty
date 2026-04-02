"""
Streamlit UI: replay the latest battery CSV from ../output with a live cursor on four panels.
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

# —— tuning —— #
VIEW_ROWS = 800
PLAY_STEP = 12
PLAY_DELAY = 0.2
MAX_DRAW_POINTS = 1600
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"
PATTERNS_DIR = Path(__file__).resolve().parent.parent / "training_data"


@st.cache_data
def read_export(csv_path: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    df["timestamp"] = pd.to_datetime(df["timestamp"], format='ISO8601')
    df = df.sort_values("timestamp").reset_index(drop=True)
    for c in ("tte_hours", "ttf_hours"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def latest_csv() -> Path | None:
    files = list(OUTPUT_DIR.glob("*.csv"))
    if not files:
        return None
    return max(files, key=lambda p: p.stat().st_mtime)


def thin(df: pd.DataFrame, cap: int) -> pd.DataFrame:
    n = len(df)
    if n <= cap:
        return df
    step = max(1, n // cap)
    idx = sorted({*range(0, n, step), n - 1})
    return df.iloc[idx]


def fmt_hours(x, soc: float = None, empty_threshold: float = 5.0, full_threshold: float = 99.0) -> str:
    """Format hours with special handling for charger control thresholds."""
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "—"
    try:
        h = float(x)
    except (TypeError, ValueError):
        return "—"

    # Special cases: SOC-based thresholds for charger control
    if soc is not None:
        if soc < empty_threshold and h == 0.0:
            return "⚠️ PLUG CHARGER"
        elif soc > full_threshold and h < 0:
            return "⚠️ UNPLUG CHARGER"

    if h < 0:
        return "—"
    if h >= 24:
        return f"{int(h // 24)}d {int(h % 24)}h"
    return f"{int(h)}h {int((h % 1) * 60)}m"


def figure_2x2(win: pd.DataFrame, now_ts: pd.Timestamp, line_at_now: bool) -> go.Figure:
    t = win["timestamp"]
    fig = make_subplots(
        rows=2,
        cols=2,
        shared_xaxes="columns",
        vertical_spacing=0.12,
        horizontal_spacing=0.06,
        subplot_titles=("SOC (%)", "Current (A)", "Voltage (V)", "TTE & TTF (h)"),
    )

    fig.add_trace(go.Scatter(x=t, y=win["soc"], mode="lines", line=dict(color="#2563eb", width=1.3), name="SOC"), row=1, col=1)
    fig.add_trace(
        go.Scatter(x=t, y=win["current_a"], mode="lines", line=dict(color="#ea580c", width=1.2), name="A", showlegend=False),
        row=1,
        col=2,
    )
    fig.add_trace(
        go.Scatter(x=t, y=win["voltage_v"], mode="lines", line=dict(color="#16a34a", width=1.2), name="V", showlegend=False),
        row=2,
        col=1,
    )
    if "tte_hours" in win.columns:
        fig.add_trace(
            go.Scatter(x=t, y=win["tte_hours"], mode="lines", line=dict(color="#dc2626", width=1.15), name="TTE", connectgaps=False),
            row=2,
            col=2,
        )
    if "ttf_hours" in win.columns:
        fig.add_trace(
            go.Scatter(x=t, y=win["ttf_hours"], mode="lines", line=dict(color="#9333ea", width=1.15), name="TTF", connectgaps=False),
            row=2,
            col=2,
        )

    if line_at_now:
        for r, c in (1, 1), (1, 2), (2, 1), (2, 2):
            fig.add_vline(x=now_ts, line_width=1.5, line_dash="solid", line_color="#64748b", opacity=0.9, row=r, col=c)

    fig.update_xaxes(showticklabels=False, row=1, col=1)
    fig.update_xaxes(showticklabels=False, row=1, col=2)
    fig.update_xaxes(title_text="Time", row=2, col=1)
    fig.update_xaxes(title_text="Time", row=2, col=2)

    fig.update_layout(
        height=440,
        template="plotly_white",
        margin=dict(l=48, r=28, t=48, b=40),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font=dict(size=10)),
        showlegend=True,
        uirevision="1",
    )
    for ann in fig.layout.annotations:
        ann.font = dict(size=10)
    return fig


def ensure_state() -> None:
    for k, v in (
        ("bundle", None),
        ("ix", 0),
        ("run", False),
    ):
        if k not in st.session_state:
            st.session_state[k] = v


def sync_data() -> tuple[pd.DataFrame, Path] | None:
    path = latest_csv()
    if path is None:
        return None
    tag = (str(path.resolve()), path.stat().st_mtime)
    if st.session_state.bundle != tag:
        st.session_state.bundle = tag
        st.session_state.df = read_export(str(path))
        st.session_state.ix = 0
        st.session_state.run = False
    return st.session_state.df, path


def main() -> None:
    st.set_page_config(page_title="Battery TTE/TTF Replay", layout="wide")
    ensure_state()

    st.markdown("### Battery TTE/TTF Analysis - Test Results")
    st.caption(f"Data source: `{OUTPUT_DIR}` — displaying the most recently modified `*.csv`")

    got = sync_data()
    if got is None:
        st.info("No CSV files found in output folder. Run the algorithm to generate test results.")
        return

    df, src = got
    n = len(df)
    if n == 0:
        st.warning("CSV is empty.")
        return

    # Show file info and statistics
    with st.expander("Test Results Info", expanded=True):
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Rows", f"{n:,}")
        with col2:
            tte_count = df["tte_hours"].notna().sum()
            st.metric("TTE Estimates", f"{tte_count:,} ({tte_count/n*100:.1f}%)")
        with col3:
            ttf_count = df["ttf_hours"].notna().sum()
            st.metric("TTF Estimates", f"{ttf_count:,} ({ttf_count/n*100:.1f}%)")
        with col4:
            high_conf = (df.get("confidence", "") == "high").sum()
            st.metric("High Confidence", f"{high_conf:,} ({high_conf/n*100:.1f}%)")

        col5, col6, col7, col8 = st.columns(4)
        with col5:
            if "tte_hours" in df.columns and tte_count > 0:
                st.metric("TTE Min", f"{df['tte_hours'].min():.2f}h")
        with col6:
            if "tte_hours" in df.columns and tte_count > 0:
                st.metric("TTE Max", f"{df['tte_hours'].max():.2f}h")
        with col7:
            if "tte_hours" in df.columns and tte_count > 0:
                st.metric("TTE Mean", f"{df['tte_hours'].mean():.2f}h")
        with col8:
            st.metric("Source File", src.name)

    ix = int(np.clip(st.session_state.ix, 0, n - 1))
    st.session_state.ix = ix

    r0, r1, r2, _ = st.columns([1, 1, 1, 2])
    with r0:
        go_play = st.button("Play", type="primary", use_container_width=True)
    with r1:
        go_pause = st.button("Pause", use_container_width=True)
    with r2:
        go_rest = st.button("Rest", use_container_width=True)

    if go_play:
        st.session_state.run = True
    if go_pause:
        st.session_state.run = False
    if go_rest:
        st.session_state.ix = 0
        st.session_state.run = False
        st.rerun()

    here = df.iloc[ix]
    lo = max(0, ix - VIEW_ROWS + 1)
    win = thin(df.iloc[lo : ix + 1].copy(), MAX_DRAW_POINTS)

    tte = here["tte_hours"] if "tte_hours" in here.index else np.nan
    ttf = here["ttf_hours"] if "ttf_hours" in here.index else np.nan
    soc = here["soc"] if "soc" in here.index else None
    st.caption(f"`{src.name}` · row **{ix + 1}** / **{n}** · **{here['status']}** · TTE **{fmt_hours(tte, soc)}** · TTF **{fmt_hours(ttf, soc)}** · `{here['timestamp']}`")

    fig = figure_2x2(win, pd.Timestamp(here["timestamp"]), line_at_now=True)
    st.plotly_chart(fig, use_container_width=True, key=f"g_{ix}")

    st.progress((ix + 1) / n)

    if st.session_state.run and ix < n - 1:
        st.session_state.ix = min(ix + PLAY_STEP, n - 1)
        time.sleep(PLAY_DELAY)
        st.rerun()

    # Show detailed data view and statistics
    st.divider()
    st.markdown("### Data Explorer")

    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        status_filter = st.multiselect("Filter by Status", ["charging", "discharging", "rest"], default=["charging", "discharging"])
    with col2:
        confidence_filter = st.multiselect("Filter by Confidence", ["high", "medium", "low"], default=["high", "medium", "low"])
    with col3:
        show_only_tte = st.checkbox("Show only rows with TTE estimates")

    # Apply filters
    filtered_df = df.copy()
    if status_filter:
        filtered_df = filtered_df[filtered_df["status"].isin(status_filter)]
    if confidence_filter:
        filtered_df = filtered_df[filtered_df.get("confidence", "").isin(confidence_filter)]
    if show_only_tte:
        filtered_df = filtered_df[filtered_df["tte_hours"].notna()]

    st.subheader(f"Data Table ({len(filtered_df):,} rows)")
    st.dataframe(
        filtered_df[["timestamp", "soc", "voltage_v", "current_a", "status", "tte_hours", "ttf_hours", "confidence"]].head(100),
        use_container_width=True,
        height=400,
    )


if __name__ == "__main__":
    main()
