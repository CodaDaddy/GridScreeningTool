import json
import math

import streamlit as st
import pandas as pd
import folium
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium
from pyproj import Transformer

# ========= UTM -> WGS84 (Spain, zone 30N) =========
utm30_to_wgs84 = Transformer.from_crs("EPSG:32630", "EPSG:4326", always_xy=True)


def convert_spain_to_wgs84(df: pd.DataFrame, source_name: str | None = None) -> pd.DataFrame:
    """
    Convert standard REE-style Spain capacity file with
    'Coordenada UTM X' / 'Coordenada UTM Y' to WGS84 lat/lon.
    Creates 'lon_wgs', 'lat_wgs', and optional 'source_file'.
    """
    df = df.copy()
    required_cols = ["Coordenada UTM X", "Coordenada UTM Y"]
    for c in required_cols:
        if c not in df.columns:
            raise ValueError(f"Missing required column '{c}' in Spain file '{source_name or ''}'.")

    df["Coordenada UTM X"] = pd.to_numeric(df["Coordenada UTM X"], errors="coerce")
    df["Coordenada UTM Y"] = pd.to_numeric(df["Coordenada UTM Y"], errors="coerce")

    xs = df["Coordenada UTM X"].values
    ys = df["Coordenada UTM Y"].values
    lons, lats = utm30_to_wgs84.transform(xs, ys)

    df["lon_wgs"] = lons
    df["lat_wgs"] = lats

    if source_name is not None:
        df["source_file"] = source_name

    # keep only valid coords
    df.loc[
        ~(
            (df["lat_wgs"].between(-90, 90))
            & (df["lon_wgs"].between(-180, 180))
        ),
        ["lat_wgs", "lon_wgs"],
    ] = pd.NA

    return df


# ========= Substations (GeoJSON) helpers =========

@st.cache_data
def load_substations(path: str):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data


def is_valid_feature(feature):
    """
    Return True only if the feature has clean geometry + relevant info.
    Filters OUT all substations where voltage is not known.
    """
    geom = feature.get("geometry")
    if not geom:
        return False

    if geom.get("type") != "Point":
        return False

    coords = geom.get("coordinates")
    if not coords or len(coords) != 2:
        return False

    lon, lat = coords
    if (
        lon is None or lat is None
        or lon in ["", "N/A"] or lat in ["", "N/A"]
    ):
        return False

    props = feature.get("properties", {})
    name = props.get("name")
    voltage = props.get("voltage")
    operator = props.get("operator")

    # require a non-empty voltage value
    if not voltage:
        return False

    # basic quality requirement
    if not name and not operator:
        return False

    return True


# ========= Transmission lines (GeoJSON) helpers =========

@st.cache_data
def load_lines(path: str = "line.geojson"):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def line_style_function(feature):
    """Color OSM lines by voltage."""
    props = feature.get("properties", {})
    v_raw = str(props.get("voltage", ""))

    try:
        v = int(v_raw.split(";")[0])   # handle "400000;220000"
    except Exception:
        v = None

    color = "#666666"
    weight = 2

    if v is not None:
        if v >= 380000:
            color, weight = "#d73027", 3      # ~400 kV
        elif v >= 220000:
            color, weight = "#fc8d59", 2.5    # ~220 kV
        elif v >= 110000:
            color = "#4575b4"                 # ~110 kV

    return {"color": color, "weight": weight, "opacity": 0.9}


def build_line_popup_html(props: dict) -> str:
    """Card-style popup for each transmission line."""
    name = props.get("name", "Transmission line")
    operator = props.get("operator", "Unknown")
    voltage_raw = str(props.get("voltage", "Unknown"))
    voltage_kv = props.get("voltage_kv")
    circuits = props.get("circuits", "N/A")
    cables = props.get("cables", "N/A")
    freq = props.get("frequency", "N/A")

    voltage_str = f"{voltage_kv:.1f} kV" if isinstance(voltage_kv, (int, float)) and not pd.isna(voltage_kv) else voltage_raw

    popup_html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                width: 260px; padding: 8px 10px;">
      <div style="font-size:16px; font-weight:600; margin-bottom:2px;">{name}</div>
      <div style="font-size:12px; color:#666; margin-bottom:6px;">
        ⚙️ Operator: {operator}
      </div>
      <div style="height:1px; background-color:#555; margin:4px 0 8px 0;"></div>

      <div style="border-radius:8px; background:#f7f7f9; padding:8px; margin-bottom:6px;">
        <div style="font-size:12px; font-weight:600; margin-bottom:4px;">
          ⚡ Electrical characteristics
        </div>
        <div style="font-size:12px; color:#333;">
          <b>Voltage:</b> {voltage_str}<br>
          <b>Circuits:</b> {circuits}<br>
          <b>Cables:</b> {cables}<br>
          <b>Frequency:</b> {freq}
        </div>
      </div>

      <div style="font-size:10px; color:#999;">
        Data: OpenStreetMap / OpenInfraMap
      </div>
    </div>
    """
    return popup_html


# ========= Streamlit app =========

st.set_page_config(page_title="Grid Screening Tool – Spain", layout="wide")
st.title("🛰️ Ingrid Capacity – Grid Screening Tool")

# ------ Sidebar: optional OSM line layer ------
st.sidebar.header("🧩 Optional layers")
show_lines = st.sidebar.checkbox("Show OSM transmission lines (line.geojson)", value=False)

st.markdown(
    """
This app shows on **one map**:

- 🔌 **Spain grid connection points** (one or more REE capacity exports)  
- 🏭 **OSM substations** from `spain_substations.geojson` (only with known voltage)  
- 🌐 **OSM transmission lines** from `line.geojson` (optional checkbox, click line → card popup)  
- On top of **OpenStreetMap + OpenInfraMap** grid tiles
"""
)

# ------ Sidebar: REE capacity upload (MULTI-FILE) ------
st.sidebar.header("📂 Spain capacity input")

spain_files = st.sidebar.file_uploader(
    "Upload one or more Spain capacity Excel files (REE capacity map export)",
    type=["xlsx"],
    accept_multiple_files=True,
)

spain_df = None
name_col = volt_col = cap_avail_col = cap_occ_col = None
prov_col = muni_col = None

if spain_files:
    converted = []
    read_errors = []

    for f in spain_files:
        try:
            df_raw = pd.read_excel(f)
            if df_raw.empty:
                read_errors.append(f"{f.name}: file is empty")
                continue

            df_conv = convert_spain_to_wgs84(df_raw, source_name=f.name)
            converted.append(df_conv)

        except Exception as e:
            read_errors.append(f"{f.name}: {e}")

    if read_errors:
        st.sidebar.error("Some capacity files could not be parsed:\n- " + "\n- ".join(read_errors))

    if converted:
        spain_df = pd.concat(converted, ignore_index=True)

        # Typical REE column names
        cols = spain_df.columns
        name_col       = "Nombre Subestación"         if "Nombre Subestación"         in cols else None
        volt_col       = "Nivel de Tensión (kV)"      if "Nivel de Tensión (kV)"      in cols else None
        cap_avail_col  = "Capacidad disponible (MW)"  if "Capacidad disponible (MW)"  in cols else None
        cap_occ_col    = "Capacidad ocupada (MW)"     if "Capacidad ocupada (MW)"     in cols else None
        prov_col       = "Provincia"                  if "Provincia"                  in cols else None
        muni_col       = "Municipio"                  if "Municipio"                  in cols else None

        # Make numeric for filtering
        if volt_col:
            spain_df[volt_col] = pd.to_numeric(spain_df[volt_col], errors="coerce")
        if cap_avail_col:
            spain_df[cap_avail_col] = pd.to_numeric(spain_df[cap_avail_col], errors="coerce")
        if cap_occ_col:
            spain_df[cap_occ_col] = pd.to_numeric(spain_df[cap_occ_col], errors="coerce")

        st.sidebar.subheader("Filters")

        # ------- Voltage filter (robust) -------
        if volt_col and spain_df[volt_col].notna().any():
            vmin = float(spain_df[volt_col].min())
            vmax = float(spain_df[volt_col].max())
            vmin_i = int(math.floor(vmin))
            vmax_i = int(math.ceil(vmax))

            if vmin_i < vmax_i:
                vsel = st.sidebar.slider(
                    "Voltage range (kV)",
                    min_value=vmin_i,
                    max_value=vmax_i,
                    value=(vmin_i, vmax_i),
                )
                spain_df = spain_df[
                    (spain_df[volt_col] >= vsel[0])
                    & (spain_df[volt_col] <= vsel[1])
                ]
            else:
                st.sidebar.info(f"Voltage level fixed at {vmin_i} kV (no range to filter).")

        # ------- Capacity filter (available capacity, robust) -------
        if cap_avail_col and spain_df[cap_avail_col].notna().any():
            cmin = float(spain_df[cap_avail_col].min())
            cmax = float(spain_df[cap_avail_col].max())
            cmin_i = int(math.floor(cmin))
            cmax_i = int(math.ceil(cmax))

            if cmin_i < cmax_i:
                min_cap = st.sidebar.slider(
                    "Min available capacity (MW)",
                    min_value=cmin_i,
                    max_value=cmax_i,
                    value=cmin_i,
                )
                spain_df = spain_df[spain_df[cap_avail_col] >= min_cap]
            else:
                st.sidebar.info(
                    f"Available capacity fixed at {cmin_i} MW for all points (no range to filter)."
                )

        # final coordinate clean
        spain_df = spain_df.dropna(subset=["lat_wgs", "lon_wgs"])
        spain_df = spain_df[
            (spain_df["lat_wgs"].between(-90, 90))
            & (spain_df["lon_wgs"].between(-180, 180))
        ]

# ------ Load substations GeoJSON ------
substations = None
substation_coords = []

try:
    substations = load_substations("spain_substations.geojson")
    for feature in substations.get("features", []):
        if not is_valid_feature(feature):
            continue
        lon, lat = feature["geometry"]["coordinates"]
        substation_coords.append((lat, lon))
except FileNotFoundError:
    st.warning("spain_substations.geojson not found in this folder. OSM substation layer will be missing.")
except Exception as e:
    st.warning(f"Could not load spain_substations.geojson: {e}")
    substations = None
    substation_coords = []

# ------ Metrics ------
st.metric("REE connection points on map (all files)", len(spain_df) if spain_df is not None else 0)
st.metric("OSM substations (known voltage) on map", len(substation_coords))

st.subheader("🗺️ Map: REE connection points + OSM substations + OSM lines + OpenInfraMap grid")

# ------ Decide center based on all available coords ------
all_lat = []
all_lon = []

if spain_df is not None and not spain_df.empty:
    all_lat.extend(spain_df["lat_wgs"].tolist())
    all_lon.extend(spain_df["lon_wgs"].tolist())

for lat, lon in substation_coords:
    all_lat.append(lat)
    all_lon.append(lon)

# Fallback center on Spain if nothing else loaded
if not all_lat or not all_lon:
    center_lat, center_lon = 40.0, -3.7
else:
    center_lat = sum(all_lat) / len(all_lat)
    center_lon = sum(all_lon) / len(all_lon)

# ------ Build Folium map ------
m = folium.Map(
    location=[center_lat, center_lon],
    zoom_start=7,
    tiles=None,
)

# Base OSM
folium.TileLayer(
    tiles="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
    name="OpenStreetMap",
    attr="&copy; OpenStreetMap contributors",
).add_to(m)

# OpenInfraMap tiles
folium.TileLayer(
    tiles="https://tiles.openinframap.org/power/{z}/{x}/{y}.png",
    name="OpenInfraMap – Power",
    attr="&copy; OpenInfraMap, OpenStreetMap contributors",
    overlay=True,
    control=True,
).add_to(m)

folium.TileLayer(
    tiles="https://tiles.openinframap.org/power-lowvoltage/{z}/{x}/{y}.png",
    name="OpenInfraMap – Low voltage",
    attr="&copy; OpenInfraMap, OpenStreetMap contributors",
    overlay=True,
    control=True,
).add_to(m)

folium.TileLayer(
    tiles="https://tiles.openinframap.org/substations/{z}/{x}/{y}.png",
    name="OpenInfraMap – Substations tile",
    attr="&copy; OpenInfraMap, OpenStreetMap contributors",
    overlay=True,
    control=True,
).add_to(m)

# ------ Optional: OSM transmission lines (GeoJSON, card popup) ------
if show_lines:
    try:
        lines = load_lines("line.geojson")

        # Enrich properties with voltage in kV and prebuild popup html
        for feat in lines.get("features", []):
            props = feat.get("properties", {})
            v_raw = str(props.get("voltage", ""))
            try:
                props["voltage_kv"] = int(v_raw.split(";")[0]) / 1000.0
            except Exception:
                props["voltage_kv"] = None

            props["popup_html"] = build_line_popup_html(props)

        folium.GeoJson(
            lines,
            name="OSM transmission lines",
            style_function=line_style_function,
            highlight_function=lambda feat: {
                "weight": 5,
                "color": "#000000",
                "opacity": 1.0,
            },
            # NO tooltip -> no annoying hover box, only click popup
            popup=folium.GeoJsonPopup(
                fields=["popup_html"],
                aliases=[""],
                localize=True,
                labels=False,
                max_width=320,
            ),
        ).add_to(m)

    except FileNotFoundError:
        st.warning("line.geojson not found in this folder. Transmission line layer will be missing.")
    except Exception as e:
        st.warning(f"Could not load line.geojson: {e}")

# ------ Add OSM substations (blue circles, only known voltage) ------
if substations is not None:
    fg_sub = folium.FeatureGroup(name="OSM Substations (GeoJSON, known voltage)")
    for feature in substations.get("features", []):
        if not is_valid_feature(feature):
            continue

        props = feature.get("properties", {})
        lon, lat = feature["geometry"]["coordinates"]

        name = props.get("name", "Substation")
        voltage = props.get("voltage", "Unknown")
        operator = props.get("operator", "Unknown")

        popup_html = f"""
        <b>{name}</b><br>
        Voltage: {voltage}<br>
        Operator: {operator}
        """

        folium.CircleMarker(
            location=[lat, lon],
            radius=5,
            fill=True,
            fill_opacity=0.85,
            popup=popup_html,
            tooltip=name,
            color="blue",
        ).add_to(fg_sub)

    fg_sub.add_to(m)

# ------ Add REE capacity points (red plug markers with "card" popup, ALL FILES) ------
if spain_df is not None and not spain_df.empty:
    fg_es = folium.FeatureGroup(name="Spain connection points (REE, all files)")
    mc_es = MarkerCluster().add_to(fg_es)

    for _, row in spain_df.iterrows():
        lat = float(row["lat_wgs"])
        lon = float(row["lon_wgs"])

        source = row.get("source_file", "")

        # Base info
        name = row.get(name_col, "Connection point") if name_col else "Connection point"
        province = row.get(prov_col, "") if prov_col else ""
        municipio = row.get(muni_col, "") if muni_col else ""
        location_text = ", ".join([x for x in [province, municipio] if x])

        voltage_val = row.get(volt_col, "") if volt_col else ""
        voltage_str = f"{voltage_val} kV" if voltage_val != "" else "N/A"

        # Capacity info
        avail = float(row.get(cap_avail_col, 0) or 0) if cap_avail_col else 0.0
        occ   = float(row.get(cap_occ_col, 0) or 0)   if cap_occ_col   else 0.0
        total = avail + occ

        util_pct = (occ / total * 100) if total > 0 else 0.0
        util_str = f"{util_pct:.1f}%"
        avail_str = f"{avail:.1f} MW"
        occ_str   = f"{occ:.1f} MW"
        no_capacity_flag = (avail <= 0.0)

        # Card-style popup HTML
        popup_html = f"""
        <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                    width: 260px; padding: 8px 10px;">
          <div style="font-size:16px; font-weight:600; margin-bottom:2px;">{name}</div>
          <div style="font-size:12px; color:#666; margin-bottom:3px;">
            📍 {location_text if location_text else "Spain"}
          </div>
          <div style="font-size:10px; color:#999; margin-bottom:6px;">
            Source: {source}
          </div>
          <div style="height:1px; background-color:#e33; margin:4px 0 8px 0;"></div>

          <div style="display:flex; justify-content:space-between; margin-bottom:10px;">
            <div style="flex:1; margin-right:4px; padding:6px 4px; background:#f7f7f9; border-radius:6px; text-align:center;">
              <div style="font-size:10px; color:#888; text-transform:uppercase;">Voltage level</div>
              <div style="font-size:18px; font-weight:600; margin-top:2px;">{voltage_str}</div>
            </div>
            <div style="flex:1; margin-left:4px; padding:6px 4px; background:#f7f7f9; border-radius:6px; text-align:center;">
              <div style="font-size:10px; color:#888; text-transform:uppercase;">Utilization</div>
              <div style="font-size:18px; font-weight:600; margin-top:2px;">{util_str}</div>
            </div>
          </div>

          <div style="border-radius:8px; border-left:4px solid #ffb01f; background:#fff8e6; padding:8px 8px 6px 8px; margin-bottom:8px;">
            <div style="font-size:12px; font-weight:600; margin-bottom:4px;">
              ⚡ Capacity Overview (MW)
            </div>
            <div style="display:flex; justify-content:space-between; font-size:12px;">
              <div>
                <div style="color:#666;">Available Capacity</div>
                <div style="font-size:14px; font-weight:600; color:{'#d00' if no_capacity_flag else '#111'};">
                  {avail_str}
                </div>
                {"<div style='font-size:10px; color:#d00;'>● No usable capacity</div>" if no_capacity_flag else ""}
              </div>
              <div style="text-align:right;">
                <div style="color:#666;">Occupied Capacity</div>
                <div style="font-size:14px; font-weight:600; color:#d33636;">
                  {occ_str}
                </div>
                <div style="font-size:10px; color:#888;">{util_str} utilized</div>
              </div>
            </div>
          </div>
        </div>
        """

        folium.Marker(
            location=[lat, lon],
            popup=folium.Popup(popup_html, max_width=300),
            tooltip=name,
            icon=folium.Icon(icon="plug", prefix="fa", color="red"),
        ).add_to(mc_es)

    fg_es.add_to(m)

# ------ Layer control + render ------
folium.LayerControl().add_to(m)
st_folium(m, width=900, height=650)
