import streamlit as st
import pandas as pd
import geopandas as gpd
import matplotlib.pyplot as plt
from pathlib import Path
import folium
from streamlit_folium import st_folium

# ------------------------------------------------
# 0. BASIC CONFIG
# ------------------------------------------------
st.set_page_config(
    page_title="Soybean Acreage Stability Dashboard",
    layout="wide"
)

st.title("🌾 Soybean Acreage Stability & Risk Dashboard")

st.markdown(
    """
    This dashboard summarises **district-wise soybean acreage stability, 
    model confidence (R²)** and **2025 predicted acreage** for your states.
    """
)

# 🔤 Slightly increase normal text size (keep headings as-is)
st.markdown(
    """
    <style>
    p, li {
        font-size: 1.05rem !important;
    }
    </style>
    """,
    unsafe_allow_html=True
)

# ------------------------------------------------
# 1. PATH SETTINGS  (EDIT THESE FOR YOUR SYSTEM)
# ------------------------------------------------
DEFAULT_CSV = r"District_Acreage_Variation_R2_2025_f.csv"
DEFAULT_SHP = r"3states.shp"

st.sidebar.header("🔧 Data Inputs")

csv_path = st.sidebar.text_input("District stability CSV path:", DEFAULT_CSV)
shp_path = st.sidebar.text_input("Shapefile path (multi-state districts):", DEFAULT_SHP)

# Column names in your files (change if different)
district_col_csv = "District"
state_col_csv    = "State"   # if not present, we’ll only use district

district_col_shp = "District"
state_col_shp    = "State"

# Optional: column for last year's acreage (2024)
acreage_2024_col = "Acreage_2024"   # change if your column name is different

# ------------------------------------------------
# 2. LOAD DATA
# ------------------------------------------------
@st.cache_data
def load_stability_table(path):
    df = pd.read_csv(path)
    # Ensure expected columns exist
    if district_col_csv not in df.columns:
        raise ValueError(f"Column '{district_col_csv}' not found in CSV")
    if "Acreage_Stability_Class" not in df.columns:
        raise ValueError("Column 'Acreage_Stability_Class' not found in CSV")
    if "Predicted_2025_Acreage" not in df.columns:
        raise ValueError("Column 'Predicted_2025_Acreage' not found in CSV")

    # Create join key
    df["District_key"] = df[district_col_csv].astype(str).str.upper().str.strip()
    return df

@st.cache_data
def load_shapefile(path):
    gdf = gpd.read_file(path)
    if district_col_shp not in gdf.columns:
        raise ValueError(f"Column '{district_col_shp}' not found in shapefile")
    # join key
    gdf["District_key"] = gdf[district_col_shp].astype(str).str.upper().str.strip()
    return gdf

try:
    stab_df = load_stability_table(csv_path)
    gdf = load_shapefile(shp_path)
except Exception as e:
    st.error(f"Error loading data: {e}")
    st.stop()

# Try to use State from CSV, else from shapefile
if state_col_csv in stab_df.columns:
    stab_df[state_col_csv] = stab_df[state_col_csv].astype(str).str.strip()
elif state_col_shp in gdf.columns:
    # we will pull state info from shapefile after join
    pass

# ------------------------------------------------
# 3. JOIN STABILITY → GEOMETRY
# ------------------------------------------------
gdf_join = gdf.merge(
    stab_df,
    on="District_key",
    how="left",
    suffixes=("", "_stab")
)

# If State is missing in stab_df, use shapefile's
if state_col_csv not in stab_df.columns and state_col_shp in gdf_join.columns:
    gdf_join[state_col_csv] = gdf_join[state_col_shp]

# Get list of states available
if state_col_csv in gdf_join.columns:
    state_list = sorted(gdf_join[state_col_csv].dropna().unique())
else:
    state_list = ["All"]

# ------------------------------------------------
# 4. SIDEBAR FILTERS
# ------------------------------------------------
st.sidebar.header("📌 Filters")

selected_state_filter = st.sidebar.selectbox(
    "Select State:",
    options=["All"] + state_list,
    index=0
)

stability_classes = [
    "Stable Acreage",
    "Moderately Variable",
    "Highly Volatile / Crop Switching Likely",
    "Marginal Acreage (Statistically Unstable)"
]
stab_opts = st.sidebar.multiselect(
    "Filter by Stability Class:",
    options=stability_classes,
    default=stability_classes
)

# 🔴 Removed R² filter – as requested

# ------------------------------------------------
# 5. APPLY FILTERS
# ------------------------------------------------
df_view = gdf_join.copy()

if selected_state_filter != "All" and state_col_csv in df_view.columns:
    df_view = df_view[df_view[state_col_csv] == selected_state_filter]

if stab_opts:
    df_view = df_view[df_view["Acreage_Stability_Class"].isin(stab_opts)]

# No R² filtering now

if df_view.empty:
    st.warning("No districts match the selected filters.")
    st.stop()

# ------------------------------------------------
# 6. COLOR MAPPING FOR STABILITY CLASS
# ------------------------------------------------
def classify_color(stab_class: str) -> str:
    if pd.isna(stab_class):
        return "#CCCCCC"   # Grey - No Data
    if "Marginal Acreage" in stab_class:
        return "#FF0000"   # Red
    if "Highly Volatile" in stab_class:
        return "#FF7F00"   # Orange
    if "Moderately Variable" in stab_class:
        return "#FFFF00"   # Yellow
    if "Stable Acreage" in stab_class:
        return "#00A000"   # Green
    return "#CCCCCC"

df_view["stab_color"] = df_view["Acreage_Stability_Class"].apply(classify_color)

# ------------------------------------------------
# 7. SUMMARY KPIs
# ------------------------------------------------
total_pred_2025 = df_view["Predicted_2025_Acreage"].sum(skipna=True)

if "Mean_Acreage" in df_view.columns:
    base_area = df_view["Mean_Acreage"].sum(skipna=True)
    delta_pct = ((total_pred_2025 - base_area) / base_area * 100) if base_area > 0 else None
else:
    base_area = None
    delta_pct = None

col1, col2, col3 = st.columns(3)
with col1:
    st.metric("Total Predicted 2025 Acreage (Lakh ha)", f"{total_pred_2025:.2f}")
with col2:
    if base_area is not None and delta_pct is not None:
        st.metric("Total Mean Acreage (Historical)", f"{base_area:.2f}")
with col3:
    if delta_pct is not None:
        st.metric("Δ 2025 vs Mean (%)", f"{delta_pct:.1f}%")

# ------------------------------------------------
# 8. MAP (LEFT) + DISTRICT DETAIL (RIGHT)
# ------------------------------------------------
st.subheader("🗺️ Acreage Stability Map & District Insight")

map_col, detail_col = st.columns([1.4, 1])

# ---------- MAP (Folium) ----------
with map_col:
    # center map on filtered districts
    bounds = df_view.total_bounds  # [minx, miny, maxx, maxy]
    center_lat = (bounds[1] + bounds[3]) / 2
    center_lon = (bounds[0] + bounds[2]) / 2

    m = folium.Map(location=[center_lat, center_lon],
                   zoom_start=6,
                   tiles="cartodbpositron")

    def style_fn(feature):
        stab = feature["properties"].get("Acreage_Stability_Class")
        color = classify_color(stab)
        return {
            "fillColor": color,
            "color": "black",
            "weight": 0.5,
            "fillOpacity": 0.7,
        }

    gj = folium.GeoJson(
        data=df_view.to_json(),
        style_function=style_fn,
        highlight_function=lambda x: {"weight": 3, "color": "blue"},
        tooltip=folium.GeoJsonTooltip(
            fields=[district_col_csv, state_col_csv, "Acreage_Stability_Class"],
            aliases=["District", "State", "Stability"],
            sticky=False
        )
    )
    gj.add_to(m)

    map_data = st_folium(m, width="100%", height=550, key="soy_map")

# ---------- DETERMINE SELECTED DISTRICT FROM MAP CLICK ----------
all_districts = sorted(df_view[district_col_csv].dropna().unique())

clicked_district = None
if map_data:
    clicked_props = None
    if map_data.get("last_active_drawing"):
        clicked_props = map_data["last_active_drawing"].get("properties", {})
    elif map_data.get("last_object_clicked"):
        clicked_props = map_data["last_object_clicked"].get("properties", {})

    if clicked_props:
        clicked_district = clicked_props.get(district_col_csv)

# Fallback if nothing clicked yet
if "selected_district" not in st.session_state:
    st.session_state["selected_district"] = all_districts[0]

if clicked_district:
    st.session_state["selected_district"] = clicked_district

selected_district = st.session_state["selected_district"]

# Make sure selected district is still in filtered view
if selected_district not in all_districts:
    selected_district = all_districts[0]
    st.session_state["selected_district"] = selected_district

drow = df_view[df_view[district_col_csv] == selected_district].iloc[0]

# ---------- DISTRICT DETAIL + BAR CHART ON RIGHT ----------
with detail_col:
    st.markdown(f"### 🔍 {selected_district}")

    colA, colB = st.columns(2)

    with colA:
        st.markdown(f"**State:** {drow.get(state_col_csv, 'NA')}")
        st.markdown(f"**Stability Class:** {drow['Acreage_Stability_Class']}")
        if "CV(%)" in drow:
            st.markdown(f"**Coefficient of Variation (CV):** {drow['CV(%)']:.2f}%")
        if "Trend_Slope" in drow:
            st.markdown(
                f"**Trend Slope:** {drow['Trend_Slope']:.4f} Lakh ha / year "
                f"({'⬆️ increasing' if drow['Trend_Slope']>0 else '⬇️ decreasing' if drow['Trend_Slope']<0 else 'flat'})"
            )
        if "R2" in drow and not pd.isna(drow["R2"]):
            st.markdown(f"**Model R² (fit):** {drow['R2']:.3f}")

    with colB:
        mean_ac = drow["Mean_Acreage"] if "Mean_Acreage" in drow else None
        pred25 = drow["Predicted_2025_Acreage"]

        st.markdown("**Acreage Comparison (Lakh ha)**")
        st.write(f"- Historical Mean: **{mean_ac:.3f}**" if mean_ac is not None else "- Historical Mean: NA")
        st.write(f"- Predicted 2025: **{pred25:.3f}**")

        # 2024 comparison text if present
        has_2024 = acreage_2024_col in drow.index and not pd.isna(drow[acreage_2024_col])
        if has_2024:
            ac2024 = drow[acreage_2024_col]
            st.write(f"- 2024 Acreage: **{ac2024:.3f}**")

            if ac2024 > 0:
                delta_24_25 = (pred25 - ac2024) / ac2024 * 100
                st.write(f"- Δ 2025 vs 2024: **{delta_24_25:+.1f}%**")

        # Δ Mean vs 2025
        if mean_ac is not None and mean_ac > 0:
            delta_pct_d = (pred25 - mean_ac) / mean_ac * 100
            st.write(f"- Δ 2025 vs Mean: **{delta_pct_d:+.1f}%**")

        # Small compact bar chart: Mean, 2024 (if available), 2025 Pred
        bar_labels = []
        bar_values = []

        if mean_ac is not None:
            bar_labels.append("Mean")
            bar_values.append(mean_ac)

        if has_2024:
            bar_labels.append("2024")
            bar_values.append(ac2024)

        bar_labels.append("2025 Pred")
        bar_values.append(pred25)

        if len(bar_values) > 0:
            fig2, ax2 = plt.subplots(figsize=(2.6, 2.6))   # small chart
            colors = ["#8FAADC", "#F4B183", "#6AA84F"][:len(bar_values)]

            ax2.bar(bar_labels, bar_values, width=0.5, color=colors)
            ax2.set_ylabel("Lakh ha", fontsize=10)
            ax2.set_title("Acreage Comparison", fontsize=11)
            ax2.tick_params(axis='both', labelsize=10)

            for i, v in enumerate(bar_values):
                ax2.text(i, v, f"{v:.2f}", ha="center", va="bottom", fontsize=9)

            st.pyplot(fig2)

# ------------------------------------------------
# 9. TEXTUAL RISK INTERPRETATION
# ------------------------------------------------
st.markdown("---")
st.subheader("🧠 Risk Interpretation")

stab_class = drow["Acreage_Stability_Class"]

if "Stable Acreage" in stab_class:
    msg = (
        f"**{selected_district}** is classified as **stable acreage**. "
        f"Acreage shows low year-to-year variation and this district can be considered a "
        f"**relatively safe zone**."
    )
elif "Moderately Variable" in stab_class:
    msg = (
        f"**{selected_district}** is classified as **moderately variable acreage**. "
        f"Acreage fluctuates across years and this district can be considered a "
        f"**moderate-risk zone**."
    )
elif "Highly Volatile" in stab_class:
    msg = (
        f"**{selected_district}** is classified as **highly volatile / crop switching likely**. "
        f"Acreage changes significantly across years, often driven by rainfall timing or price "
        f"signals. This district should be treated as a **risk zone**."
    )
elif "Marginal Acreage" in stab_class:
    msg = (
        f"**{selected_district}** is classified as **marginal and statistically unstable acreage**. "
        f"The cropped area is small and variable, and this district should be treated as a "
        f"**marginal zone**."
    )
else:
    msg = (
        f"Acreage stability class for **{selected_district}** is unclear or missing. "
        f"Please verify input data."
    )

st.write(msg)

# ------------------------------------------------
# 10. DISTRICT TABLE (LAST SECTION)
# ------------------------------------------------
st.markdown("---")
st.subheader("📋 District-wise Metrics (All Filtered Districts)")

cols_to_show = [
    district_col_csv,
    "Acreage_Stability_Class",
    "Years_Available" if "Years_Available" in df_view.columns else None,
    "Mean_Acreage" if "Mean_Acreage" in df_view.columns else None,
    "Std_Acreage" if "Std_Acreage" in df_view.columns else None,
    "CV(%)" if "CV(%)" in df_view.columns else None,
    "Trend_Slope" if "Trend_Slope" in df_view.columns else None,
    "R2" if "R2" in df_view.columns else None,
    acreage_2024_col if acreage_2024_col in df_view.columns else None,
    "Predicted_2025_Acreage",
]
cols_to_show = [c for c in cols_to_show if c in df_view.columns]

table_df = df_view[cols_to_show].copy().sort_values(district_col_csv)
st.dataframe(table_df, use_container_width=True)

