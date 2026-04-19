import streamlit as st
import pandas as pd
import plotly.express as px
import re

st.set_page_config(page_title="Portfolio Analytics", layout="wide")

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
        "Issuer Name": "issuer",
        "Macro Economic Sector": "macro_sector",
        "Sector": "sector",
        "Industry": "industry",
        "Basic Industry": "basic_industry",
        "% of Net Assets": "weight",
        "Market Cap": "market_cap",
        "AMC Name": "amc",
    }
    df = df.rename(columns=rename_map)

    if "weight" in df.columns:
        df["weight"] = pd.to_numeric(df["weight"], errors="coerce").fillna(0)

    for col in ["scheme", "company", "sector", "industry", "basic_industry", "macro_sector", "market_cap", "amc"]:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()

    return df

# Stop until file uploaded
if uploaded_file is not None:
    df = load_data(uploaded_file)
    st.success("File uploaded successfully ✅")
else:
    st.info("Please upload an Excel file to begin.")
    st.stop()

# ------------------ APP START ------------------ #
st.title("📊 Portfolio Analytics")

# ------------------ FUNCTIONS ------------------ #
def sector_filter(df_in, macro, sector="All", industry="All", basic="All"):
    f = df_in[df_in["macro_sector"] == macro].copy()
    if sector != "All":
        f = f[f["sector"] == sector]
    if industry != "All":
        f = f[f["industry"] == industry]
    if basic != "All":
        f = f[f["basic_industry"] == basic]
    return f

def stock_filter(df_in, stocks):
    if not stocks:
        return df_in.iloc[0:0].copy()
    pattern = "|".join(re.escape(s) for s in stocks)
    return df_in[df_in["company"].str.contains(pattern, case=False, na=False)].copy()

def top_funds(df_in):
    if df_in.empty:
        return pd.DataFrame(columns=["scheme", "weight"])
    return (
        df_in.groupby("scheme", as_index=False)["weight"]
        .sum()
        .sort_values("weight", ascending=False)
        .reset_index(drop=True)
    )

def get_fund_df(df_all, scheme):
    return df_all[df_all["scheme"] == scheme].copy()

def fund_metrics(fund_df):
    eq = fund_df[fund_df["weight"] > 0].copy()
    top10 = (
        eq.groupby("company", as_index=False)["weight"]
        .sum()
        .sort_values("weight", ascending=False)
        .head(10)
    )
    top5 = top10.head(5)["weight"].sum()
    top10_sum = top10["weight"].sum()
    stocks = eq["company"].nunique()
    total_weight = eq["weight"].sum()
    return stocks, total_weight, top5, top10_sum, eq

def export_csv(df_in):
    return df_in.to_csv(index=False).encode("utf-8")

def fig_to_png_bytes(fig):
    return fig.to_image(format="png")

def render_downloads(table_df, fig=None, table_name="table", chart_name="chart"):
    c1, c2 = st.columns(2)
    with c1:
        st.download_button(f"Download {table_name} CSV", export_csv(table_df), f"{table_name}.csv", "text/csv")
    with c2:
        if fig is not None:
            st.download_button(f"Download {chart_name} PNG", fig_to_png_bytes(fig), f"{chart_name}.png", "image/png")

def render_fund_deep_dive(df_all, scheme):
    fund_df = get_fund_df(df_all, scheme)
    eq = fund_df[fund_df["weight"] > 0].copy()

    stocks, total_weight, top5, top10, eq = fund_metrics(fund_df)

    st.markdown(f"## {scheme}")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Stocks", int(stocks))
    c2.metric("Total Weight", f"{total_weight:.2f}%")
    c3.metric("Top 5 Concentration", f"{top5:.2f}%")
    c4.metric("Top 10 Concentration", f"{top10:.2f}%")

    # Sector
    st.markdown("### Sector Allocation")
    sec = eq.groupby("sector", as_index=False)["weight"].sum().sort_values("weight")
    if not sec.empty:
        fig = px.bar(sec, x="weight", y="sector", orientation="h", text="weight")
        st.plotly_chart(fig, use_container_width=True)
        render_downloads(sec, fig, "sector_allocation", "sector_chart")

    # Market Cap
    st.markdown("### Market Cap Mix")
    cap = eq.groupby("market_cap", as_index=False)["weight"].sum()
    st.dataframe(cap, use_container_width=True, hide_index=True)

    # Top holdings
    st.markdown("### Top Holdings")
    top = (
        eq.groupby("company", as_index=False)["weight"]
        .sum()
        .sort_values("weight", ascending=False)
        .head(10)
    )
    st.dataframe(top, use_container_width=True, hide_index=True)

# ------------------ SESSION STATE ------------------ #
def init_state():
    if "sector_ran" not in st.session_state:
        st.session_state.sector_ran = False
        st.session_state.sector_result = pd.DataFrame()
        st.session_state.stock_ran = False
        st.session_state.stock_result = pd.DataFrame()

init_state()

# ------------------ TABS ------------------ #
tab1, tab2, tab3 = st.tabs(["Sector Screener", "Stock Screener", "Fund Deep Dive"])

# -------- Sector Screener -------- #
with tab1:
    macro_options = sorted(df["macro_sector"].dropna().unique())
    macro = st.selectbox("Macro Sector", macro_options)

    filtered = df[df["macro_sector"] == macro]

    sector = st.selectbox("Sector", ["All"] + sorted(filtered["sector"].dropna().unique()))
    if sector != "All":
        filtered = filtered[filtered["sector"] == sector]

    top_n = st.slider("Top N", 5, 50, 20)

    if st.button("Run Sector Screener"):
        result = top_funds(filtered).head(top_n)
        st.session_state.sector_result = result
        st.session_state.sector_ran = True

    if st.session_state.sector_ran:
        st.dataframe(st.session_state.sector_result, use_container_width=True)

# -------- Stock Screener -------- #
with tab2:
    stocks = sorted(df["company"].dropna().unique())
    selected = st.multiselect("Select Stocks", stocks)

    if st.button("Run Stock Screener"):
        result = top_funds(stock_filter(df, selected))
        st.session_state.stock_result = result
        st.session_state.stock_ran = True

    if st.session_state.stock_ran:
        st.dataframe(st.session_state.stock_result, use_container_width=True)

# -------- Deep Dive -------- #
with tab3:
    funds = sorted(df["scheme"].dropna().unique())
    selected_fund = st.selectbox("Select Fund", funds)

    if selected_fund:
        render_fund_deep_dive(df, selected_fund)