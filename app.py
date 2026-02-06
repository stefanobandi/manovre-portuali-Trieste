import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime, time

# Configurazione pagina
st.set_page_config(page_title="Monitor Manovre Trieste", layout="wide")

def fetch_tmt_data():
    """Funzione per pescare i dati dal sito TMT"""
    url = "https://www.trieste-marine-terminal.com/it/berthing-plan"
    try:
        response = requests.get(url, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Cerchiamo la tabella nel sito
        tables = soup.find_all('table')
        if not tables:
            return pd.DataFrame()
            
        # Estraiamo la prima tabella (Berthing Plan)
        df = pd.read_html(str(tables[0]))[0]
        
        # Pulizia base delle colonne (nomi tipici TMT: Vessel, ETB, ETD)
        # Nota: TMT spesso usa nomi colonne specifici, se cambiano aggiorneremo qui
        return df
    except Exception as e:
        st.error(f"Errore nel recupero dati TMT: {e}")
        return pd.DataFrame()

def check_turno():
    """Determina il turno attuale in base all'ora"""
    ora_attuale = datetime.now().time()
    if time(8, 0) <= ora_attuale < time(20, 0):
        return "Diurno (08-20)", time(8, 0), time(20, 0)
    else:
        return "Notturno (20-08)", time(20, 0), time(8, 0)

# --- INTERFACCIA STREAMLIT ---

st.title("🚢 Monitor Manovre Rimorchiatore")

# Barra superiore con Refresh e Info Turno
col1, col2, col3 = st.columns([2, 2, 2])

with col1:
    if st.button("🔄 AGGIORNA DATI"):
        st.rerun()

turno_nome, inizio_t, fine_t = check_turno()

with col2:
    st.info(f"Turno Corrente: **{turno_nome}**")

with col3:
    selezione_turno = st.radio(
        "Cosa vuoi vedere?",
        ["Turno Attuale", "Prossimo Turno"],
        horizontal=True
    )

st.divider()

# Simulazione o recupero dati reali
with st.spinner("Pescando dati da TMT..."):
    dati_tmt = fetch_tmt_data()

if not dati_tmt.empty:
    st.subheader("Navi Container (TMT)")
    
    # Mostriamo la tabella grezza per ora per capire come arrivano i dati
    # Nelle fasi successive filtreremo per ETB/ETD e per l'orario di turno scelto
    st.dataframe(dati_tmt, use_container_width=True)
    
    st.caption(f"Ultimo aggiornamento: {datetime.now().strftime('%H:%M:%S')}")
else:
    st.warning("Nessun dato trovato o problema di connessione al sito TMT.")

# --- LOGICA TURNI (IN SVILUPPO) ---
st.sidebar.header("Impostazioni Turno")
ora_manuale = st.sidebar.time_input("Simula orario attuale", datetime.now().time())
st.sidebar.write("Questa funzione servirà per testare l'app fuori orario di lavoro.")
