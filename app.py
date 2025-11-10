
import os
import sqlite3
from datetime import datetime, date
import requests
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium
import folium
import plotly.express as px

st.set_page_config(page_title="Corridas Espanha - Usuário/Admin (V2)", page_icon="🚖", layout="wide")
COST_PER_KM = 0.60
DEFAULT_ORIGIN_NAME = "Ibi, Alicante, Espanha"
DB_PATH = "rides.db"
GMAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()

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
            duration_min REAL,
            price_eur REAL
        )
    """)
    con.commit()
    con.close()

def insert_ride(status, origin, olat, olng, dest, dlat, dlng, distance_km, duration_min, price_eur):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
        INSERT INTO rides (created_at, status, origin, origin_lat, origin_lng, destination, dest_lat, dest_lng, distance_km, duration_min, price_eur)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (datetime.utcnow().isoformat(), status, origin, olat, olng, dest, dlat, dlng, distance_km, duration_min, price_eur))
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
    conditions, params = [], []
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

def gmaps_geocode(address):
    if not GMAPS_API_KEY:
        return None
    try:
        url = "https://maps.googleapis.com/maps/api/geocode/json"
        r = requests.get(url, params={"address": address, "key": GMAPS_API_KEY}, timeout=15)
        data = r.json()
        if data.get("status") == "OK":
            loc = data["results"][0]["geometry"]["location"]
            return (loc["lat"], loc["lng"])
    except Exception:
        pass
    return None

def gmaps_distance_and_duration(origin_latlng, dest_latlng):
    if not GMAPS_API_KEY:
        return None, None
    try:
        url = "https://maps.googleapis.com/maps/api/distancematrix/json"
        params = {
            "origins": f"{origin_latlng[0]},{origin_latlng[1]}",
            "destinations": f"{dest_latlng[0]},{dest_latlng[1]}",
            "units": "metric",
            "key": GMAPS_API_KEY
        }
        r = requests.get(url, params=params, timeout=15)
        data = r.json()
        rows = data.get("rows", [])
        if rows and rows[0]["elements"][0]["status"] == "OK":
            meters = rows[0]["elements"][0]["distance"]["value"]
            seconds = rows[0]["elements"][0]["duration"]["value"]
            return meters/1000.0, seconds/60.0
    except Exception:
        pass
    return None, None

def decode_polyline(polyline_str):
    index, lat, lng, coordinates = 0, 0, 0, []
    while index < len(polyline_str):
        result, shift = 0, 0
        while True:
            b = ord(polyline_str[index]) - 63
            index += 1
            result |= (b & 0x1f) << shift
            shift += 5
            if b < 0x20:
                break
        dlat = ~(result >> 1) if (result & 1) else (result >> 1)
        lat += dlat
        result, shift = 0, 0
        while True:
            b = ord(polyline_str[index]) - 63
            index += 1
            result |= (b & 0x1f) << shift
            shift += 5
            if b < 0x20:
                break
        dlng = ~(result >> 1) if (result & 1) else (result >> 1)
        lng += dlng
        coordinates.append((lat / 1e5, lng / 1e5))
    return coordinates

def gmaps_directions_polyline(origin_latlng, dest_latlng):
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
        r = requests.get(url, params=params, timeout=15)
        data = r.json()
        if data.get("status") == "OK":
            pts = []
            for route in data["routes"]:
                for leg in route["legs"]:
                    for step in leg["steps"]:
                        pts.extend(decode_polyline(step["polyline"]["points"]))
            return pts
    except Exception:
        pass
    return None

def user_view():
    st.header("Área do Usuário")
    st.caption("Digite origem e destino. O sistema consulta o Google Maps e calcula o valor automaticamente (tarifa: € 0,60/km).")
    c1, c2 = st.columns(2)
    with c1:
        origin = st.text_input("Origem", value=DEFAULT_ORIGIN_NAME, placeholder="Ex.: Calle de San Vicente, Alicante")
    with c2:
        destination = st.text_input("Destino", placeholder="Ex.: Estación del Norte, Valencia")

    if st.button("Calcular preço", type="primary"):
        if not GMAPS_API_KEY:
            st.error("Defina a variável de ambiente GOOGLE_MAPS_API_KEY para habilitar o cálculo automático.")
            return
        if not origin.strip() or not destination.strip():
            st.warning("Digite origem e destino.")
            return
        orig_coords = gmaps_geocode(origin)
        dest_coords = gmaps_geocode(destination)
        if not orig_coords or not dest_coords:
            st.error("Não foi possível localizar os endereços. Tente detalhar (número, bairro, cidade).")
            return
        dist_km, dur_min = gmaps_distance_and_duration(orig_coords, dest_coords)
        if dist_km is None:
            st.error("Falha ao obter distância pelo Google. Verifique sua API key.")
            return
        price = round(dist_km * COST_PER_KM, 2)
        st.success(f"🚗 Distância: **{dist_km:.2f} km** | ⏱ **{dur_min:.0f} min** | 💰 **€ {price:,.2f}**")

        center = [(orig_coords[0] + dest_coords[0]) / 2, (orig_coords[1] + dest_coords[1]) / 2]
        m = folium.Map(location=center, zoom_start=9)
        folium.Marker(orig_coords, tooltip="Origem", popup=origin, icon=folium.Icon(color="green")).add_to(m)
        folium.Marker(dest_coords, tooltip="Destino", popup=destination, icon=folium.Icon(color="red")).add_to(m)
        poly = gmaps_directions_polyline(orig_coords, dest_coords)
        if poly:
            folium.PolyLine(poly, weight=5, opacity=0.85).add_to(m)
        st_folium(m, height=440, use_container_width=True)

        if st.button("Solicitar corrida"):
            insert_ride("Pendente", origin, orig_coords[0], orig_coords[1], destination, dest_coords[0], dest_coords[1], float(dist_km), float(dur_min), float(price))
            st.success("Solicitação enviada ao administrador!")

def admin_view():
    st.header("Área do Administrador")
    st.caption("Aceite corridas e visualize métricas por período.")
    c1, c2, c3 = st.columns(3)
    with c1:
        start_date = st.date_input("Início", value=date.today())
    with c2:
        end_date = st.date_input("Fim", value=date.today())
    with c3:
        status = st.selectbox("Status", ["Todos", "Pendente", "Aceita", "Concluída", "Recusada"])
    df = fetch_rides(start=start_date, end=end_date, status=status)
    st.subheader("Corridas")
    if df.empty:
        st.info("Nenhuma corrida encontrada.")
    else:
        for _, row in df.iterrows():
            with st.expander(f"#{int(row['id'])} | {row['origin']} → {row['destination']} | € {row['price_eur']:.2f} | {row['status']}"):
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.write(f"Distância: **{row['distance_km']:.2f} km**")
                    st.write(f"Tempo: **{row['duration_min']:.0f} min**")
                    st.write(f"Criada: {row['created_at']}")
                with col2:
                    if st.button("Aceitar", key=f"acc_{row['id']}"):
                        update_ride_status(int(row['id']), "Aceita")
                        st.experimental_rerun()
                    if st.button("Recusar", key=f"rej_{row['id']}"):
                        update_ride_status(int(row['id']), "Recusada")
                        st.experimental_rerun()
                with col3:
                    if st.button("Concluir", key=f"done_{row['id']}"):
                        update_ride_status(int(row['id']), "Concluída")
                        st.experimental_rerun()
                with col4:
                    st.metric("Valor (€)", f"{row['price_eur']:.2f}")
        st.subheader("Métricas")
        df["created_day"] = pd.to_datetime(df["created_at"]).dt.date
        agg = df.groupby("created_day").agg(total_eur=("price_eur", "sum"), rides=("id", "count")).reset_index()
        m1, m2, m3 = st.columns(3)
        m1.metric("Corridas", int(df.shape[0]))
        m2.metric("Faturamento (€)", f"{df['price_eur'].sum():,.2f}")
        m3.metric("Distância total (km)", f"{df['distance_km'].sum():,.1f}")
        if not agg.empty:
            fig = px.bar(agg, x="created_day", y="total_eur", title="Faturamento por dia (€)")
            st.plotly_chart(fig, use_container_width=True)

def main():
    init_db()
    st.sidebar.title("Menu")
    mode = st.sidebar.radio("Selecione o modo", ["Usuário", "Administrador"])
    st.sidebar.info("Defina GOOGLE_MAPS_API_KEY nas *secrets* para rotas e distâncias reais.")
    if mode == "Usuário":
        user_view()
    else:
        admin_view()

if __name__ == "__main__":
    main()
