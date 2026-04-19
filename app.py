import streamlit as st
import pandas as pd
import plotly.express as px
import re

st.set_page_config(page_title="Funds Analytics", layout="wide")

# ------------------ FILE UPLOAD ------------------ #
uploaded_file = st.file_uploader("📂 Upload Portfolio Excel", type=["xlsx"])

@st.cache_data
def load_data(file):
    df = pd.read_excel(file)
    df.columns = df.columns.str.strip()

    rename_map = {
        "Fund Type": "fund_type",
        "Scheme Name": "scheme",
        "Company Name": "company",
        "Macro Economic Sector": "macro_sector",
        "Sector": "sector",
        "Industry": "industry",
        "Basic Industry": "basic_industry",
        "% of Net Assets": "weight",
        "Market Cap": "market_cap",
    }
    df = df.rename(columns=rename_map)

    df["weight"] = pd.to_numeric(df["weight"], errors="coerce").fillna(0)

    for col in ["scheme", "company", "sector", "industry", "basic_industry", "market_cap", "fund_type"]:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()

    return df

if uploaded_file is None:
    st.info("Please upload an Excel file to begin.")
    st.stop()

df = load_data(uploaded_file)

st.title("📊 Funds Analytics Dashboard")
st.caption("Upload your monthly portfolio file to analyze funds, sectors, and holdings")

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

# ------------------ FUND DEEP DIVE ------------------ #
def render_fund_deep_dive(df_all, scheme):
    fund_df = df_all[df_all["scheme"] == scheme].copy()

    st.markdown(f"## {scheme}")

    total_weight = fund_df["weight"].sum()
    stocks = fund_df["company"].nunique()

    c1, c2 = st.columns(2)
    c1.metric("Total Weight", f"{total_weight:.2f}%")
    c2.metric("Number of Stocks", stocks)

    # Market Cap Pie
    st.markdown("### Market Cap Allocation")
    cap = fund_df.groupby("market_cap", as_index=False)["weight"].sum()

    if not cap.empty:
        fig = px.pie(cap, names="market_cap", values="weight")
        st.plotly_chart(fig, use_container_width=True)

    # Top 10 holdings
    st.markdown("### Top 10 Holdings")
    top10 = (
        fund_df.groupby("company", as_index=False)["weight"]
        .sum()
        .sort_values("weight", ascending=False)
        .head(10)
    )

    st.dataframe(top10, use_container_width=True, hide_index=True)

    # 🔥 NEW: Top 10 sum
    top10_sum = top10["weight"].sum()
    st.metric("Top 10 Concentration", f"{top10_sum:.2f}%")

    # Full portfolio download
    st.markdown("### Full Portfolio")
    full = fund_df[["company", "weight", "market_cap", "sector"]].copy()

    st.download_button(
        "Download Full Portfolio CSV",
        export_csv(full),
        f"{scheme}_portfolio.csv",
        "text/csv"
    )

# ------------------ TABS ------------------ #
tab1, tab2, tab3 = st.tabs(["Sector Screener", "Stock Screener", "Fund Deep Dive"])

# -------- Sector Screener -------- #
with tab1:
    st.markdown("### Sector Screener")

    macro = st.selectbox("Macro Sector", sorted(df["macro_sector"].dropna().unique()))
    temp = df[df["macro_sector"] == macro]

    sector = st.selectbox("Sector", ["All"] + sorted(temp["sector"].dropna().unique()))
    if sector != "All":
        temp = temp[temp["sector"] == sector]

    # NEW: Industry
    industry = st.selectbox("Industry", ["All"] + sorted(temp["industry"].dropna().unique()))
    if industry != "All":
        temp = temp[temp["industry"] == industry]

    # NEW: Basic Industry
    basic = st.selectbox("Basic Industry", ["All"] + sorted(temp["basic_industry"].dropna().unique()))
    if basic != "All":
        temp = temp[temp["basic_industry"] == basic]

    if st.button("Run Sector Screener"):
        result = build_fund_table(temp)
        st.dataframe(result, use_container_width=True, hide_index=True)

        st.download_button(
            "Download Results CSV",
            export_csv(result),
            "sector_screener.csv",
            "text/csv"
        )

# -------- Stock Screener -------- #
with tab2:
    st.markdown("### Stock Screener")

    stocks = st.multiselect("Select Stocks", sorted(df["company"].dropna().unique()))

    if st.button("Run Stock Screener"):
        if stocks:
            pattern = "|".join(re.escape(s) for s in stocks)
            filtered = df[df["company"].str.contains(pattern, case=False, na=False)]

            result = build_fund_table(filtered)

            st.dataframe(result, use_container_width=True, hide_index=True)

            st.download_button(
                "Download Results CSV",
                export_csv(result),
                "stock_screener.csv",
                "text/csv"
            )
        else:
            st.warning("Select at least one stock.")

# -------- Fund Deep Dive -------- #
with tab3:
    st.markdown("### Fund Deep Dive")

    fund = st.selectbox("Select Fund", sorted(df["scheme"].dropna().unique()))
    if fund:
        render_fund_deep_dive(df, fund)
