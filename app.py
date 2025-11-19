import json
import streamlit as st
import folium
from streamlit_folium import st_folium

# -------------------------------------------------
# 1. Load the GeoJSON with the transmission lines
# -------------------------------------------------
@st.cache_data
def load_lines(path: str = "line.geojson"):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data


# -------------------------------------------------
# 2. Styling function (color by voltage)
# -------------------------------------------------
def style_function(feature):
    props = feature.get("properties", {})
    voltage_raw = str(props.get("voltage", ""))

    # Handle things like "400000" or "400000;220000"
    try:
        v = int(voltage_raw.split(";")[0])
    except Exception:
        v = None

    color = "#666666"
    weight = 2

    if v is not None:
        if v >= 380000:
            color = "#d73027"   # red
            weight = 3
        elif v >= 220000:
            color = "#fc8d59"   # orange
            weight = 2.5
        elif v >= 110000:
            color = "#4575b4"   # blue

    return {
        "color": color,
        "weight": weight,
        "opacity": 0.9,
    }


# -------------------------------------------------
# 3. Helper: find a reasonable center for the map
# -------------------------------------------------
def compute_center(geojson_dict):
    coords = []
    for feat in geojson_dict.get("features", []):
        geom = feat.get("geometry", {})
        if geom.get("type") == "LineString":
            coords.extend(geom.get("coordinates", []))
        elif geom.get("type") == "MultiLineString":
            for line in geom.get("coordinates", []):
                coords.extend(line)

    if not coords:
        # Fallback: Spain center
        return 40.0, -3.5

    # GeoJSON is [lon, lat]
    lats = [c[1] for c in coords]
    lons = [c[0] for c in coords]
    return sum(lats) / len(lats), sum(lons) / len(lons)


# -------------------------------------------------
# 4. Streamlit app
# -------------------------------------------------
def main():
    st.set_page_config(layout="wide")
    st.title("OSM Transmission Lines (Spain)")
    # Option A: use local file
    data = load_lines("line.geojson")

    # Option B: let user upload instead:
    # uploaded = st.file_uploader("Upload line.geojson", type=["geojson", "json"])
    # if uploaded is None:
    #     st.stop()
    # data = json.load(uploaded)

    center_lat, center_lon = compute_center(data)

    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=6,
        tiles="OpenStreetMap"
    )

    # Add the GeoJSON layer
    wanted_fields = ["name", "operator", "voltage", "circuits", "cables", "frequency"]

    # keys present in first feature
    first_props = data["features"][0]["properties"]
    available_fields = [f for f in wanted_fields if f in first_props]

    folium.GeoJson(
        data,
        name="Transmission lines",
        style_function=style_function,
        popup=folium.GeoJsonPopup(
            fields=["@id", "operator", "voltage", "circuits", "cables", "frequency"],
            aliases=["OSM id", "Operator", "Voltage (V)", "Circuits", "Cables", "Frequency (Hz)"],
        ),
    ).add_to(m)




    folium.LayerControl().add_to(m)

    st_folium(m, width=1100, height=700)


if __name__ == "__main__":
    main()
