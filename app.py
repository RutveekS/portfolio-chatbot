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

    # --- Master Categorisation ---
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

    # --- Benchmark Returns ---
    bm = xl.parse("BM1")
    bm.columns = bm.columns.str.strip()
    bm = bm.rename(columns={bm.columns[0]: "date"})
    bm["date"] = pd.to_datetime(bm["date"], errors="coerce")
    bm = bm.dropna(subset=["date"]).sort_values("date").set_index("date")
    bm = bm.apply(pd.to_numeric, errors="coerce")

    # --- NAV Data ---
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
def export_csv(df):
    return df.to_csv(index=False).encode("utf-8")

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

def calculate_overlap(df, funds):
    pivot = df[df["scheme"].isin(funds)].pivot_table(
        index="company", columns="scheme", values="weight", aggfunc="sum"
    ).fillna(0)
    overlap = pd.DataFrame(index=funds, columns=funds)
    for f1 in funds:
        for f2 in funds:
            overlap.loc[f1, f2] = (pivot[[f1, f2]].min(axis=1)).sum()
    return overlap.astype(float).round(2)

def sector_cross(df, funds, level):
    temp = df[df["scheme"].isin(funds)]
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
    periods = {"1M": 30, "3M": 3 * 30, "6M": 6 * 30, "1Y": 365, "3Y": 3 * 365, "5Y": 5 * 365}
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
    years = series.index.year.unique()
    cal = {}
    for yr in sorted(years):
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

    if master is not None:
        mfie = match_portfolio_scheme_to_mfie(scheme, master)
        if mfie:
            fm_rows = master[master["mfie_name"] == mfie][
                ["fund_manager", "start_date", "end_date", "categorisation"]
            ].copy()
            if not fm_rows.empty:
                st.markdown("### Historical Fund Managers")
                fm_rows = fm_rows.rename(columns={
                    "fund_manager": "Fund Manager",
                    "start_date": "Start Date",
                    "end_date": "End Date",
                    "categorisation": "Categorisation"
                })
                fm_rows["Start Date"] = pd.to_datetime(fm_rows["Start Date"], errors="coerce").dt.strftime("%b %Y")
                fm_rows["End Date"] = pd.to_datetime(fm_rows["End Date"], errors="coerce").dt.strftime("%b %Y")
                fm_rows["End Date"] = fm_rows["End Date"].fillna("Present")
                st.dataframe(fm_rows, use_container_width=True, hide_index=True)

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

    st.markdown(f"**Data range:** {nav_series.index.min().date()} to {nav_series.index.max().date()} | **{len(nav_series)} data points**")

    st.markdown("### Absolute Returns")
    fund_rets = compute_returns(nav_series)
    bm_rets = compute_returns(bm_series) if bm_series is not None else {}

    periods = ["1M", "3M", "6M", "1Y", "3Y", "5Y"]
    annualised = {"3Y", "5Y"}

    ret_rows = []
    for p in periods:
        f_val = fund_rets.get(p)
        b_val = bm_rets.get(p)
        alpha = (f_val - b_val) if (f_val is not None and b_val is not None) else None
        ret_rows.append({
            "Period": f"{p} {'(Ann.)' if p in annualised else ''}",
            "Fund": f"{f_val*100:.2f}%" if f_val is not None else "N/A",
            "Benchmark": f"{b_val*100:.2f}%" if b_val is not None else "N/A",
            "Alpha": f"{alpha*100:.2f}%" if alpha is not None else "N/A",
        })

    ret_df = pd.DataFrame(ret_rows)

    def style_returns(val):
        if val == "N/A":
            return ""
        try:
            num = float(val.replace("%", ""))
            color = "#2ecc71" if num >= 0 else "#e74c3c"
            return f"color: {color}; font-weight: bold"
        except Exception:
            return ""

    styled = ret_df.style.applymap(style_returns, subset=["Fund", "Benchmark", "Alpha"])
    st.dataframe(styled, use_container_width=True, hide_index=True)

    st.markdown("### NAV vs Benchmark (Indexed to 100)")
    date_range = st.selectbox("Chart Period", ["1Y", "3Y", "5Y", "Max"], index=3, key="nav_range")
    end_date = nav_series.index.max()
    range_map = {"1Y": 365, "3Y": 3 * 365, "5Y": 5 * 365, "Max": None}
    days_back = range_map[date_range]
    if days_back:
        start_cut = end_date - pd.Timedelta(days=days_back)
        nav_plot = nav_series[nav_series.index >= start_cut]
        bm_plot = bm_series[bm_series.index >= start_cut] if bm_series is not None else None
    else:
        nav_plot = nav_series
        bm_plot = bm_series

    fig_nav = go.Figure()
    nav_idx = nav_plot / nav_plot.iloc[0] * 100
    fig_nav.add_trace(go.Scatter(x=nav_idx.index, y=nav_idx.values, name=selected_fund, line=dict(width=2)))

    if bm_plot is not None and not bm_plot.empty:
        common_start = max(nav_plot.index[0], bm_plot.index[0])
        bm_trimmed = bm_plot[bm_plot.index >= common_start]
        if not bm_trimmed.empty:
            bm_idx = bm_trimmed / bm_trimmed.iloc[0] * 100
            fig_nav.add_trace(go.Scatter(x=bm_idx.index, y=bm_idx.values, name=selected_bm,
                                          line=dict(width=2, dash="dash")))

    fig_nav.update_layout(yaxis_title="Indexed (Base=100)", xaxis_title="Date", hovermode="x unified")
    st.plotly_chart(fig_nav, use_container_width=True)

    st.markdown("### Drawdown Analysis")
    dd = compute_drawdown(nav_plot)
    bm_dd = compute_drawdown(bm_plot) if bm_plot is not None and not bm_plot.empty else None

    fig_dd = go.Figure()
    if dd is not None:
        fig_dd.add_trace(go.Scatter(x=dd.index, y=dd.values, fill="tozeroy",
                                     name=f"{selected_fund} Drawdown",
                                     line=dict(color="#e74c3c", width=1)))
    if bm_dd is not None:
        fig_dd.add_trace(go.Scatter(x=bm_dd.index, y=bm_dd.values,
                                     name=f"{selected_bm} Drawdown",
                                     line=dict(color="#3498db", width=1, dash="dash")))

    fig_dd.update_layout(yaxis_title="Drawdown (%)", xaxis_title="Date", hovermode="x unified")
    st.plotly_chart(fig_dd, use_container_width=True)

    if dd is not None:
        max_dd = dd.min()
        max_dd_date = dd.idxmin()
        c1, c2 = st.columns(2)
        c1.metric("Max Drawdown (Fund)", f"{max_dd:.2f}%")
        c2.metric("Date of Max Drawdown", str(max_dd_date.date()))

    st.markdown("### Calendar Year Returns: Fund vs Benchmark")
    fund_cal = compute_calendar_returns(nav_series)
    bm_cal = compute_calendar_returns(bm_series) if bm_series is not None else {}

    all_years = sorted(set(list(fund_cal.keys()) + list(bm_cal.keys())))
    if not all_years:
        st.info("Not enough data for calendar year returns.")
        return

    cal_rows = []
    for yr in all_years:
        f = fund_cal.get(yr)
        b = bm_cal.get(yr)
        alpha = round(f - b, 2) if (f is not None and b is not None) else None
        cal_rows.append({
            "Year": yr,
            "Fund (%)": f,
            "Benchmark (%)": b,
            "Alpha (%)": alpha
        })
    cal_df = pd.DataFrame(cal_rows)

    fig_cal = go.Figure()
    fig_cal.add_trace(go.Bar(
        x=cal_df["Year"], y=cal_df["Fund (%)"],
        name=selected_fund, marker_color="#3498db"
    ))
    if bm_series is not None:
        fig_cal.add_trace(go.Bar(
            x=cal_df["Year"], y=cal_df["Benchmark (%)"],
            name=selected_bm or "Benchmark", marker_color="#95a5a6"
        ))

    fig_cal.update_layout(
        barmode="group", yaxis_title="Return (%)",
        xaxis_title="Year", hovermode="x unified"
    )
    st.plotly_chart(fig_cal, use_container_width=True)

    def color_cal(val):
        if val is None or (isinstance(val, float) and np.isnan(val)):
            return ""
        try:
            color = "#2ecc71" if float(val) >= 0 else "#e74c3c"
            return f"color: {color}; font-weight: bold"
        except Exception:
            return ""

    styled_cal = cal_df.style.applymap(color_cal, subset=["Fund (%)", "Benchmark (%)", "Alpha (%)"])
    st.dataframe(styled_cal, use_container_width=True, hide_index=True)


# ------------------ TABS ------------------ #
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "Sector Screener",
    "Stock Screener",
    "Fund Deep Dive",
    "Fund Comparison",
    "Performance"
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
