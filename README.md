Here’s a README-style description you can drop straight into your repo:

---

# Ingrid Capacity – Grid Screening Tool 

The **Grid Screening Tool** is an internal web app built for Ingrid Capacity to quickly screen and visualise grid connection opportunities in Spain.

It combines **TSO capacity data** with **open grid infrastructure data** from OpenStreetMap / OpenInfraMap and presents everything on a single interactive map, so you can move from raw files to a spatial view of “where to build” in seconds.

---

## What this tool does

**1. Visualises Spanish grid connection points (REE capacity map)**

* Upload a standard REE *generación* / capacity Excel export.
* The app automatically:

  * Reads UTM coordinates (`Coordenada UTM X`, `Coordenada UTM Y`)
  * Converts them to WGS84 lat/lon (EPSG:32630 → EPSG:4326)
  * Filters by:

    * **Voltage level** (`Nivel de Tensión (kV)`)
    * **Available capacity** (`Capacidad disponible (MW)`)
* Each connection point is shown as a red marker with a **card-style popup** summarising:

  * Substation name (`Nombre Subestación`)
  * Province / municipality
  * Voltage level
  * Available vs. occupied capacity
  * Utilisation (%) and a flag if no usable capacity remains

**2. Overlays OSM substations**

* Uses a pre-exported `spain_substations.geojson` (from Overpass / OpenInfraMap / OSM).
* Cleans out noisy features and displays only “real” substations with:

  * Name
  * Voltage
  * Operator
* Substations are shown as blue circles and can be toggled on/off as a map layer.

**3. Optional OSM transmission line layer**

* Optionally loads `line.geojson` with OSM **high-voltage transmission lines**.
* Lines are styled by nominal voltage (e.g. ~400 kV, ~220 kV, ~110 kV) using different colours and weights.
* Hover tooltips and popups expose:

  * Operator
  * Voltage (kV)
  * Circuits, cables, frequency
  * Underlying OSM id

**4. Grid context from OpenInfraMap**
Underneath everything, the map uses tiled layers from **OpenInfraMap**:

* `OpenInfraMap – Power` (HV/MV/LV lines + substations)
* `OpenInfraMap – Low voltage`
* `OpenInfraMap – Substations tile`

plus the standard **OpenStreetMap** basemap. You can toggle each layer via the built-in layer control.

---

## Why this is useful

This tool is designed as a **fast screening layer** for development and BD work:

* Quickly see **where capacity exists** and at what voltage level.
* Understand how that capacity sits relative to:

  * Existing substations
  * Existing transmission lines
  * Urban/industrial areas in OSM
* Use voltage and capacity sliders to **narrow down candidate nodes** before detailed modelling or commercial discussions.

It’s intentionally lightweight: everything runs as a **Streamlit** app with **Folium** maps, so analysts can iterate on data and visual logic without heavy GIS tooling.

---

## Inputs & expected files

The current Spain configuration expects:

1. **REE capacity Excel** (uploaded in the UI)

   * Key columns (Spanish naming):

     * `Coordenada UTM X`, `Coordenada UTM Y` (UTM zone 30N, EPSG:32630)
     * `Nombre Subestación`
     * `Nivel de Tensión (kV)`
     * `Capacidad disponible (MW)`
     * `Capacidad ocupada (MW)` *(optional but used for utilisation)*
     * `Provincia`, `Municipio` *(optional but used for location labels)*

2. **OSM substations GeoJSON** – `spain_substations.geojson`

   * A point GeoJSON exported from Overpass / OpenInfraMap / other OSM tools.
   * Must contain `geometry.type == "Point"` and properties like `name`, `voltage`, `operator`.

3. **OSM transmission lines GeoJSON** – `line.geojson` *(optional)*

   * A line GeoJSON with `power=line` features and properties such as `voltage`, `operator`, `circuits`, `cables`.

---

## Tech stack

* **Python**
* **Streamlit** – app framework / UI
* **Folium + streamlit-folium** – interactive maps and popups
* **pyproj** – UTM → WGS84 coordinate transformation
* **Pandas** – data wrangling for Excel/GeoJSON inputs

---

## Running the app (short)

```bash
pip install -r requirements.txt   # or pip install streamlit folium streamlit-folium pyproj pandas
streamlit run grid_screening_tool.py
```

Then open the Streamlit URL, upload:

* A REE capacity Excel file,
* Ensure `spain_substations.geojson` (and optionally `line.geojson`) sit next to the script,

and you’ll get an interactive grid screening map ready for exploration and screenshots for Ingrid Capacity internal work and investor decks.
