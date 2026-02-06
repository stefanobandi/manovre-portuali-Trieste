import streamlit as st
import pandas as pd
from datetime import datetime, time, timedelta
import os
import glob
import time as time_module
import pytz 

# Import Selenium components
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# --- CONFIGURAZIONE ---
st.set_page_config(page_title="Monitor Manovre Porto", layout="wide", initial_sidebar_state="collapsed")
TZ_TRIESTE = pytz.timezone('Europe/Rome')

def get_ora_trieste():
    return datetime.now(TZ_TRIESTE).replace(tzinfo=None)

# --- SESSION STATE ---
if 'dati_totali' not in st.session_state:
    # Struttura fissa: 4 colonne. Nessuna sorpresa.
    st.session_state.dati_totali = pd.DataFrame(columns=['Terminal', 'Vessel', 'ETA', 'ETD'])
if 'ultimo_aggiornamento' not in st.session_state:
    st.session_state.ultimo_aggiornamento = None
if 'debug_msg_tasco' not in st.session_state:
    st.session_state.debug_msg_tasco = ""

# --- BROWSER ---
def get_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    
    download_dir = os.getcwd()
    prefs = {
        "download.default_directory": download_dir,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True
    }
    chrome_options.add_experimental_option("prefs", prefs)
    
    service = Service("/usr/bin/chromedriver")
    return webdriver.Chrome(service=service, options=chrome_options)

# --- FUNZIONI DI PULIZIA DEDICATE (RESET) ---

def clean_tmt_data(df):
    """Pulisce i dati TMT copiando solo ciò che serve in una nuova tabella."""
    if df is None or df.empty:
        return pd.DataFrame(columns=['Terminal', 'Vessel', 'ETA', 'ETD'])
    
    # 1. Pulisci intestazioni
    df.columns = [str(c).strip() for c in df.columns]
    
    # 2. Rimuovi duplicati (se ci sono due colonne Vessel, ne tiene una sola)
    df = df.loc[:, ~df.columns.duplicated()]
    
    # 3. Creiamo la destinazione pulita
    clean_df = pd.DataFrame()
    clean_df['Terminal'] = ['TMT (Molo VII)'] * len(df)
    
    # 4. Copia Dati (Senza rinominare l'originale, copiamo e basta)
    # TMT ha 'Vessel', 'ETB', 'ETD'
    
    # Vessel
    if 'Vessel' in df.columns:
        clean_df['Vessel'] = df['Vessel']
    else:
        clean_df['Vessel'] = "Sconosciuto"
        
    # ETA (che nel TMT si chiama ETB)
    if 'ETB' in df.columns:
        clean_df['ETA'] = pd.to_datetime(df['ETB'], dayfirst=True, errors='coerce')
    else:
        clean_df['ETA'] = pd.NaT
        
    # ETD
    if 'ETD' in df.columns:
        clean_df['ETD'] = pd.to_datetime(df['ETD'], dayfirst=True, errors='coerce')
    else:
        clean_df['ETD'] = pd.NaT
        
    return clean_df

def clean_tasco_data(df):
    """Pulisce i dati TASCO/SIOT copiando solo ciò che serve."""
    if df is None or df.empty:
        return pd.DataFrame(columns=['Terminal', 'Vessel', 'ETA', 'ETD'])
    
    # 1. Drop righe vuote
    df = df.dropna(how='all')
    
    # 2. Pulisci intestazioni
    df.columns = [str(c).replace("?","").replace(".","").strip() for c in df.columns]
    df = df.loc[:, ~df.columns.duplicated()]
    
    # 3. Creiamo la destinazione pulita
    clean_df = pd.DataFrame()
    clean_df['Terminal'] = ['SIOT (Petroli)'] * len(df)
    
    # 4. Copia Dati
    # TASCO ha 'Tanker Name' (o Tanker), 'POB', 'TLB'
    
    # Vessel
    if 'Tanker Name' in df.columns:
        clean_df['Vessel'] = df['Tanker Name']
    elif 'Tanker' in df.columns:
        clean_df['Vessel'] = df['Tanker']
    else:
        clean_df['Vessel'] = "Sconosciuto"

    # Preparazione date
    current_year = get_ora_trieste().year
    def parse_date(val):
        val = str(val).strip()
        if not val or val.lower() == 'nan': return pd.NaT
        try:
            if isinstance(val, str) and val.count('.') >= 2:
                return pd.to_datetime(f"{val}{current_year}", format="%d.%m.%Y", dayfirst=True)
        except: pass
        return pd.to_datetime(val, errors='coerce')

    # ETA (che nel TASCO si chiama POB)
    if 'POB' in df.columns:
        clean_df['ETA'] = df['POB'].apply(parse_date)
    else:
        clean_df['ETA'] = pd.NaT

    # ETD (che nel TASCO si chiama TLB) - 30 MINUTI
    if 'TLB' in df.columns:
        raw_dates = df['TLB'].apply(parse_date)
        clean_df['ETD'] = raw_dates - timedelta(minutes=30)
    else:
        clean_df['ETD'] = pd.NaT
        
    return clean_df

# --- 1. SCRAPING TMT ---
def fetch_tmt_data(driver):
    url = "https://www.trieste-marine-terminal.com/it"
    try:
        driver.get(url)
        time_module.sleep(3)
        dfs = pd.read_html(driver.page_source, match="Vessel", flavor='html5lib')
        if len(dfs) > 0:
            # Passiamo subito alla funzione di pulizia dedicata
            return clean_tmt_data(dfs[0])
    except Exception as e:
        print(f"Errore TMT: {e}")
    return clean_tmt_data(None)

# --- 2. SCRAPING TASCO ---
def fetch_tasco_data(driver):
    st.session_state.debug_msg_tasco = ""
    if "tasco" not in st.secrets:
        st.error("⚠️ Configura i Secrets [tasco]!")
        return clean_tasco_data(None)

    login_url = "https://tasco.tal-oil.com/ui/login"
    
    st.toast("Accesso SIOT... (1/4)", icon="⛽")
    
    try:
        wait = WebDriverWait(driver, 20)
        
        # LOGIN
        driver.get(login_url)
        pass_input = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='password']")))
        try:
            user_input = driver.find_element(By.XPATH, "//input[preceding::*[contains(text(), 'Login name')]]")
        except:
            user_input = driver.find_element(By.CSS_SELECTOR, "input[type='text']")

        user_input.clear()
        user_input.send_keys(st.secrets["tasco"]["username"])
        pass_input.clear()
        pass_input.send_keys(st.secrets["tasco"]["password"])
        pass_input.send_keys(Keys.RETURN)
        time_module.sleep(5)

        # NAVIGAZIONE
        st.toast("Navigazione...", icon="🖱️")
        try:
            btn_timos = wait.until(EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), 'Access to TIMOS')]")))
            btn_timos.click()
            time_module.sleep(5)
            btn_bb = wait.until(EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), 'Terminal Basic Blackboard')]")))
            btn_bb.click()
            time_module.sleep(8)
        except:
            return clean_tasco_data(None)

        # EXPORT
        st.toast("Scarico Excel... (4/4)", icon="📥")
        for f in glob.glob("*.xls*"):
            try: os.remove(f)
            except: pass

        try:
            btn_export = wait.until(EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), 'Export')]")))
            btn_export.click()
        except:
            return clean_tasco_data(None)
            
        # ATTESA FILE
        file_scaricato = None
        for i in range(15):
            files = glob.glob("*.xls*")
            if files:
                file_scaricato = files[0]
                break
            time_module.sleep(1)
            
        if not file_scaricato:
            return clean_tasco_data(None)
            
        st.session_state.debug_msg_tasco = f"File elaborato: {os.path.basename(file_scaricato)}"
        
        df = pd.read_excel(file_scaricato)
        try: os.remove(file_scaricato)
        except: pass
        
        return clean_tasco_data(df)
            
    except Exception as e:
        return clean_tasco_data(None)

# --- AGGIORNAMENTO ---
def aggiorna_dati():
    with st.spinner("Scaricamento dati in corso... (Attendi circa 30s)"):
        driver = get_driver()
        df_tmt = fetch_tmt_data(driver)
        df_tasco = fetch_tasco_data(driver)
        driver.quit()

        frames = []
        if not df_tmt.empty: frames.append(df_tmt)
        if not df_tasco.empty: frames.append(df_tasco)
        
        if frames:
            # Ora i dataframe sono garantiti avere le stesse 4 colonne: Terminal, Vessel, ETA, ETD
            st.session_state.dati_totali = pd.concat(frames, ignore_index=True)
            st.session_state.ultimo_aggiornamento = get_ora_trieste().strftime("%H:%M:%S")
        else:
            st.session_state.dati_totali = pd.DataFrame(columns=['Terminal', 'Vessel', 'ETA', 'ETD'])

# --- LOGICA TURNI ---
def get_orari_turno(ora_riferimento, tipo_visualizzazione):
    if ora_riferimento.tzinfo is not None:
        ora_riferimento = ora_riferimento.replace(tzinfo=None)
        
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

# --- STILE ---
def style_manovre(row):
    styles = [''] * len(row.index)
    def set_style(col_name, css):
        try:
            idx = row.index.get_loc(col_name)
            styles[idx] = css
        except KeyError: pass

    if 'ARRIVO' in str(row['Tipo']):
        set_style('Tipo', 'background-color: #d4edda; color: black; font-weight: bold')
        set_style('ETA', 'background-color: #d4edda; color: #155724; font-weight: bold; border: 2px solid #155724')
        
    if 'PARTENZA' in str(row['Tipo']):
        set_style('Tipo', 'background-color: #f8d7da; color: black; font-weight: bold')
        set_style('ETD', 'background-color: #f8d7da; color: #721c24; font-weight: bold; border: 2px solid #721c24')
        
    return styles

# --- INTERFACCIA ---
st.title("⚓ Monitor Manovre Porto di Trieste")

with st.sidebar:
    st.header("🔧 Simulazione (Fuso Trieste)")
    ora_default = get_ora_trieste()
    ora_simulata = st.time_input("Ora", ora_default.time())
    data_simulata = st.date_input("Data", ora_default.date())
    dt_rif = datetime.combine(data_simulata, ora_simulata)

col_btn, col_info, col_sel = st.columns([1, 2, 2])

with col_btn:
    if st.button("🔄 AGGIORNA SCARICANDO I DATI", type="primary"):
        aggiorna_dati()

if st.session_state.dati_totali.empty and st.session_state.ultimo_aggiornamento is None:
    aggiorna_dati()

with col_sel:
    scelta_vista = st.radio("Filtra per:", ["Turno Attuale", "Prossimo Turno"], horizontal=True)

start, end, nome_turno = get_orari_turno(dt_rif, scelta_vista)

with col_info:
    st.info(f"Turno: **{nome_turno}**\nFiltro: {start.strftime('%H:%M')} - {end.strftime('%H:%M')}")
    if st.session_state.ultimo_aggiornamento:
        st.caption(f"Ultimo scaricamento: {st.session_state.ultimo_aggiornamento} (Ora TS)")

st.divider()

# --- VISUALIZZAZIONE ---
df_total = st.session_state.dati_totali

if not df_total.empty:
    if 'ETA' in df_total.columns and 'ETD' in df_total.columns:
        mask = ((df_total['ETA'] >= start) & (df_total['ETA'] <= end)) | ((df_total['ETD'] >= start) & (df_total['ETD'] <= end))
        df_filtrato = df_total[mask].copy()
    else:
        df_filtrato = pd.DataFrame()
    
    if not df_filtrato.empty:
        
        def processa_riga(row):
            azioni = []
            orari_rilevanti = []
            
            if pd.notnull(row['ETA']) and start <= row['ETA'] <= end: 
                azioni.append("ARRIVO")
                orari_rilevanti.append(row['ETA'])
                
            if pd.notnull(row['ETD']) and start <= row['ETD'] <= end: 
                azioni.append("PARTENZA")
                orari_rilevanti.append(row['ETD'])
            
            tipo = " + ".join(azioni) if azioni else "-"
            sort_key = min(orari_rilevanti) if orari_rilevanti else pd.NaT
            
            return pd.Series([tipo, sort_key])

        df_filtrato[['Tipo', 'SortKey']] = df_filtrato.apply(processa_riga, axis=1)
        df_filtrato = df_filtrato.sort_values(by='SortKey')
        
        # MOSTRA SOLO COLONNE UTILI
        cols_desired = ['Terminal', 'Tipo', 'Vessel', 'ETA', 'ETD']
        for c in cols_desired:
            if c not in df_filtrato.columns: df_filtrato[c] = ""
                
        st.success(f"Trovate {len(df_filtrato)} manovre totali!")
        
        st.dataframe(
            df_filtrato[cols_desired].style.apply(style_manovre, axis=1).format({
                'ETA': lambda t: t.strftime("%d/%m %H:%M") if pd.notnull(t) else "-",
                'ETD': lambda t: t.strftime("%d/%m %H:%M") if pd.notnull(t) else "-"
            }),
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("Nessuna manovra prevista nel turno.")

    st.write("---")
    
    c1, c2 = st.columns(2)
    with c1:
        with st.expander("Tabella Completa TMT"):
            st.dataframe(df_total[df_total['Terminal'].str.contains("TMT")])
    with c2:
        with st.expander("Tabella Completa SIOT"):
            st.write(f"ℹ️ {st.session_state.debug_msg_tasco}")
            st.dataframe(df_total[df_total['Terminal'].str.contains("SIOT")])
else:
    if st.session_state.ultimo_aggiornamento:
        st.warning("Nessun dato trovato sui siti.")
    else:
        st.info("Premi il pulsante per scaricare i dati.")
