import streamlit as st
import pandas as pd
from datetime import datetime, time, timedelta
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
import time as time_module

# --- CONFIGURAZIONE ---
st.set_page_config(page_title="Monitor Manovre TMT", layout="wide")

# --- FUNZIONE SCRAPING CON SELENIUM ---
def fetch_tmt_data_selenium():
    url = "https://www.trieste-marine-terminal.com/it"
    
    # Opzioni per rendere il browser compatibile con l'ambiente server Linux
    chrome_options = Options()
    chrome_options.add_argument("--headless") # Esegue senza interfaccia grafica
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    
    try:
        # Usiamo il driver di sistema installato via packages.txt
        service = Service("/usr/bin/chromedriver")
        
        driver = webdriver.Chrome(service=service, options=chrome_options)
        
        driver.get(url)
        
        # Aspettiamo 5 secondi che il sito carichi i dati
        time_module.sleep(5)
        
        # Leggiamo l'HTML completo
        html_completo = driver.page_source
        driver.quit()
        
        # Cerchiamo le tabelle nell'HTML completo
        dfs = pd.read_html(html_completo, match="Vessel", flavor='html5lib')
        
        if len(dfs) > 0:
            df = dfs[0]
            # Pulizia nomi colonne
            df.columns = [str(c).strip() for c in df.columns]
            
            # Conversione Date (formato dd-mm-yyyy HH:MM:SS)
            for col in ['ETB', 'ETD']:
                if col in df.columns:
                    df[col] = pd.to_datetime(df[col], dayfirst=True, errors='coerce')
            return df
        else:
            return pd.DataFrame()

    except Exception as e:
        st.error(f"Errore Browser: {e}")
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

# --- FUNZIONE DI STILE (COLORI) ---
def style_manovre(row):
    # Creiamo una lista di stili vuota lunga quanto le colonne
    styles = [''] * len(row.index)
    
    # Helper per trovare l'indice della colonna
    def set_style(col_name, css):
        try:
            idx = row.index.get_loc(col_name)
            styles[idx] = css
        except KeyError:
            pass # Se la colonna non c'è, ignora

    # Logica Colori
    if 'ARRIVO' in str(row['Tipo']):
        # Colora la cella del TIPO (Verde chiaro)
        set_style('Tipo', 'background-color: #d4edda; color: black; font-weight: bold')
        # Colora la cella ETB (Verde più scuro sul testo)
        set_style('ETB', 'background-color: #d4edda; color: #155724; font-weight: bold; border: 2px solid #155724')
        
    if 'PARTENZA' in str(row['Tipo']):
        # Colora la cella del TIPO (Rosso chiaro)
        set_style('Tipo', 'background-color: #f8d7da; color: black; font-weight: bold')
        # Colora la cella ETD (Rosso più scuro sul testo)
        set_style('ETD', 'background-color: #f8d7da; color: #721c24; font-weight: bold; border: 2px solid #721c24')
        
    return styles

# --- INTERFACCIA ---
st.title("⚓ Monitor Manovre TMT (Live)")

# Sidebar Debug
st.sidebar.header("🔧 Simulazione")
ora_simulata = st.sidebar.time_input("Ora Simulazione", datetime.now().time())
data_simulata = st.sidebar.date_input("Data Simulazione", datetime.now().date())
dt_rif = datetime.combine(data_simulata, ora_simulata)

col_btn, col_info, col_sel = st.columns([1, 2, 2])

with col_btn:
    if st.button("🔄 AGGIORNA DATI", type="primary"):
        st.rerun()

with col_sel:
    scelta_vista = st.radio("Filtra per:", ["Turno Attuale", "Prossimo Turno"], horizontal=True)

# Calcolo orari
start, end, nome_turno = get_orari_turno(dt_rif, scelta_vista)

with col_info:
    st.info(f"Turno: **{nome_turno}**\nFiltro: {start.strftime('%H:%M')} - {end.strftime('%H:%M')}")

st.divider()

# Esecuzione
with st.spinner("Scaricamento dati in corso..."):
    df = fetch_tmt_data_selenium()

if not df.empty:
    # 1. Filtro Temporale
    mask = ((df['ETB'] >= start) & (df['ETB'] <= end)) | ((df['ETD'] >= start) & (df['ETD'] <= end))
    df_filtrato = df[mask].copy()
    
    # 2. Creazione colonna "Azione"
    def get_azione(row):
        azioni = []
        if start <= row['ETB'] <= end: azioni.append("ARRIVO")
        if start <= row['ETD'] <= end: azioni.append("PARTENZA")
        return " + ".join(azioni) if azioni else "-"
        
    if not df_filtrato.empty:
        df_filtrato['Tipo'] = df_filtrato.apply(get_azione, axis=1)
        
        # Selezione colonne utili
        colonne_utili = ['Tipo', 'Vessel', 'ETB', 'ETD', 'Agent', 'Viaggio']
        colonne_finali = [c for c in colonne_utili if c in df_filtrato.columns]
        
        st.success(f"Trovate {len(df_filtrato)} manovre operative!")
        
        # Applicazione Stili
        st.dataframe(
            df_filtrato[colonne_finali].style.apply(style_manovre, axis=1).format({
                'ETB': lambda t: t.strftime("%d/%m %H:%M") if pd.notnull(t) else "-",
                'ETD': lambda t: t.strftime("%d/%m %H:%M") if pd.notnull(t) else "-"
            }),
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("Nessuna manovra (Arrivo/Partenza) prevista in questo turno.")

    with st.expander("Visualizza Tabella Completa (Tutte le navi)"):
        st.dataframe(df)
else:
    st.error("Non sono riuscito a scaricare la tabella. Se vedi questo errore, assicurati che il file packages.txt esista.")
