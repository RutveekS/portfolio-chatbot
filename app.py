import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import numpy as np
import re

st.set_page_config(page_title="Funds Analytics", layout="wide")

# ------------------ FILE UPLOAD ------------------ #
uploaded_file = st.file_uploader("📂 Upload Portfolio Excel", type=["xlsx"])
perf_file = st.file_uploader("📈 Upload Performance Excel", type=["xlsx"])

@st.cache_data
def load_data(file):
    df = pd.read_excel(file)
    df.columns = df.columns.str.strip().str.replace("\n", "").str.replace("  ", " ")
    cols_lower = {col.lower(): col for col in df.columns}

    def get_col(possible_names):
        for name in possible_names:
            if name.lower() in cols_lower:
                return cols_lower[name.lower()]
        return None

    col_map = {
        "scheme": get_col(["Scheme Name"]),
        "company": get_col(["Company Name"]),
        "macro_sector": get_col(["Macro Economic Sector"]),
        "sector": get_col(["Sector"]),
        "industry": get_col(["Industry"]),
        "basic_industry": get_col(["Basic Industry"]),
        "market_cap": get_col(["Market Cap"]),
        "fund_type": get_col(["Fund Type"]),
        "weight": get_col(["% of Net Assets", "Weight", "% Net Assets"]),
    }

    missing = [k for k, v in col_map.items() if v is None and k in ["scheme", "company", "weight"]]
    if missing:
        st.error(f"❌ Missing required columns: {missing}")
        st.write("Columns found:", list(df.columns))
        st.stop()

    df = df.rename(columns={v: k for k, v in col_map.items() if v is not None})
    df["weight"] = pd.to_numeric(df["weight"], errors="coerce").fillna(0)

    for col in ["scheme", "company", "sector", "industry", "basic_industry", "market_cap", "fund_type", "macro_sector"]:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()

    return df


@st.cache_data
def load_perf_data(file):
    xl = pd.ExcelFile(file)

    master = xl.parse("Master Categorisation List")
    master.columns = master.columns.str.strip()
    master = master.rename(columns={
        "Fund Name": "fund_name",
        "Name as per MFIE": "mfie_name",
        "Fund Manager": "fund_manager",
        "Start": "start_date",
        "End Date": "end_date",
        "Categorisation": "categorisation",
        "Wherever there is a change in categorisation": "cat_change_note",
        "ISIN": "isin",
        "Benchmark": "benchmark",
    })
    master["mfie_name"] = master["mfie_name"].astype(str).str.strip()
    master["isin"] = master["isin"].astype(str).str.strip()
    master["benchmark"] = master["benchmark"].astype(str).str.strip()

    bm = xl.parse("BM1")
    bm.columns = bm.columns.str.strip()
    bm = bm.rename(columns={bm.columns[0]: "date"})
    bm["date"] = pd.to_datetime(bm["date"], errors="coerce")
    bm = bm.dropna(subset=["date"]).sort_values("date").set_index("date")
    bm = bm.apply(pd.to_numeric, errors="coerce")

    nav_raw = xl.parse("Updated NAV")
    nav_raw.columns = nav_raw.columns.str.strip()
    date_col = nav_raw.columns[0]
    nav_raw = nav_raw.rename(columns={date_col: "date"})

    first_val = str(nav_raw.iloc[0, 1]) if len(nav_raw) > 0 else ""
    if first_val.startswith("INF"):
        nav = nav_raw.iloc[1:].copy()
        nav.columns = nav_raw.columns
        nav["date"] = pd.to_datetime(nav["date"], errors="coerce")
        nav = nav.dropna(subset=["date"]).sort_values("date").set_index("date")
        for col in nav.columns:
            nav[col] = pd.to_numeric(nav[col], errors="coerce")
    else:
        nav = nav_raw.copy()
        nav["date"] = pd.to_datetime(nav["date"], errors="coerce")
        nav = nav.dropna(subset=["date"]).sort_values("date").set_index("date")
        for col in nav.columns:
            nav[col] = pd.to_numeric(nav[col], errors="coerce")

    return master, bm, nav


# ------------------ LOAD DATA ------------------ #
df = None
master = bm = nav = None

if uploaded_file is not None:
    df = load_data(uploaded_file)

if perf_file is not None:
    try:
        master, bm, nav = load_perf_data(perf_file)
    except Exception as e:
        st.warning(f"⚠️ Could not load performance file: {e}")

if df is None:
    st.info("Please upload a Portfolio Excel file to begin.")
    st.stop()

st.title("📊 Funds Analytics Dashboard")

# ------------------ HELPERS ------------------ #
def export_csv(dataframe):
    return dataframe.to_csv(index=False).encode("utf-8")

def get_market_cap_split(df_in):
    cap = df_in.groupby("market_cap")["weight"].sum()
    return {
        "Large": cap.get("Large Cap", 0),
        "Mid": cap.get("Mid Cap", 0),
        "Small": cap.get("Small Cap", 0),
    }

def build_fund_table(df_in):
    rows = []
    grouped = df_in.groupby("scheme")
    for scheme, data in grouped:
        cap = get_market_cap_split(data)
        fund_type = data["fund_type"].iloc[0] if "fund_type" in data.columns else "NA"
        total_weight = data["weight"].sum()
        rows.append({
            "Fund Name": scheme,
            "Large Cap %": round(cap["Large"], 2),
            "Mid Cap %": round(cap["Mid"], 2),
            "Small Cap %": round(cap["Small"], 2),
            "Fund Type": fund_type,
            "Weight": round(total_weight, 2)
        })
    return pd.DataFrame(rows).sort_values("Weight", ascending=False)

def calculate_overlap(df_in, funds):
    pivot = df_in[df_in["scheme"].isin(funds)].pivot_table(
        index="company", columns="scheme", values="weight", aggfunc="sum"
    ).fillna(0)
    overlap = pd.DataFrame(index=funds, columns=funds)
    for f1 in funds:
        for f2 in funds:
            if f1 in pivot.columns and f2 in pivot.columns:
                overlap.loc[f1, f2] = (pivot[[f1, f2]].min(axis=1)).sum()
            else:
                overlap.loc[f1, f2] = 0.0
    return overlap.astype(float).round(2)

def sector_cross(df_in, funds, level):
    temp = df_in[df_in["scheme"].isin(funds)]
    table = temp.pivot_table(
        index=level, columns="scheme", values="weight", aggfunc="sum"
    ).fillna(0)
    return table.round(2)

# ------------------ PERFORMANCE HELPERS ------------------ #
def get_nav_series(fund_mfie_name, nav_df, master_df):
    if nav_df is None or master_df is None:
        return None
    if fund_mfie_name in nav_df.columns:
        return nav_df[fund_mfie_name].dropna()
    fund_rows = master_df[master_df["mfie_name"] == fund_mfie_name]
    if not fund_rows.empty:
        isin = fund_rows["isin"].iloc[0]
        if isin in nav_df.columns:
            return nav_df[isin].dropna()
    for col in nav_df.columns:
        if fund_mfie_name.lower() in str(col).lower():
            return nav_df[col].dropna()
    return None

def get_benchmark_series(benchmark_name, bm_df):
    if bm_df is None or benchmark_name is None:
        return None
    if benchmark_name in bm_df.columns:
        return bm_df[benchmark_name].dropna()
    for col in bm_df.columns:
        if benchmark_name.lower() in str(col).lower():
            return bm_df[col].dropna()
    return None

def compute_returns(series):
    if series is None or len(series) < 2:
        return {}
    series = series.sort_index().dropna()
    last_date = series.index[-1]
    last_val = series.iloc[-1]
    periods = {"1M": 30, "3M": 90, "6M": 180, "1Y": 365, "3Y": 3 * 365, "5Y": 5 * 365}
    annualised_periods = {"3Y", "5Y"}
    results = {}
    for label, days in periods.items():
        try:
            past = series[series.index <= last_date - pd.Timedelta(days=days)]
            if past.empty:
                results[label] = None
                continue
            past_val = past.iloc[-1]
            raw = (last_val / past_val) - 1
            if label in annualised_periods:
                years = days / 365
                results[label] = (1 + raw) ** (1 / years) - 1
            else:
                results[label] = raw
        except Exception:
            results[label] = None
    return results

def compute_annualised_return(series, start_date, end_date):
    """Compute annualised return for a series between two dates."""
    if series is None or series.empty:
        return None
    try:
        s = series.sort_index().dropna()
        s = s[(s.index >= pd.Timestamp(start_date)) & (s.index <= pd.Timestamp(end_date))]
        if len(s) < 2:
            return None
        years = (s.index[-1] - s.index[0]).days / 365.25
        if years < 1 / 12:
            return (s.iloc[-1] / s.iloc[0]) - 1
        raw = (s.iloc[-1] / s.iloc[0]) - 1
        return (1 + raw) ** (1 / years) - 1
    except Exception:
        return None

def compute_drawdown(series):
    if series is None or len(series) < 2:
        return None
    series = series.sort_index().dropna()
    rolling_max = series.cummax()
    drawdown = (series - rolling_max) / rolling_max * 100
    return drawdown

def compute_calendar_returns(series):
    if series is None or len(series) < 2:
        return {}
    series = series.sort_index().dropna()
    cal = {}
    for yr in sorted(series.index.year.unique()):
        yr_data = series[series.index.year == yr]
        if len(yr_data) < 2:
            continue
        ret = (yr_data.iloc[-1] / yr_data.iloc[0]) - 1
        cal[yr] = round(ret * 100, 2)
    return cal

def get_fund_benchmark(mfie_name, master_df):
    if master_df is None:
        return None
    rows = master_df[master_df["mfie_name"] == mfie_name]
    if not rows.empty:
        bm_val = rows["benchmark"].iloc[0]
        if bm_val and bm_val != "nan":
            return bm_val
    return None

def match_portfolio_scheme_to_mfie(scheme_name, master_df):
    if master_df is None:
        return None
    exact = master_df[master_df["mfie_name"] == scheme_name]
    if not exact.empty:
        return scheme_name
    for mfie in master_df["mfie_name"].unique():
        if scheme_name.lower() in str(mfie).lower() or str(mfie).lower() in scheme_name.lower():
            return mfie
    return None

def style_return_value(val):
    if val in ("N/A", "No BM", ""):
        return ""
    try:
        num = float(str(val).replace("%", ""))
        return f"color: {'#2ecc71' if num >= 0 else '#e74c3c'}; font-weight: bold"
    except Exception:
        return ""

def style_numeric_value(val):
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return ""
    try:
        return f"color: {'#2ecc71' if float(val) >= 0 else '#e74c3c'}; font-weight: bold"
    except Exception:
        return ""

def render_returns_table(fund_rets, bm_rets, fund_label="Fund", bm_label="Benchmark"):
    periods = ["1M", "3M", "6M", "1Y", "3Y", "5Y"]
    annualised_set = {"3Y", "5Y"}
    rows = []
    for p in periods:
        f_val = fund_rets.get(p)
        b_val = bm_rets.get(p)
        alpha = (f_val - b_val) if (f_val is not None and b_val is not None) else None
        rows.append({
            "Period": f"{p} {'(Ann.)' if p in annualised_set else ''}",
            fund_label: f"{f_val * 100:.2f}%" if f_val is not None else "N/A",
            bm_label: f"{b_val * 100:.2f}%" if b_val is not None else "N/A",
            "Alpha": f"{alpha * 100:.2f}%" if alpha is not None else "N/A",
        })
    ret_df = pd.DataFrame(rows)
    styled = ret_df.style.map(style_return_value, subset=[fund_label, bm_label, "Alpha"])
    st.dataframe(styled, use_container_width=True, hide_index=True)

def render_calendar_table(fund_cal, bm_cal, fund_label="Fund (%)", bm_label="Benchmark (%)"):
    all_years = sorted(set(list(fund_cal.keys()) + list(bm_cal.keys())))
    if not all_years:
        st.info("Not enough data for calendar year returns.")
        return None
    rows = []
    for yr in all_years:
        f = fund_cal.get(yr)
        b = bm_cal.get(yr)
        alpha = round(f - b, 2) if (f is not None and b is not None) else None
        rows.append({"Year": yr, fund_label: f, bm_label: b, "Alpha (%)": alpha})
    cal_df = pd.DataFrame(rows)
    styled = cal_df.style.map(style_numeric_value, subset=[fund_label, bm_label, "Alpha (%)"])
    st.dataframe(styled, use_container_width=True, hide_index=True)
    return cal_df

def render_nav_chart(nav_plot, bm_plot, fund_label, bm_label):
    fig = go.Figure()
    nav_idx = nav_plot / nav_plot.iloc[0] * 100
    fig.add_trace(go.Scatter(x=nav_idx.index, y=nav_idx.values,
                             name=fund_label, line=dict(width=2, color="#3498db")))
    if bm_plot is not None and not bm_plot.empty:
        common_start = max(nav_plot.index[0], bm_plot.index[0])
        bm_trimmed = bm_plot[bm_plot.index >= common_start]
        if not bm_trimmed.empty:
            bm_idx = bm_trimmed / bm_trimmed.iloc[0] * 100
            fig.add_trace(go.Scatter(x=bm_idx.index, y=bm_idx.values,
                                     name=bm_label, line=dict(width=2, dash="dash", color="#95a5a6")))
    fig.update_layout(yaxis_title="Indexed (Base=100)", xaxis_title="Date", hovermode="x unified")
    st.plotly_chart(fig, use_container_width=True)

def render_drawdown_chart(nav_plot, bm_plot, fund_label, bm_label):
    dd = compute_drawdown(nav_plot)
    bm_dd = compute_drawdown(bm_plot) if (bm_plot is not None and not bm_plot.empty) else None
    fig = go.Figure()
    if dd is not None:
        fig.add_trace(go.Scatter(x=dd.index, y=dd.values, fill="tozeroy",
                                 name=f"{fund_label} Drawdown",
                                 line=dict(color="#e74c3c", width=1)))
    if bm_dd is not None:
        fig.add_trace(go.Scatter(x=bm_dd.index, y=bm_dd.values,
                                 name=f"{bm_label} Drawdown",
                                 line=dict(color="#3498db", width=1, dash="dash")))
    fig.update_layout(yaxis_title="Drawdown (%)", xaxis_title="Date", hovermode="x unified")
    st.plotly_chart(fig, use_container_width=True)
    if dd is not None:
        c1, c2 = st.columns(2)
        c1.metric("Max Drawdown", f"{dd.min():.2f}%")
        c2.metric("Date of Max Drawdown", str(dd.idxmin().date()))

def render_calendar_bar_chart(cal_df, fund_label, bm_label, bm_name):
    fig = go.Figure()
    fig.add_trace(go.Bar(x=cal_df["Year"], y=cal_df[fund_label],
                         name=fund_label, marker_color="#3498db"))
    if bm_name:
        fig.add_trace(go.Bar(x=cal_df["Year"], y=cal_df[bm_label],
                             name=bm_name, marker_color="#95a5a6"))
    fig.update_layout(barmode="group", yaxis_title="Return (%)",
                      xaxis_title="Year", hovermode="x unified")
    st.plotly_chart(fig, use_container_width=True)

def slice_series_by_range(series, date_range):
    range_map = {"1Y": 365, "3Y": 3 * 365, "5Y": 5 * 365, "Max": None}
    days_back = range_map.get(date_range)
    if days_back and series is not None and not series.empty:
        start_cut = series.index.max() - pd.Timedelta(days=days_back)
        return series[series.index >= start_cut]
    return series


# ------------------ FUND DEEP DIVE ------------------ #
def render_fund_deep_dive(df_all, scheme):
    fund_df = df_all[df_all["scheme"] == scheme].copy()
    st.markdown(f"## {scheme}")

    total_weight = fund_df["weight"].sum()
    stocks = fund_df["company"].nunique()

    c1, c2 = st.columns(2)
    c1.metric("Total Weight", f"{total_weight:.2f}%")
    c2.metric("Number of Stocks", stocks)

    st.markdown("### Market Cap Allocation")
    cap = fund_df.groupby("market_cap", as_index=False)["weight"].sum()
    fig = px.pie(cap, names="market_cap", values="weight")
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("### Sector Allocation")
    sector_df = fund_df.groupby("sector", as_index=False)["weight"].sum().sort_values("weight")
    fig_sec = px.bar(sector_df, x="weight", y="sector", orientation="h", text="weight")
    fig_sec.update_traces(texttemplate="%{text:.2f}%")
    st.plotly_chart(fig_sec, use_container_width=True)

    st.markdown("### Sector Drilldown")
    sun = fund_df.groupby(
        ["macro_sector", "sector", "industry", "basic_industry"], as_index=False
    )["weight"].sum()
    fig_sun = px.sunburst(
        sun, path=["macro_sector", "sector", "industry", "basic_industry"], values="weight"
    )
    st.plotly_chart(fig_sun, use_container_width=True)

    top = fund_df.groupby("company", as_index=False)["weight"].sum().sort_values("weight", ascending=False)
    top5 = top.head(5)
    top10 = top.head(10)

    st.markdown("### Top 10 Holdings")
    st.dataframe(top10, use_container_width=True, hide_index=True)

    top5_sum = top5["weight"].sum()
    top10_sum = top10["weight"].sum()
    conviction = top10_sum / total_weight if total_weight > 0 else 0

    c1, c2, c3 = st.columns(3)
    c1.metric("Top 5 %", f"{top5_sum:.2f}%")
    c2.metric("Top 10 %", f"{top10_sum:.2f}%")
    c3.metric("Conviction Score", f"{conviction:.2f}")

    # ------------------ FUND MANAGER TENURE + PERFORMANCE ------------------ #
    if master is not None:
        mfie = match_portfolio_scheme_to_mfie(scheme, master)
        if mfie:
            fm_rows = master[master["mfie_name"] == mfie][
                ["fund_manager", "start_date", "end_date", "categorisation"]
            ].copy()

            if not fm_rows.empty:
                st.markdown("### Historical Fund Managers & Tenure Performance")

                benchmark_name = get_fund_benchmark(mfie, master)
                nav_series = get_nav_series(mfie, nav, master) if nav is not None else None
                bm_series = get_benchmark_series(benchmark_name, bm) if (bm is not None and benchmark_name) else None

                fm_rows["start_date"] = pd.to_datetime(fm_rows["start_date"], errors="coerce")
                fm_rows["end_date"] = pd.to_datetime(fm_rows["end_date"], errors="coerce")

                nav_last_date = (
                    nav_series.index.max()
                    if (nav_series is not None and not nav_series.empty)
                    else pd.Timestamp.today()
                )
                fm_rows["end_date_filled"] = fm_rows["end_date"].fillna(nav_last_date)

                display_rows = []
                for _, row in fm_rows.iterrows():
                    start = row["start_date"]
                    end = row["end_date_filled"]
                    end_label = row["end_date"].strftime("%b %Y") if pd.notna(row["end_date"]) else "Present"

                    if pd.isna(start):
                        display_rows.append({
                            "Fund Manager": row["fund_manager"],
                            "Start Date": "N/A",
                            "End Date": end_label,
                            "Categorisation": row["categorisation"],
                            "Tenure (Yrs)": "N/A",
                            "Fund Return (Ann.)": "N/A",
                            "Benchmark Return (Ann.)": "N/A",
                            "Alpha (Ann.)": "N/A",
                        })
                        continue

                    tenure_years = (end - start).days / 365.25 if pd.notna(end) else None
                    fund_ret = compute_annualised_return(nav_series, start, end) if nav_series is not None else None
                    bm_ret = compute_annualised_return(bm_series, start, end) if bm_series is not None else None
                    alpha = (fund_ret - bm_ret) if (fund_ret is not None and bm_ret is not None) else None

                    display_rows.append({
                        "Fund Manager": row["fund_manager"],
                        "Start Date": start.strftime("%b %Y"),
                        "End Date": end_label,
                        "Categorisation": row["categorisation"],
                        "Tenure (Yrs)": f"{tenure_years:.1f}" if tenure_years is not None else "N/A",
                        "Fund Return (Ann.)": f"{fund_ret * 100:.2f}%" if fund_ret is not None else "N/A",
                        "Benchmark Return (Ann.)": (
                            f"{bm_ret * 100:.2f}%" if bm_ret is not None
                            else ("N/A" if bm_series is not None else "No BM")
                        ),
                        "Alpha (Ann.)": f"{alpha * 100:.2f}%" if alpha is not None else "N/A",
                    })

                fm_display_df = pd.DataFrame(display_rows)
                styled_fm = fm_display_df.style.map(
                    style_return_value,
                    subset=["Alpha (Ann.)", "Fund Return (Ann.)"]
                )
                st.dataframe(styled_fm, use_container_width=True, hide_index=True)

                if benchmark_name:
                    st.caption(f"Benchmark used: **{benchmark_name}**")
                else:
                    st.caption("No benchmark found in Master sheet for this fund.")

    full = fund_df[["company", "weight", "market_cap", "macro_sector", "sector", "industry", "basic_industry"]]
    st.download_button(
        "Download Full Portfolio CSV",
        export_csv(full),
        f"{scheme}_portfolio.csv",
        "text/csv"
    )


# ------------------ PERFORMANCE TAB ------------------ #
def render_performance_tab(df_portfolio, master_df, bm_df, nav_df):
    st.markdown("## 📈 Fund Performance")

    if nav_df is None or master_df is None:
        st.warning("Please upload the Performance Excel file to use this tab.")
        return

    all_schemes = sorted(df_portfolio["scheme"].dropna().unique())
    selected_fund = st.selectbox("Select Fund", all_schemes, key="perf_fund")

    mfie = match_portfolio_scheme_to_mfie(selected_fund, master_df)
    auto_bm = get_fund_benchmark(mfie, master_df) if mfie else None

    bm_cols = list(bm_df.columns) if bm_df is not None else []
    bm_mode = st.radio("Benchmark Selection", ["Auto (from Master sheet)", "Manual"], horizontal=True)

    if bm_mode == "Auto (from Master sheet)":
        selected_bm = auto_bm
        if selected_bm:
            st.info(f"Auto-matched benchmark: **{selected_bm}**")
        else:
            st.warning("No benchmark found in Master sheet for this fund. Switch to Manual.")
    else:
        selected_bm = st.selectbox("Select Benchmark", ["None"] + bm_cols)
        if selected_bm == "None":
            selected_bm = None

    nav_series = get_nav_series(mfie or selected_fund, nav_df, master_df)
    bm_series = get_benchmark_series(selected_bm, bm_df) if selected_bm else None

    if nav_series is None or nav_series.empty:
        st.error(f"Could not find NAV data for **{selected_fund}**.")
        return

    st.markdown(
        f"**Data range:** {nav_series.index.min().date()} to {nav_series.index.max().date()} "
        f"| **{len(nav_series)} data points**"
    )

    st.markdown("### Absolute Returns")
    render_returns_table(
        compute_returns(nav_series),
        compute_returns(bm_series) if bm_series is not None else {},
        fund_label="Fund",
        bm_label="Benchmark"
    )

    st.markdown("### NAV vs Benchmark (Indexed to 100)")
    date_range = st.selectbox("Chart Period", ["1Y", "3Y", "5Y", "Max"], index=3, key="nav_range")
    nav_plot = slice_series_by_range(nav_series, date_range)
    bm_plot = slice_series_by_range(bm_series, date_range) if bm_series is not None else None
    render_nav_chart(nav_plot, bm_plot, selected_fund, selected_bm or "Benchmark")

    st.markdown("### Drawdown Analysis")
    render_drawdown_chart(nav_plot, bm_plot, selected_fund, selected_bm or "Benchmark")

    st.markdown("### Calendar Year Returns: Fund vs Benchmark")
    fund_cal = compute_calendar_returns(nav_series)
    bm_cal = compute_calendar_returns(bm_series) if bm_series is not None else {}
    cal_df = render_calendar_table(fund_cal, bm_cal, fund_label="Fund (%)", bm_label="Benchmark (%)")
    if cal_df is not None:
        render_calendar_bar_chart(cal_df, "Fund (%)", "Benchmark (%)", selected_bm)


# ------------------ PORTFOLIO VISUALISATION TAB ------------------ #
def render_portfolio_visualisation(df_all, master_df, bm_df, nav_df):
    st.markdown("## 🗂️ Look-Through")
    st.markdown("Enter your fund allocations below. Weights should sum to 100%.")

    all_schemes = sorted(df_all["scheme"].dropna().unique())

    if "pv_funds" not in st.session_state:
        st.session_state.pv_funds = [{"fund": all_schemes[0], "weight": 100.0}]

    def add_fund():
        st.session_state.pv_funds.append({"fund": all_schemes[0], "weight": 0.0})

    def remove_fund(idx):
        st.session_state.pv_funds.pop(idx)

    updated_funds = []
    for i, row in enumerate(st.session_state.pv_funds):
        cols = st.columns([4, 2, 1])
        with cols[0]:
            selected = st.selectbox(
                f"Fund {i + 1}", all_schemes,
                index=all_schemes.index(row["fund"]) if row["fund"] in all_schemes else 0,
                key=f"pv_fund_{i}"
            )
        with cols[1]:
            weight = st.number_input(
                "Weight (%)", min_value=0.0, max_value=100.0,
                value=float(row["weight"]), step=0.5, key=f"pv_weight_{i}"
            )
        with cols[2]:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("✕", key=f"pv_remove_{i}") and len(st.session_state.pv_funds) > 1:
                remove_fund(i)
                st.rerun()
        updated_funds.append({"fund": selected, "weight": weight})

    st.session_state.pv_funds = updated_funds
    st.button("➕ Add Fund", on_click=add_fund)

    total_w = sum(r["weight"] for r in st.session_state.pv_funds)
    if abs(total_w - 100) > 0.1:
        st.warning(f"⚠️ Weights sum to {total_w:.1f}%. Please adjust to 100%.")
    else:
        st.success(f"✅ Weights sum to {total_w:.1f}%")

    st.markdown("---")
    bm_cols = list(bm_df.columns) if bm_df is not None else []
    use_bm = st.checkbox("Add a benchmark for performance comparison", value=False)
    portfolio_bm = None
    if use_bm:
        if bm_cols:
            portfolio_bm = st.selectbox("Select Benchmark", bm_cols, key="pv_bm")
        else:
            st.info("Upload a Performance Excel file to enable benchmark selection.")

    if st.button("📊 Analyse Look-Through Portfolio", type="primary"):
        if abs(total_w - 100) > 0.1:
            st.error("Please make sure weights sum to 100% before analysing.")
            return

        # fund_weights stores raw % values, e.g. {"Fund A": 60.0, "Fund B": 40.0}
        fund_weights = {r["fund"]: r["weight"] for r in st.session_state.pv_funds}
        selected_funds = list(fund_weights.keys())

        # Build weighted holdings:
        # stock weight is already in % (e.g. 5.2%)
        # fund allocation is in % (e.g. 40%)
        # portfolio contribution = stock_weight% × (fund_allocation% / 100) → result still in %
        weighted_holdings = []
        for fund, fw in fund_weights.items():
            fund_data = df_all[df_all["scheme"] == fund].copy()
            fund_data = fund_data[fund_data["weight"] > 0].copy()
            fund_data["portfolio_weight"] = fund_data["weight"] * (fw / 100.0)
            weighted_holdings.append(fund_data)

        if not weighted_holdings:
            st.error("No holdings data found for selected funds.")
            return

        wh = pd.concat(weighted_holdings, ignore_index=True)

        # Aggregate stock weights across funds
        agg_stocks = wh.groupby("company")["portfolio_weight"].sum()

        # HHI: normalise to fractions first so HHI is always 0–1
        agg_stocks_norm = agg_stocks / agg_stocks.sum()
        hhi = (agg_stocks_norm ** 2).sum()
        diversification_score = round((1 - hhi) * 100, 1)

        st.markdown("---")

        # ---- SUMMARY METRICS ---- #
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Funds in Portfolio", len(selected_funds))
        c2.metric("Unique Stocks", agg_stocks.shape[0])
        c3.metric(
            "Diversification Score", f"{diversification_score}/100",
            help="100 = perfectly diversified. Based on Herfindahl-Hirschman Index of stock weights."
        )
        c4.metric("Largest Single Stock Exposure", f"{agg_stocks.max():.2f}%")

        st.markdown("---")

        # ---- FUND ALLOCATION PIE ---- #
        st.markdown("### Fund Allocation")
        fund_pie_df = pd.DataFrame([
            {"Fund": f, "Weight (%)": w} for f, w in fund_weights.items()
        ])
        fig_fpie = px.pie(fund_pie_df, names="Fund", values="Weight (%)",
                          title="Your Portfolio Allocation by Fund")
        st.plotly_chart(fig_fpie, use_container_width=True)

        # ---- MARKET CAP ---- #
        st.markdown("### Aggregate Market Cap Split")
        if "market_cap" in wh.columns:
            cap_agg = wh.groupby("market_cap")["portfolio_weight"].sum().reset_index()
            cap_agg.columns = ["Market Cap", "Weight (%)"]
            cap_agg["Weight (%)"] = cap_agg["Weight (%)"].round(2)
            col1, col2 = st.columns(2)
            with col1:
                fig_cap = px.pie(cap_agg, names="Market Cap", values="Weight (%)",
                                  title="Market Cap Allocation")
                st.plotly_chart(fig_cap, use_container_width=True)
            with col2:
                st.dataframe(cap_agg.sort_values("Weight (%)", ascending=False),
                             use_container_width=True, hide_index=True)

        # ---- SECTOR ALLOCATION ---- #
        st.markdown("### Aggregate Sector Allocation")
        if "sector" in wh.columns:
            sec_agg = wh.groupby("sector")["portfolio_weight"].sum().reset_index()
            sec_agg.columns = ["Sector", "Weight (%)"]
            sec_agg["Weight (%)"] = sec_agg["Weight (%)"].round(2)
            sec_agg = sec_agg.sort_values("Weight (%)", ascending=True)
            fig_sec = px.bar(sec_agg, x="Weight (%)", y="Sector", orientation="h",
                             text="Weight (%)", title="Sector Allocation")
            fig_sec.update_traces(texttemplate="%{text:.2f}%", marker_color="#3498db")
            fig_sec.update_layout(height=max(400, len(sec_agg) * 28))
            st.plotly_chart(fig_sec, use_container_width=True)

        # ---- SECTOR DRILLDOWN SUNBURST ---- #
        if all(c in wh.columns for c in ["macro_sector", "sector", "industry", "basic_industry"]):
            st.markdown("### Sector Drilldown")
            sun = wh.groupby(
                ["macro_sector", "sector", "industry", "basic_industry"], as_index=False
            )["portfolio_weight"].sum()
            fig_sun = px.sunburst(
                sun, path=["macro_sector", "sector", "industry", "basic_industry"],
                values="portfolio_weight", title="Portfolio Drilldown"
            )
            st.plotly_chart(fig_sun, use_container_width=True)

        # ---- TOP HOLDINGS ---- #
        st.markdown("### Top Holdings (Consolidated)")
        top_holdings = agg_stocks.reset_index()
        top_holdings.columns = ["Company", "Portfolio Weight (%)"]
        top_holdings = top_holdings.sort_values("Portfolio Weight (%)", ascending=False)
        top_holdings["Portfolio Weight (%)"] = top_holdings["Portfolio Weight (%)"].round(3)

        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Top 10 Stocks**")
            st.dataframe(top_holdings.head(10), use_container_width=True, hide_index=True)
        with col2:
            fig_top = px.bar(
                top_holdings.head(15).sort_values("Portfolio Weight (%)"),
                x="Portfolio Weight (%)", y="Company", orientation="h",
                title="Top 15 Holdings"
            )
            fig_top.update_traces(marker_color="#2ecc71")
            st.plotly_chart(fig_top, use_container_width=True)

        # ---- STOCK-LEVEL FUND OVERLAP ---- #
        st.markdown("### Stock Overlap Across Funds")
        if len(selected_funds) > 1:
            overlap = calculate_overlap(df_all, selected_funds)
            fig_heat = px.imshow(
                overlap.values.astype(float),
                x=overlap.columns.tolist(),
                y=overlap.index.tolist(),
                text_auto=".1f",
                color_continuous_scale="Blues",
                title="Portfolio Overlap Matrix (% shared holdings by weight)"
            )
            st.plotly_chart(fig_heat, use_container_width=True)
        else:
            st.info("Add more than one fund to see overlap analysis.")

        # ---- PERFORMANCE ---- #
        st.markdown("### Portfolio Performance")

        if nav_df is None or master_df is None:
            st.info("Upload a Performance Excel file to see portfolio performance.")
        else:
            # Build blended NAV
            # Weights stored as %, convert to decimal fractions for NAV blending
            nav_series_list = []
            for fund, fw in fund_weights.items():
                mfie = match_portfolio_scheme_to_mfie(fund, master_df)
                ns = get_nav_series(mfie or fund, nav_df, master_df)
                if ns is not None and not ns.empty:
                    nav_series_list.append((ns, fw / 100.0))
                else:
                    st.warning(f"Could not find NAV for **{fund}** — excluded from performance.")

            if nav_series_list:
                all_nav_series = [s.rename(f"f{i}") for i, (s, _) in enumerate(nav_series_list)]
                weights_list = [w for _, w in nav_series_list]

                combined = pd.concat(all_nav_series, axis=1).sort_index().dropna()

                if combined.empty:
                    st.warning("No overlapping dates found across selected fund NAVs.")
                else:
                    # Normalise each NAV to 100 at the common start, then weight-blend
                    normalised = combined / combined.iloc[0] * 100
                    weight_arr = np.array(weights_list)
                    weight_arr = weight_arr / weight_arr.sum()  # renormalise if any fund was excluded
                    portfolio_nav = (normalised * weight_arr).sum(axis=1)

                    bm_series_pv = get_benchmark_series(portfolio_bm, bm_df) if portfolio_bm else None

                    st.markdown("#### Portfolio NAV (Indexed to 100)")
                    date_range_pv = st.selectbox(
                        "Chart Period", ["1Y", "3Y", "5Y", "Max"], index=3, key="pv_range"
                    )
                    pnav_plot = slice_series_by_range(portfolio_nav, date_range_pv)
                    bm_plot_pv = slice_series_by_range(bm_series_pv, date_range_pv) if bm_series_pv is not None else None

                    render_nav_chart(pnav_plot, bm_plot_pv, "Look-Through", portfolio_bm or "Benchmark")

                    st.markdown("#### Portfolio Returns")
                    render_returns_table(
                        compute_returns(portfolio_nav),
                        compute_returns(bm_series_pv) if bm_series_pv is not None else {},
                        fund_label="Portfolio",
                        bm_label="Benchmark"
                    )

                    st.markdown("#### Portfolio Drawdown")
                    render_drawdown_chart(pnav_plot, bm_plot_pv, "Look-Through", portfolio_bm or "Benchmark")

                    st.markdown("#### Calendar Year Returns")
                    port_cal = compute_calendar_returns(portfolio_nav)
                    bm_cal_pv = compute_calendar_returns(bm_series_pv) if bm_series_pv is not None else {}
                    cal_df_pv = render_calendar_table(
                        port_cal, bm_cal_pv,
                        fund_label="Portfolio (%)", bm_label="Benchmark (%)"
                    )
                    if cal_df_pv is not None:
                        render_calendar_bar_chart(
                            cal_df_pv, "Portfolio (%)", "Benchmark (%)", portfolio_bm
                        )

        # ---- DOWNLOAD ---- #
        st.markdown("---")
        st.markdown("### Download Portfolio Data")
        st.download_button(
            "📥 Download Consolidated Holdings CSV",
            export_csv(top_holdings),
            "my_portfolio_holdings.csv",
            "text/csv"
        )


# ------------------ TABS ------------------ #
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "Sector Screener",
    "Stock Screener",
    "Fund Deep Dive",
    "Fund Comparison",
    "Performance",
    "Look-Through"
])

with tab1:
    macro = st.selectbox("Macro Sector", sorted(df["macro_sector"].dropna().unique()))
    temp = df[df["macro_sector"] == macro]

    sector = st.selectbox("Sector", ["All"] + sorted(temp["sector"].dropna().unique()))
    if sector != "All":
        temp = temp[temp["sector"] == sector]

    industry = st.selectbox("Industry", ["All"] + sorted(temp["industry"].dropna().unique()))
    if industry != "All":
        temp = temp[temp["industry"] == industry]

    basic = st.selectbox("Basic Industry", ["All"] + sorted(temp["basic_industry"].dropna().unique()))
    if basic != "All":
        temp = temp[temp["basic_industry"] == basic]

    if st.button("Run Sector Screener"):
        result = build_fund_table(temp)
        st.dataframe(result, use_container_width=True, hide_index=True)
        st.download_button("Download CSV", export_csv(result), "sector.csv")

with tab2:
    stocks = st.multiselect("Select Stocks", sorted(df["company"].dropna().unique()))

    if st.button("Run Stock Screener"):
        if stocks:
            pattern = "|".join(re.escape(s) for s in stocks)
            filtered = df[df["company"].str.contains(pattern, case=False, na=False)]
            result = build_fund_table(filtered)
            st.dataframe(result, use_container_width=True, hide_index=True)
            st.download_button("Download CSV", export_csv(result), "stock.csv")
        else:
            st.warning("Select at least one stock.")

with tab3:
    fund = st.selectbox("Select Fund", sorted(df["scheme"].dropna().unique()))
    if fund:
        render_fund_deep_dive(df, fund)

with tab4:
    funds = st.multiselect("Select Funds", sorted(df["scheme"].dropna().unique()))

    if st.button("Run Comparison"):
        if len(funds) >= 2:
            st.markdown("### Overlap Matrix")
            overlap = calculate_overlap(df, funds)
            st.dataframe(overlap, use_container_width=True)

            st.markdown("### Sector Cross-Fund")
            level = st.selectbox("Select Level", ["macro_sector", "sector", "industry"])
            cross = sector_cross(df, funds, level)
            st.dataframe(cross, use_container_width=True)
        else:
            st.warning("Select at least 2 funds.")

with tab5:
    render_performance_tab(df, master, bm, nav)

with tab6:
    render_portfolio_visualisation(df, master, bm, nav)
