import streamlit as st
import pandas as pd
from shapely import wkt
from shapely.geometry import LineString
import folium
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium

# --------------------------------------------------
# Helpers
# --------------------------------------------------

@st.cache_data
def add_coordinates(df: pd.DataFrame) -> pd.DataFrame:
    """
    Take the dataframe with 'geometry' (and possibly 'Unnamed: 7')
    and return same df with lon/lat for start, end and midpoint.
    """

    # 1) Rebuild full WKT string from split geometry columns
    if "Unnamed: 7" in df.columns:
        geom_str = df["geometry"].astype(str) + "," + df["Unnamed: 7"].astype(str)
    else:
        geom_str = df["geometry"].astype(str)

    # Remove leading/trailing quotes
    geom_str = geom_str.str.strip("'").str.strip()
    df = df.copy()
    df["geometry_wkt"] = geom_str

    # Prepare columns
    for col in ["lon_start", "lat_start", "lon_end", "lat_end", "lon_mid", "lat_mid"]:
        if col not in df.columns:
            df[col] = None

    # 2) Parse geometries
    for idx, row in df.iterrows():
        try:
            line: LineString = wkt.loads(row["geometry_wkt"])

            x0, y0 = line.coords[0]     # start (bus0)
            x1, y1 = line.coords[-1]    # end (bus1)

            xm = (x0 + x1) / 2
            ym = (y0 + y1) / 2

            df.at[idx, "lon_start"] = x0
            df.at[idx, "lat_start"] = y0
            df.at[idx, "lon_end"]   = x1
            df.at[idx, "lat_end"]   = y1
            df.at[idx, "lon_mid"]   = xm
            df.at[idx, "lat_mid"]   = ym

        except Exception as e:
            # If something fails, just log it in the app
            print(f"Could not parse geometry for row {idx}: {e}")

    return df


def make_osm_map(df: pd.DataFrame):
    """
    Create a Folium map (OpenStreetMap) with transformer markers.
    Uses the midpoint (lon_mid, lat_mid) as the transformer location.
    """

    df_valid = df.dropna(subset=["lat_mid", "lon_mid"]).copy()
    if df_valid.empty:
        st.warning("No valid coordinates found after parsing geometry.")
        return None

    # Center on mean location
    center_lat = df_valid["lat_mid"].astype(float).mean()
    center_lon = df_valid["lon_mid"].astype(float).mean()

    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=6,
        tiles="OpenStreetMap",
    )

    marker_cluster = MarkerCluster().add_to(m)

    for _, row in df_valid.iterrows():
        lat = float(row["lat_mid"])
        lon = float(row["lon_mid"])

        popup_html = f"""
        <b>Transformer ID:</b> {row.get('transformer_id', '')}<br>
        <b>Bus0:</b> {row.get('bus0', '')} ({row.get('voltage_bus0', '')} kV)<br>
        <b>Bus1:</b> {row.get('bus1', '')} ({row.get('voltage_bus1', '')} kV)<br>
        <b>Rating:</b> {row.get('s_nom', '')} MVA
        """

        folium.Marker(
            location=[lat, lon],
            popup=folium.Popup(popup_html, max_width=300),
            tooltip=row.get("transformer_id", "Transformer"),
        ).add_to(marker_cluster)

    return m


# --------------------------------------------------
# Streamlit UI
# --------------------------------------------------

st.set_page_config(page_title="Transformers Map", layout="wide")
st.title("🔌 Transformers Viewer on OpenStreetMap")

st.markdown(
    """
This tool reads an Excel file with transformer data, extracts their coordinates from
LINESTRING geometries, and shows each transformer on an interactive OpenStreetMap.
"""
)

# --- File input ---
st.sidebar.header("📂 Data input")

uploaded_file = st.sidebar.file_uploader(
    "Upload `transformers.xlsx`",
    type=["xlsx"],
    help="If you skip this, the app will try to load 'transformers.xlsx' from the current folder.",
)

if uploaded_file is not None:
    df_raw = pd.read_excel(uploaded_file)
else:
    # Try local file as fallback
    try:
        df_raw = pd.read_excel("transformers.xlsx")
        st.sidebar.info("Using local file: transformers.xlsx")
    except Exception:
        st.error("No file uploaded and could not find 'transformers.xlsx' locally.")
        st.stop()

# Add coordinates
df = add_coordinates(df_raw)

# --- Sidebar filters ---
st.sidebar.header("🔎 Filters")

# Transformer ID search
search_id = st.sidebar.text_input("Search Transformer ID (contains):", "")

# Voltage filters
voltage_cols = [c for c in ["voltage_bus0", "voltage_bus1"] if c in df.columns]

if voltage_cols:
    all_voltages = sorted(
        set(
            v
            for col in voltage_cols
            for v in df[col].dropna().unique()
        )
    )
    selected_voltages = st.sidebar.multiselect(
        "Filter by voltage (any of bus0/bus1):",
        options=all_voltages,
        default=all_voltages,
    )
else:
    selected_voltages = None

# Min rating filter
if "s_nom" in df.columns:
    min_rating = float(df["s_nom"].min() if df["s_nom"].notna().any() else 0)
    max_rating = float(df["s_nom"].max() if df["s_nom"].notna().any() else 0)
    if max_rating > 0:
        rating_slider = st.sidebar.slider(
            "Minimum transformer rating (MVA):",
            min_value=min_rating,
            max_value=max_rating,
            value=min_rating,
        )
    else:
        rating_slider = min_rating
else:
    rating_slider = None

# --- Apply filters ---
df_filtered = df.copy()

if search_id:
    df_filtered = df_filtered[
        df_filtered["transformer_id"].astype(str).str.contains(search_id, case=False, na=False)
    ]

if selected_voltages is not None and len(selected_voltages) > 0:
    mask_voltage = False
    for col in voltage_cols:
        mask_voltage = mask_voltage | df_filtered[col].isin(selected_voltages)
    df_filtered = df_filtered[mask_voltage]

if rating_slider is not None and "s_nom" in df_filtered.columns:
    df_filtered = df_filtered[df_filtered["s_nom"] >= rating_slider]

st.subheader("📊 Filtered transformers")
st.write(f"Number of transformers: **{len(df_filtered)}**")
st.dataframe(df_filtered.head(50))  # show a preview

# --- Map ---
st.subheader("🗺️ Map (OpenStreetMap)")

if df_filtered.empty:
    st.warning("No transformers match the current filters.")
else:
    m = make_osm_map(df_filtered)
    if m is not None:
        st_folium(m, width="100%", height=600)
