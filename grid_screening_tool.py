import streamlit as st
import pandas as pd
import folium
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium
from pyproj import Transformer

# ========= UTM -> WGS84 (Spain, zone 30N) =========
utm30_to_wgs84 = Transformer.from_crs("EPSG:32630", "EPSG:4326", always_xy=True)

def convert_spain_to_wgs84(df: pd.DataFrame) -> pd.DataFrame:
    """
    Convert standard REE-style Spain capacity file with
    'Coordenada UTM X' / 'Coordenada UTM Y' to WGS84 lat/lon.
    Creates 'lon_wgs', 'lat_wgs'.
    """
    df = df.copy()
    required_cols = ["Coordenada UTM X", "Coordenada UTM Y"]
    for c in required_cols:
        if c not in df.columns:
            raise ValueError(f"Missing required column '{c}' in Spain file.")

    df["Coordenada UTM X"] = pd.to_numeric(df["Coordenada UTM X"], errors="coerce")
    df["Coordenada UTM Y"] = pd.to_numeric(df["Coordenada UTM Y"], errors="coerce")

    xs = df["Coordenada UTM X"].values
    ys = df["Coordenada UTM Y"].values
    lons, lats = utm30_to_wgs84.transform(xs, ys)

    df["lon_wgs"] = lons
    df["lat_wgs"] = lats

    # keep only valid coords
    df.loc[
        ~(
            (df["lat_wgs"].between(-90, 90))
            & (df["lon_wgs"].between(-180, 180))
        ),
        ["lat_wgs", "lon_wgs"],
    ] = pd.NA

    return df


# ========= Streamlit app =========

st.set_page_config(page_title="Grid Screening Tool – Spain", layout="wide")
st.title("🛰️ Ingrid Capacity – Grid Screening Tool")

st.markdown(
    """
This app shows **Spain grid connection points** on top of:

- **OpenStreetMap** base map  
- **OpenInfraMap – Power grid** (HV/MV/LV lines + substations from OSM)

All OpenInfraMap grid tiles are active via the layer control.
"""
)

st.sidebar.header("📂 Spain capacity input")

spain_file = st.sidebar.file_uploader(
    "Upload Spain capacity Excel (REE capacity map export)",
    type=["xlsx"],
)

spain_df = None

if spain_file is not None:
    try:
        df_raw = pd.read_excel(spain_file)

        if df_raw.empty:
            st.sidebar.error("Spain capacity file is empty.")
        else:
            # Convert coordinates
            spain_df = convert_spain_to_wgs84(df_raw)

            # Check / infer key columns (no UI mapping)
            # These are the typical names in your sample
            name_col = "Nombre Subestación" if "Nombre Subestación" in spain_df.columns else None
            volt_col = "Nivel de Tensión (kV)" if "Nivel de Tensión (kV)" in spain_df.columns else None
            cap_col  = "Capacidad disponible (MW)" if "Capacidad disponible (MW)" in spain_df.columns else None

            # Make numeric for filtering
            if volt_col:
                spain_df[volt_col] = pd.to_numeric(spain_df[volt_col], errors="coerce")
            if cap_col:
                spain_df[cap_col] = pd.to_numeric(spain_df[cap_col], errors="coerce")

            # ===== Filters (just sliders, no mapping UI) =====
            st.sidebar.subheader("Filters")

            # Voltage filter
            if volt_col and spain_df[volt_col].notna().any():
                vmin = float(spain_df[volt_col].min())
                vmax = float(spain_df[volt_col].max())
                if vmin < vmax:
                    vsel = st.sidebar.slider(
                        "Voltage range (kV)",
                        min_value=round(vmin),
                        max_value=round(vmax),
                        value=(round(vmin), round(vmax)),
                    )
                    spain_df = spain_df[
                        (spain_df[volt_col] >= vsel[0])
                        & (spain_df[volt_col] <= vsel[1])
                    ]

            # Capacity filter
            if cap_col and spain_df[cap_col].notna().any():
                cmin = float(spain_df[cap_col].min())
                cmax = float(spain_df[cap_col].max())
                if cmin < cmax:
                    min_cap = st.sidebar.slider(
                        "Min available capacity (MW)",
                        min_value=round(cmin),
                        max_value=round(cmax),
                        value=round(cmin),
                    )
                    spain_df = spain_df[spain_df[cap_col] >= min_cap]

            # final coordinate clean
            spain_df = spain_df.dropna(subset=["lat_wgs", "lon_wgs"])
            spain_df = spain_df[
                (spain_df["lat_wgs"].between(-90, 90))
                & (spain_df["lon_wgs"].between(-180, 180))
            ]

    except Exception as e:
        st.sidebar.error(f"Error reading/parsing Spain file: {e}")
        spain_df = None

st.metric("Spain grid connection points on map", len(spain_df) if spain_df is not None else 0)

st.subheader("🗺️ Map with OpenInfraMap grid + Spain connection points")

if spain_df is None or spain_df.empty:
    st.info("Upload a Spain capacity file to see connection points.")
else:
    all_lat = spain_df["lat_wgs"].tolist()
    all_lon = spain_df["lon_wgs"].tolist()

    center_lat = sum(all_lat) / len(all_lat)
    center_lon = sum(all_lon) / len(all_lon)

    # Base map with explicit tiles so we can add OpenInfraMap layers
    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=7,
        tiles=None,
    )

    # --- Base OSM ---
    folium.TileLayer(
        tiles="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
        name="OpenStreetMap",
        attr="&copy; OpenStreetMap contributors",
    ).add_to(m)

    # --- OpenInfraMap grid tiles ---
    # Main power grid (HV/MV/LV lines, substations, plants)
    folium.TileLayer(
        tiles="https://tiles.openinframap.org/power/{z}/{x}/{y}.png",
        name="OpenInfraMap – Power",
        attr="&copy; OpenInfraMap, OpenStreetMap contributors",
        overlay=True,
        control=True,
    ).add_to(m)

    # Low voltage grid (separate layer on OIM, optional)
    folium.TileLayer(
        tiles="https://tiles.openinframap.org/power-lowvoltage/{z}/{x}/{y}.png",
        name="OpenInfraMap – Low voltage",
        attr="&copy; OpenInfraMap, OpenStreetMap contributors",
        overlay=True,
        control=True,
    ).add_to(m)

    # Substations only layer (optional – still raster, but useful)
    folium.TileLayer(
        tiles="https://tiles.openinframap.org/substations/{z}/{x}/{y}.png",
        name="OpenInfraMap – Substations",
        attr="&copy; OpenInfraMap, OpenStreetMap contributors",
        overlay=True,
        control=True,
    ).add_to(m)

    # You now get something very close to “Grid Infrastructure / HV / MV / LV / Substations”
    # – just as raster layers instead of individual checkboxes.

    # --- Spain connection points (your data) ---
    fg_es = folium.FeatureGroup(name="Spain connection points")
    mc_es = MarkerCluster().add_to(fg_es)

    name_col = "Nombre Subestación" if "Nombre Subestación" in spain_df.columns else None
    volt_col = "Nivel de Tensión (kV)" if "Nivel de Tensión (kV)" in spain_df.columns else None
    cap_col  = "Capacidad disponible (MW)" if "Capacidad disponible (MW)" in spain_df.columns else None

    for _, row in spain_df.iterrows():
        lat = float(row["lat_wgs"])
        lon = float(row["lon_wgs"])

        popup_parts = []
        if name_col:
            popup_parts.append(f"<b>{name_col}:</b> {row.get(name_col, '')}")
        if volt_col:
            popup_parts.append(f"<b>{volt_col}:</b> {row.get(volt_col, '')}")
        if cap_col:
            popup_parts.append(f"<b>{cap_col}:</b> {row.get(cap_col, '')} MW")

        popup_html = "<br>".join(popup_parts) if popup_parts else "Connection point"

        folium.Marker(
            location=[lat, lon],
            popup=folium.Popup(popup_html, max_width=350),
            tooltip=row.get(name_col, "Connection point") if name_col else "Connection point",
            icon=folium.Icon(icon="plug", prefix="fa", color="red"),
        ).add_to(mc_es)

    fg_es.add_to(m)


    folium.LayerControl().add_to(m)
    st_folium(m, width="100%", height=700)
