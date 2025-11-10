import os
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

# ------------------------- LISTAS DE CIDADES -------------------------
cidades_espanha = [
    "Ibi", "Alicante", "Elche", "Benidorm", "Elda", "Orihuela", "Alcoy",
    "Torrevieja", "Villena", "Denia", "Calpe", "Petrer", "Santa Pola", "Crevillent",
    "Jávea", "Altea", "Novelda", "Guardamar del Segura", "Valencia", "Murcia", "Madrid",
    "Barcelona", "Sevilha", "Granada", "Toledo", "Zaragoza"
]

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
            destination TEXT,
            distance_km REAL,
            price_eur REAL
        )
    """)
    con.commit()
    con.close()

def insert_ride(status, origin, destination, distance_km, price_eur):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
        INSERT INTO rides (created_at, status, origin, destination, distance_km, price_eur)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (datetime.utcnow().isoformat(), status, origin, destination, distance_km, price_eur))
    con.commit()
    con.close()

def update_ride_status(ride_id, new_status):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("UPDATE rides SET status=? WHERE id=?", (new_status, ride_id))
    con.commit()
    con.close()

def fetch_rides():
    con = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT * FROM rides ORDER BY created_at DESC", con)
    con.close()
    return df

# ------------------------- GEO & DIST -------------------------
def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    return acos(sin(lat1)*sin(lat2) + cos(lat1)*cos(lat2)*cos(lon1 - lon2)) * R

# ------------------------- UI -------------------------
def user_view():
    st.header("Área do Usuário")
    st.caption("Selecione sua cidade de origem e destino para calcular o valor da corrida. Cálculo por km: € 0,60.")

    col1, col2 = st.columns(2)
    with col1:
        origem = st.selectbox("Origem", cidades_espanha, index=cidades_espanha.index("Ibi"))
    with col2:
        destino = st.selectbox("Destino", cidades_espanha, index=cidades_espanha.index("Alicante"))

    distancia_manual = st.number_input("Distância aproximada (km):", min_value=0.0, step=0.1)

    if st.button("Calcular valor", type="primary"):
        if origem == destino:
            st.warning("A origem e o destino não podem ser iguais.")
            return
        if distancia_manual <= 0:
            st.warning("Informe uma distância válida.")
            return

        preco = round(distancia_manual * COST_PER_KM, 2)
        st.success(f"🚗 De **{origem}** para **{destino}** — Distância: **{distancia_manual:.2f} km** | Valor: **€ {preco:,.2f}**")

        mapa = folium.Map(location=[38.625, -0.572], zoom_start=6)
        folium.Marker(location=[38.625, -0.572], popup=f"Origem: {origem}", icon=folium.Icon(color="green")).add_to(mapa)
        folium.Marker(location=[40.4168, -3.7038], popup=f"Destino: {destino}", icon=folium.Icon(color="red")).add_to(mapa)
        st_folium(mapa, height=400, use_container_width=True)

        if st.button("Solicitar corrida"):
            insert_ride("Pendente", origem, destino, distancia_manual, preco)
            st.success("Solicitação enviada com sucesso!")

def admin_view():
    st.header("Área do Administrador")
    st.caption("Visualize corridas, aceite solicitações e acompanhe o faturamento.")

    df = fetch_rides()
    if df.empty:
        st.info("Nenhuma corrida registrada.")
    else:
        st.dataframe(df)
        total = df['price_eur'].sum()
        st.metric("Faturamento total (€)", f"{total:,.2f}")
        fig = px.bar(df, x="destination", y="price_eur", title="Faturamento por destino (€)")
        st.plotly_chart(fig, use_container_width=True)

# ------------------------- MAIN -------------------------
def main():
    init_db()
    st.sidebar.title("Menu")
    modo = st.sidebar.radio("Selecione o modo", ["Usuário", "Administrador"])
    if modo == "Usuário":
        user_view()
    else:
        admin_view()

if __name__ == "__main__":
    main()
