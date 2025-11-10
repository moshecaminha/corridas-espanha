
import os
import time
import sqlite3
from datetime import datetime, date
import requests
import pandas as pd
import streamlit as st
from math import radians, sin, cos, acos
from streamlit_folium import st_folium
import folium
import plotly.express as px

# ------------------------- CONFIG -------------------------
st.set_page_config(page_title="Corridas Espanha - Usuário/Admin", page_icon="🚖", layout="wide")
COST_PER_KM = 0.60  # €
DEFAULT_ORIGIN_NAME = "Ibi, Alicante, Espanha"
DB_PATH = "rides.db"  # SQLite local
GMAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()

# ------------------------- DB -------------------------
def init_db():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS rides (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT,
            status TEXT,
            origin TEXT,
            origin_lat REAL,
            origin_lng REAL,
            destination TEXT,
            dest_lat REAL,
            dest_lng REAL,
            distance_km REAL,
            price_eur REAL
        )
    """)
    con.commit()
    con.close()

def insert_ride(status, origin, olat, olng, dest, dlat, dlng, distance_km, price_eur):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
        INSERT INTO rides (created_at, status, origin, origin_lat, origin_lng, destination, dest_lat, dest_lng, distance_km, price_eur)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (datetime.utcnow().isoformat(), status, origin, olat, olng, dest, dlat, dlng, distance_km, price_eur))
    con.commit()
    con.close()

def update_ride_status(ride_id, new_status):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("UPDATE rides SET status=? WHERE id=?", (new_status, ride_id))
    con.commit()
    con.close()

def fetch_rides(start=None, end=None, status=None):
    con = sqlite3.connect(DB_PATH)
    q = "SELECT * FROM rides"
    conditions = []
    params = []
    if start:
        conditions.append("date(created_at) >= date(?)")
        params.append(start.isoformat())
    if end:
        conditions.append("date(created_at) <= date(?)")
        params.append(end.isoformat())
    if status and status != "Todos":
        conditions.append("status = ?")
        params.append(status)
    if conditions:
        q += " WHERE " + " AND ".join(conditions)
    q += " ORDER BY created_at DESC"
    df = pd.read_sql_query(q, con, params=params)
    con.close()
    return df

# ------------------------- GEO & DIST -------------------------
def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    return acos(sin(lat1)*sin(lat2) + cos(lat1)*cos(lat2)*cos(lon1 - lon2)) * R

def geocode_address(addr):
    if not GMAPS_API_KEY:
        return None
    try:
        url = "https://maps.googleapis.com/maps/api/geocode/json"
        r = requests.get(url, params={"address": addr, "key": GMAPS_API_KEY}, timeout=10)
        data = r.json()
        if data.get("status") == "OK":
            loc = data["results"][0]["geometry"]["location"]
            return loc["lat"], loc["lng"]
    except Exception as e:
        st.warning(f"Falha no geocoding: {e}")
    return None

def distance_matrix_km(origin_latlng, dest_latlng):
    if not GMAPS_API_KEY:
        return None
    try:
        url = "https://maps.googleapis.com/maps/api/distancematrix/json"
        params = {
            "origins": f"{origin_latlng[0]},{origin_latlng[1]}",
            "destinations": f"{dest_latlng[0]},{dest_latlng[1]}",
            "units": "metric",
            "key": GMAPS_API_KEY
        }
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
        rows = data.get("rows", [])
        if rows and rows[0]["elements"][0]["status"] == "OK":
            meters = rows[0]["elements"][0]["distance"]["value"]
            return meters / 1000.0
    except Exception as e:
        st.warning(f"Falha na Distance Matrix: {e}")
    return None

def directions_polyline(origin_latlng, dest_latlng):
    if not GMAPS_API_KEY:
        return None
    try:
        url = "https://maps.googleapis.com/maps/api/directions/json"
        params = {
            "origin": f"{origin_latlng[0]},{origin_latlng[1]}",
            "destination": f"{dest_latlng[0]},{dest_latlng[1]}",
            "units": "metric",
            "key": GMAPS_API_KEY
        }
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
        if data.get("status") == "OK":
            pts = []
            for route in data["routes"]:
                for leg in route["legs"]:
                    for step in leg["steps"]:
                        p = step["polyline"]["points"]
                        pts.extend(decode_polyline(p))
            return pts
    except Exception as e:
        st.warning(f"Falha no Directions: {e}")
    return None

def decode_polyline(polyline_str):
    index, lat, lng, coordinates = 0, 0, 0, []
    changes = {'lat': 0, 'lng': 0}

    while index < len(polyline_str):
        for unit in ['lat', 'lng']:
            shift, result = 0, 0

            while True:
                b = ord(polyline_str[index]) - 63
                index += 1
                result |= (b & 0x1f) << shift
                shift += 5
                if b < 0x20:
                    break

            if (result & 1):
                changes[unit] = ~(result >> 1)
            else:
                changes[unit] = (result >> 1)

        lat += changes['lat']
        lng += changes['lng']
        coordinates.append((lat / 1e5, lng / 1e5))

    return coordinates

# ------------------------- UI -------------------------
def user_view():
    st.header("Área do Usuário")
    st.caption("Informe origem e destino para calcular o valor. Cálculo por km: € 0,60.")

    col1, col2 = st.columns(2)
    with col1:
        origin = st.text_input("Origem", value=DEFAULT_ORIGIN_NAME)
    with col2:
        destination = st.text_input("Destino", placeholder="Ex.: Alicante, Espanha")

    if st.button("Calcular valor", type="primary"):
        if not destination.strip():
            st.warning("Digite um destino.")
            return

        if GMAPS_API_KEY:
            orig_coords = geocode_address(origin) or (38.625, -0.572)
            dest_coords = geocode_address(destination)
        else:
            st.info("Sem GOOGLE_MAPS_API_KEY: usando coordenadas aproximadas para Ibi e distância por linha reta.")
            orig_coords = (38.625, -0.572)
            dest_coords = geocode_address(destination)

        if not dest_coords:
            st.error("Não foi possível obter coordenadas do destino. Tente especificar melhor (cidade, país).")
            return

        dist_km = distance_matrix_km(orig_coords, dest_coords)
        if dist_km is None:
            dist_km = haversine_km(orig_coords[0], orig_coords[1], dest_coords[0], dest_coords[1])

        price = round(dist_km * COST_PER_KM, 2)

        st.success(f"Distância estimada: **{dist_km:.2f} km**  |  Valor: **€ {price:,.2f}**")

        m = folium.Map(location=[(orig_coords[0]+dest_coords[0])/2, (orig_coords[1]+dest_coords[1])/2], zoom_start=9)
        folium.Marker(orig_coords, tooltip="Origem", popup=origin, icon=folium.Icon(color="green")).add_to(m)
        folium.Marker(dest_coords, tooltip="Destino", popup=destination, icon=folium.Icon(color="red")).add_to(m)

        poly_points = directions_polyline(orig_coords, dest_coords) if GMAPS_API_KEY else None
        if poly_points:
            folium.PolyLine(poly_points, weight=5, opacity=0.8).add_to(m)
        else:
            folium.PolyLine([orig_coords, dest_coords], weight=3, opacity=0.6, dash_array="5,5").add_to(m)

        st_folium(m, height=420, use_container_width=True)

        if st.button("Solicitar corrida"):
            insert_ride("Pendente", origin, orig_coords[0], orig_coords[1], destination, dest_coords[0], dest_coords[1], float(dist_km), float(price))
            st.success("Solicitação enviada ao administrador!")

def admin_view():
    st.header("Área do Administrador")
    st.caption("Aceite corridas, acompanhe valores e visualize métricas por período.")

    colf1, colf2, colf3 = st.columns(3)
    with colf1:
        start_date = st.date_input("Início", value=date.today())
    with colf2:
        end_date = st.date_input("Fim", value=date.today())
    with colf3:
        status = st.selectbox("Status", ["Todos", "Pendente", "Aceita", "Concluída", "Recusada"])

    df = fetch_rides(start=start_date, end=end_date, status=status)

    st.subheader("Corridas")
    if df.empty:
        st.info("Nenhuma corrida no período/critério selecionado.")
    else:
        for idx, row in df.iterrows():
            with st.expander(f"#{int(row['id'])} | {row['origin']} → {row['destination']} | € {row['price_eur']:.2f} | {row['status']}"):
                colb1, colb2, colb3, colb4 = st.columns(4)
                with colb1:
                    st.write(f"Distância: **{row['distance_km']:.2f} km**")
                    st.write(f"Criada em: {row['created_at']}")
                with colb2:
                    if st.button("Aceitar", key=f"acc_{row['id']}"):
                        update_ride_status(int(row['id']), "Aceita")
                        st.experimental_rerun()
                    if st.button("Recusar", key=f"rej_{row['id']}"):
                        update_ride_status(int(row['id']), "Recusada")
                        st.experimental_rerun()
                with colb3:
                    if st.button("Concluir", key=f"done_{row['id']}"):
                        update_ride_status(int(row['id']), "Concluída")
                        st.experimental_rerun()
                with colb4:
                    st.write(f"Status atual: **{row['status']}**")

        st.subheader("Métricas")
        df["created_day"] = pd.to_datetime(df["created_at"]).dt.date
        agg = df.groupby("created_day").agg(total_eur=("price_eur", "sum"), rides=("id", "count")).reset_index()
        colm1, colm2, colm3 = st.columns(3)
        colm1.metric("Corridas", int(df.shape[0]))
        colm2.metric("Faturamento (€)", f"{df['price_eur'].sum():,.2f}")
        colm3.metric("Distância total (km)", f"{df['distance_km'].sum():,.1f}")

        if not agg.empty:
            fig = px.bar(agg, x="created_day", y="total_eur", title="Faturamento por dia (€)")
            st.plotly_chart(fig, use_container_width=True)

def main():
    init_db()
    st.sidebar.title("Menu")
    mode = st.sidebar.radio("Selecione o modo", ["Usuário", "Administrador"])
    st.sidebar.info("Para rotas reais e distâncias por rodovia, defina a variável de ambiente GOOGLE_MAPS_API_KEY com a sua API key do Google Maps.")
    if mode == "Usuário":
        user_view()
    else:
        admin_view()

if __name__ == "__main__":
    main()
