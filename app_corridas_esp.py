import streamlit as st

# Configurações da página
st.set_page_config(page_title="Juan viaja seguro por toda España.🇪🇸
", page_icon="🚖", layout="centered")

st.title("🚖 Cálculo de Corridas - Espanha")
st.markdown("Partida fixa: **Ibi (Alicante)** 🇪🇸")
st.divider()

# Custo fixo por km
custo_km = 0.27

# Lista de cidades (pode expandir depois)
cidades = [
    "Alicante", "Elche", "Benidorm", "Elda", "Orihuela", "Alcoy",
    "Torrevieja", "Villena", "Denia", "Calpe", "Petrer",
    "Santa Pola", "Crevillent", "Jávea", "Altea", "Novelda", "Guardamar del Segura"
]

# Entrada do usuário
destino = st.selectbox("Selecione o destino:", cidades)
distancia = st.number_input("Distância até o destino (km):", min_value=0.0, step=0.1)

# Cálculo automático
if distancia > 0:
    custo_total = distancia * custo_km
    st.success(f"💰 Valor da corrida: **€ {custo_total:,.2f}**")
else:
    st.info("Informe a distância para calcular o valor da corrida.")

# Informações extras
st.divider()
st.caption("Cálculo: distância × € 0,60 por km. Origem fixa em Ibi (Alicante).")
