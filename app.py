
import os
import sqlite3
from datetime import datetime, date
from zoneinfo import ZoneInfo
import requests
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium
import folium
import plotly.express as px
from urllib.parse import quote_plus

st.set_page_config(page_title="Juan viaja seguro por toda España", page_icon="🚖", layout="wide")

COST_PER_KM = 0.60
MIN_PRICE = 5.00
NIGHT_SURCHARGE = 0.20  # 20%
NIGHT_START_HOUR = 20   # 20:00
NIGHT_END_HOUR = 5      # 05:00 (exclusive)
SPAIN_TZ = ZoneInfo("Europe/Madrid")

DB_PATH = "rides.db"
GMAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
USERS = {"admin": "1234", "gestor": "senhaSegura"}
ADMIN_DISPLAY_NAME = "Juan"
WHATSAPP_NUMBER_E164 = "5581987593444"  # +55 81 98759-3444

# -------------------- BANCO --------------------
def init_db():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS rides (
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
    )""")
    # --- Migração: adicionar coluna is_night (0/1) se não existir ---
    cur.execute("PRAGMA table_info(rides)")
    cols = [row[1] for row in cur.fetchall()]
    if "is_night" not in cols:
        cur.execute("ALTER TABLE rides ADD COLUMN is_night INTEGER DEFAULT 0")
    con.commit()
    con.close()

def insert_ride(status, origin, olat, olng, dest, dlat, dlng, distance_km, duration_min, price_eur, is_night):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""INSERT INTO rides (created_at, status, origin, origin_lat, origin_lng, destination, dest_lat, dest_lng, distance_km, duration_min, price_eur, is_night)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (datetime.utcnow().isoformat(), status, origin, olat, olng, dest, dlat, dlng, distance_km, duration_min, price_eur, int(is_night)))
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

# -------------------- GOOGLE --------------------
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
        params = {"origins": f"{origin_latlng[0]},{origin_latlng[1]}",
                  "destinations": f"{dest_latlng[0]},{dest_latlng[1]}",
                  "units": "metric", "key": GMAPS_API_KEY}
        r = requests.get(url, params=params, timeout=15)
        data = r.json()
        rows = data.get("rows", [])
        if rows and rows[0]["elements"][0]["status"] == "OK":
            meters = rows[0]["elements"][0]["distance"]["value"]
            seconds = rows[0]["elements"][0]["duration"]["value"]
            return meters / 1000.0, seconds / 60.0
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
            result |= (b & 0x1F) << shift
            shift += 5
            if b < 0x20:
                break
        dlat = ~(result >> 1) if (result & 1) else (result >> 1)
        lat += dlat
        result, shift = 0, 0
        while True:
            b = ord(polyline_str[index]) - 63
            index += 1
            result |= (b & 0x1F) << shift
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
        params = {"origin": f"{origin_latlng[0]},{origin_latlng[1]}",
                  "destination": f"{dest_latlng[0]},{dest_latlng[1]}",
                  "units": "metric", "key": GMAPS_API_KEY}
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

# -------------------- UTIL --------------------
def is_night_time(dt_spain: datetime) -> bool:
    """Retorna True se o horário local na Espanha estiver entre 20:00 e 05:00."""
    h = dt_spain.hour
    # Janela cruza a meia-noite: 20-23 ou 0-4
    return (h >= NIGHT_START_HOUR) or (h < NIGHT_END_HOUR)

# -------------------- USUÁRIO --------------------
def user_view():
    # Hero title bar
    st.markdown("""
        <div style="background:linear-gradient(90deg,#ffd400,#ff5a5a);
                    padding:18px;border-radius:14px;margin-bottom:18px;color:#111;
                    box-shadow:0 4px 18px rgba(0,0,0,0.15);">
            <h1 style="margin:0;line-height:1.2;">Juan viaja seguro por toda España</h1>
            <div style="opacity:.8">Calcule o valor da corrida em tempo real • €0,60/km • tarifa mínima €5,00 • +20% noturna (20h–5h)</div>
        </div>
    """, unsafe_allow_html=True)

    with st.form("form_corrida"):
        col1, col2 = st.columns(2)
        with col1:
            origin = st.text_input("Origem")
        with col2:
            destination = st.text_input("Destino")
        submit = st.form_submit_button("Calcular preço")

    if submit:
        if not GMAPS_API_KEY:
            st.error("Defina GOOGLE_MAPS_API_KEY para habilitar o cálculo automático.")
            return
        if not origin.strip() or not destination.strip():
            st.warning("Digite origem e destino.")
            return

        with st.spinner("🧭 Calculando rota, aguarde um momento..."):
            orig_coords = gmaps_geocode(origin)
            dest_coords = gmaps_geocode(destination)
            if not orig_coords or not dest_coords:
                st.error("Endereços não encontrados. Tente especificar melhor.")
                return

            dist_km, dur_min = gmaps_distance_and_duration(orig_coords, dest_coords)
            if dist_km is None:
                st.error("Não foi possível obter a distância/tempo.")
                return

            base_price = max(round(dist_km * COST_PER_KM, 2), MIN_PRICE)

            now_spain = datetime.now(SPAIN_TZ)
            night = is_night_time(now_spain)
            final_price = round(base_price * (1.0 + NIGHT_SURCHARGE), 2) if night else base_price

            poly_points = gmaps_directions_polyline(orig_coords, dest_coords)

            st.session_state["calc_result"] = {
                "origin": origin, "destination": destination,
                "dist_km": dist_km, "dur_min": dur_min,
                "price": final_price, "base_price": base_price,
                "is_night": night,
                "poly_points": poly_points,
                "orig_coords": orig_coords, "dest_coords": dest_coords,
                "ts_local": now_spain.isoformat()
            }

    if "calc_result" in st.session_state:
        res = st.session_state["calc_result"]
        if res["is_night"]:
            st.info("💡 Tarifa noturna aplicada (20% a mais)")
        st.success(f"Distância: {res['dist_km']:.2f} km | Tempo: {res['dur_min']:.0f} min | Valor: € {res['price']:,.2f}")

        # --- Botão que SALVA e redireciona para WhatsApp (automático) ---
        col_btn = st.container()
        with col_btn:
            clicked = st.button("📲 SOLICITAR CORRIDA AGORA", key="btn_whatsapp", help="Salvar e abrir WhatsApp")
        if clicked:
            insert_ride("Pendente",
                        res['origin'], res['orig_coords'][0], res['orig_coords'][1],
                        res['destination'], res['dest_coords'][0], res['dest_coords'][1],
                        float(res['dist_km']), float(res['dur_min']), float(res['price']),
                        int(res['is_night']))
            # WhatsApp message
            night_tag = "%0A(Tarifa noturna +20%)" if res["is_night"] else ""
            msg = f"🚕 Solicitação de corrida%0AOrigem: {quote_plus(res['origin'])}%0ADestino: {quote_plus(res['destination'])}%0ADistância: {res['dist_km']:.2f} km%0AValor estimado: € {res['price']:,.2f}{night_tag}"
            wa_url = f"https://wa.me/{WHATSAPP_NUMBER_E164}?text={msg}"
            st.success("Solicitação salva! Abrindo WhatsApp...")
            st.markdown(f'<meta http-equiv="refresh" content="0; url={wa_url}">', unsafe_allow_html=True)

        # Estilo do botão (vibrante)
        st.markdown("""
            <style>
            button[kind="secondary"]#btn_whatsapp, button#btn_whatsapp {
                background: linear-gradient(90deg,#ff1f1f,#ffd400) !important;
                color:#111 !important;
                font-weight:800 !important;
                border-radius: 12px !important;
                padding: 0.8rem 1rem !important;
                box-shadow:0 8px 18px rgba(0,0,0,.20) !important;
            }
            </style>
        """, unsafe_allow_html=True)

        # --- Mapa ---
        m = folium.Map(location=[(res['orig_coords'][0] + res['dest_coords'][0]) / 2,
                                 (res['orig_coords'][1] + res['dest_coords'][1]) / 2], zoom_start=9)
        folium.Marker(res['orig_coords'], tooltip="Origem", icon=folium.Icon(color="green")).add_to(m)
        folium.Marker(res['dest_coords'], tooltip="Destino", icon=folium.Icon(color="red")).add_to(m)
        if res['poly_points']:
            folium.PolyLine(res['poly_points'], weight=5, opacity=0.85).add_to(m)
        st_folium(m, height=430, use_container_width=True)

# -------------------- ADMIN --------------------
def admin_login():
    st.header("🔐 Login do Administrador")
    username = st.text_input("Usuário")
    password = st.text_input("Senha", type="password")
    if st.button("Entrar"):
        if username in USERS and USERS[username] == password:
            st.session_state["logged_in"] = True
            st.session_state["user"] = username
            st.experimental_rerun()
        else:
            st.error("Usuário ou senha incorretos.")

def admin_view():
    if not st.session_state.get("logged_in"):
        admin_login()
        return

    st.header("📊 Painel do Administrador")
    st.success(f"👋 Bem-vindo ao painel, {ADMIN_DISPLAY_NAME}!")

    if st.button("Logout"):
        st.session_state.clear()
        st.experimental_rerun()

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
        st.info("Nenhuma corrida registrada no período/critério selecionado.")
    else:
        for _, row in df.iterrows():
            title = f"#{int(row['id'])} | {row['origin']} → {row['destination']} | € {row['price_eur']:.2f} | {row['status']}"
            with st.expander(title):
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.write(f"Distância: {row['distance_km']:.2f} km")
                    st.write(f"Tempo: {row['duration_min']:.0f} min")
                    st.write(f"Criada (UTC): {row['created_at']}")
                    st.write(f"Tarifa noturna: {'Sim' if int(row.get('is_night', 0)) == 1 else 'Não'}")
                with col2:
                    if st.button(f"Aceitar #{int(row['id'])}"):
                        update_ride_status(int(row['id']), "Aceita")
                        st.experimental_rerun()
                    if st.button(f"Recusar #{int(row['id'])}"):
                        update_ride_status(int(row['id']), "Recusada")
                        st.experimental_rerun()
                with col3:
                    if st.button(f"Concluir #{int(row['id'])}"):
                        update_ride_status(int(row['id']), "Concluída")
                        st.experimental_rerun()
                with col4:
                    st.metric("Valor (€)", f"{row['price_eur']:.2f}")

        st.subheader("Métricas")
        df["created_day"] = pd.to_datetime(df["created_at"]).dt.date
        agg = df.groupby("created_day").agg(total_eur=("price_eur", "sum"), rides=("id", "count")).reset_index()

        c1, c2, c3 = st.columns(3)
        c1.metric("Corridas", int(df.shape[0]))
        c2.metric("Faturamento (€)", f"{df['price_eur'].sum():,.2f}")
        c3.metric("Distância total (km)", f"{df['distance_km'].sum():,.1f}")

        if not agg.empty:
            fig = px.bar(agg, x="created_day", y="total_eur", title="Faturamento por dia (€)")
            st.plotly_chart(fig, use_container_width=True)

# -------------------- MAIN --------------------
def main():
    init_db()
    st.sidebar.title("Menu")
    mode = st.sidebar.radio("Selecione o modo", ["Usuário", "Administrador"])
    st.sidebar.info("Defina GOOGLE_MAPS_API_KEY nas secrets para rotas/distância reais.")
    if mode == "Usuário":
        user_view()
    else:
        admin_view()

if __name__ == "__main__":
    main()
