import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime, time

# Configurazione pagina
st.set_page_config(page_title="Monitor Manovre Trieste", layout="wide")

def fetch_tmt_data():
    """Funzione per pescare i dati dal sito TMT simulando un browser"""
    url = "https://www.trieste-marine-terminal.com/it/berthing-plan"
    
    # Header per far credere al sito che siamo un browser reale
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status() # Controlla se la pagina risponde correttamente
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Cerchiamo la tabella specifica del Berthing Plan
        table = soup.find('table', {'class': 'table'}) 
        
        if not table:
            # Prova alternativa se la classe è diversa
            table = soup.find('table')

        if table:
            # Leggiamo la tabella con pandas
            df = pd.read_html(str(table))[0]
            
            # Rinominiamo le colonne per uniformità (TMT usa Vessel, Arrival, ETB, ETD ecc.)
            # Spesso le colonne hanno spazi o nomi leggermente diversi
            df.columns = [c.strip() for c in df.columns]
            return df
        else:
            return pd.DataFrame()
            
    except Exception as e:
        st.error(f"Errore tecnico nel recupero dati: {e}")
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

# Barra superiore
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

# Recupero dati
with st.spinner("Connessione al terminal in corso..."):
    dati_tmt = fetch_tmt_data()

if not dati_tmt.empty:
    st.subheader("Situazione Navi Container (TMT)")
    
    # Visualizzazione dei dati estratti
    st.dataframe(dati_tmt, use_container_width=True)
    
    # Nota per il debug: mostriamo i nomi delle colonne trovate
    st.write(f"Colonne rilevate: {', '.join(dati_tmt.columns)}")
    
    st.caption(f"Ultimo aggiornamento: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
else:
    st.error("Il sito TMT non ha risposto. Riprova tra pochi istanti col tasto Aggiorna.")

# Sidebar per test
st.sidebar.header("Opzioni")
ora_manuale = st.sidebar.time_input("Simula orario attuale", datetime.now().time())
