import streamlit as st
import pandas as pd
import requests
from datetime import datetime, time, timedelta
import urllib3

# Disabilita gli avvisi di sicurezza SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

st.set_page_config(page_title="Monitor Manovre TMT", layout="wide")

# --- FUNZIONI DI SCRAPING ---
def fetch_tmt_home_data():
    url = "https://www.trieste-marine-terminal.com/it"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Referer': 'https://www.google.com/'
    }
    
    try:
        session = requests.Session()
        response = session.get(url, headers=headers, timeout=20, verify=False)
        
        if response.status_code != 200:
            st.error(f"Il sito ha risposto con codice: {response.status_code}")
            return pd.DataFrame()

        # MODIFICA QUI: Aggiunto flavor='html5lib' per usare la nuova libreria
        dfs = pd.read_html(response.text, match="Vessel", flavor='html5lib')
        
        if len(dfs) > 0:
            df = dfs[0]
            
            # Pulizia nomi colonne
            df.columns = [str(c).strip() for c in df.columns]
            
            # Converti le date
            for col in ['ETB', 'ETD']:
                if col in df.columns:
                    df[col] = pd.to_datetime(df[col], dayfirst=True, errors='coerce')
            
            return df
        else:
            st.warning("Connessione riuscita, ma non ho trovato tabelle con la parola 'Vessel'.")
            return pd.DataFrame()

    except Exception as e:
        st.error(f"ERRORE: {str(e)}")
        return pd.DataFrame()

# --- LOGICA TURNI ---
def get_orari_turno(ora_riferimento, tipo_visualizzazione):
    t_mattina_start = ora_riferimento.replace(hour=8, minute=0, second=0, microsecond=0)
    t_sera_start = ora_riferimento.replace(hour=20, minute=0, second=0, microsecond=0)
    
    if 8 <= ora_riferimento.hour < 20:
        attuale_start, attuale_end = t_mattina_start, t_sera_start
        prossimo_start, prossimo_end = t_sera_start, t_sera_start + timedelta(hours=12)
        nome_attuale = "Diurno (08-20)"
    else:
        if ora_riferimento.hour >= 20:
            attuale_start = t_sera_start
            attuale_end = t_sera_start + timedelta(hours=12)
        else:
            attuale_start = t_sera_start - timedelta(days=1)
            attuale_end = t_mattina_start
        prossimo_start, prossimo_end = attuale_end, attuale_end + timedelta(hours=12)
        nome_attuale = "Notturno (20-08)"

    if tipo_visualizzazione == "Turno Attuale":
        return attuale_start, attuale_end, nome_attuale
    else:
        return prossimo_start, prossimo_end, "Prossimo Turno"

# --- INTERFACCIA ---
st.title("⚓ Monitor Manovre TMT")

col_btn, col_info = st.columns([1, 3])
with col_btn:
    if st.button("🔄 AGGIORNA", type="primary"):
        st.rerun()

# Sidebar Debug
st.sidebar.header("🔧 Simulazione")
ora_simulata = st.sidebar.time_input("Ora", datetime.now().time())
data_simulata = st.sidebar.date_input("Data", datetime.now().date())
dt_rif = datetime.combine(data_simulata, ora_simulata)

scelta = st.sidebar.radio("Turno:", ["Turno Attuale", "Prossimo Turno"])

# Logica
start, end, nome = get_orari_turno(dt_rif, scelta)
with col_info:
    st.info(f"Turno: {nome} | Filtro: {start.strftime('%H:%M')} - {end.strftime('%H:%M')}")

st.divider()

# Esecuzione
with st.spinner("Connessione al TMT in corso..."):
    df = fetch_tmt_home_data()

if not df.empty:
    # Filtro Manovre
    mask = ((df['ETB'] >= start) & (df['ETB'] <= end)) | ((df['ETD'] >= start) & (df['ETD'] <= end))
    df_filtrato = df[mask].copy()
    
    if not df_filtrato.empty:
        st.success(f"Trovate {len(df_filtrato)} manovre!")
        # Evidenziamo arrivi e partenze
        st.dataframe(df_filtrato, use_container_width=True)
    else:
        st.info("Nessuna nave in movimento nel tuo orario.")
        
    with st.expander("Vedi tabella completa (Tutte le navi)"):
        st.dataframe(df)
