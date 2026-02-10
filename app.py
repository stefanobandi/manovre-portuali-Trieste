import streamlit as st
import pandas as pd
from datetime import datetime, time, timedelta
import os
import glob
import time as time_module
import pytz 
import requests
import streamlit.components.v1 as components # NUOVO IMPORT PER LA MAPPA

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

# --- SISTEMA DI SICUREZZA (LOGIN) ---
def check_password():
    if st.session_state.get("password_correct", False):
        return True

    st.markdown("## 🔒 Accesso Riservato Monitoraggio")
    st.write("Inserisci la password per accedere ai dati portuali.")
    pwd_input = st.text_input("Password:", type="password")
    
    if st.button("Accedi"):
        if "general" in st.secrets and pwd_input == st.secrets["general"]["app_password"]:
            st.session_state["password_correct"] = True
            st.rerun()
        elif "general" not in st.secrets:
            st.error("ERRORE CONFIGURAZIONE: Manca la sezione [general] nei Secrets.")
        else:
            st.error("Password errata.")
            
    return False

if not check_password():
    st.stop()

# =========================================================
# APP VERA E PROPRIA
# =========================================================

def get_ora_trieste():
    return datetime.now(TZ_TRIESTE).replace(tzinfo=None)

# --- SESSION STATE ---
if 'dati_totali' not in st.session_state:
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

# --- LOGICA DI RICOSTRUZIONE ---
def build_clean_df(source_data, terminal_input):
    df = pd.DataFrame()
    n_rows = len(source_data.get('Vessel', []))
    
    if isinstance(terminal_input, list):
        if len(terminal_input) == n_rows:
            df['Terminal'] = terminal_input
        else:
            df['Terminal'] = ["SIOT (N.D.)"] * n_rows
    else:
        df['Terminal'] = [terminal_input] * n_rows

    df['Vessel'] = source_data.get('Vessel', [""] * n_rows)
    df['ETA'] = source_data.get('ETA', [pd.NaT] * n_rows)
    df['ETD'] = source_data.get('ETD', [pd.NaT] * n_rows)
    
    return df

# --- 1. SCRAPING TMT ---
def fetch_tmt_data(driver):
    url = "https://www.trieste-marine-terminal.com/it"
    try:
        driver.get(url)
        time_module.sleep(2)
        dfs = pd.read_html(driver.page_source, match="Vessel", flavor='html5lib')
        if len(dfs) > 0:
            raw_df = dfs[0]
            raw_df.columns = [str(c).strip() for c in raw_df.columns]
            
            vessels = raw_df['Vessel'].tolist() if 'Vessel' in raw_df.columns else []
            
            if 'ETB' in raw_df.columns:
                etas = pd.to_datetime(raw_df['ETB'], dayfirst=True, errors='coerce').tolist()
            else:
                etas = [pd.NaT] * len(vessels)
                
            if 'ETD' in raw_df.columns:
                etds = pd.to_datetime(raw_df['ETD'], dayfirst=True, errors='coerce').tolist()
            else:
                etds = [pd.NaT] * len(vessels)
            
            data_dict = {'Vessel': vessels, 'ETA': etas, 'ETD': etds}
            return build_clean_df(data_dict, 'TMT (Molo VII)')
            
    except Exception as e:
        print(f"Errore TMT: {e}")
    
    return pd.DataFrame(columns=['Terminal', 'Vessel', 'ETA', 'ETD'])

# --- 2. SCRAPING TASCO ---
def fetch_tasco_data(driver, status_container=None):
    def log(msg):
        if status_container:
            status_container.write(msg)

    st.session_state.debug_msg_tasco = "" 
    if "tasco" not in st.secrets:
        st.error("⚠️ Configura i Secrets [tasco]!")
        return pd.DataFrame(columns=['Terminal', 'Vessel', 'ETA', 'ETD'])

    login_url = "https://tasco.tal-oil.com/ui/login"
    
    try:
        wait = WebDriverWait(driver, 20)
        
        # LOGIN
        log("🔑 Accesso SIOT in corso...")
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
        time_module.sleep(4)
        log("✅ Login effettuato")

        # NAVIGAZIONE
        log("🧭 Navigazione menu TIMOS...")
        try:
            btn_timos = wait.until(EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), 'Access to TIMOS')]")))
            btn_timos.click()
            time_module.sleep(3)
            btn_bb = wait.until(EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), 'Terminal Basic Blackboard')]")))
            btn_bb.click()
            time_module.sleep(5)
            log("✅ Tabella raggiunta")
        except:
            log("❌ Errore navigazione menu")
            return pd.DataFrame(columns=['Terminal', 'Vessel', 'ETA', 'ETD'])

        # EXPORT
        log("📥 Scaricamento file Excel...")
        for f in glob.glob("*.xls*"):
            try: os.remove(f)
            except: pass

        try:
            btn_export = wait.until(EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), 'Export')]")))
            btn_export.click()
        except:
            log("❌ Tasto Export non trovato")
            return pd.DataFrame(columns=['Terminal', 'Vessel', 'ETA', 'ETD'])
            
        # DOWNLOAD
        file_scaricato = None
        for i in range(15):
            files = glob.glob("*.xls*")
            if files:
                file_scaricato = files[0]
                break
            time_module.sleep(1)
            
        if not file_scaricato:
            log("❌ Timeout download")
            return pd.DataFrame(columns=['Terminal', 'Vessel', 'ETA', 'ETD'])
        
        log(f"✅ File ricevuto: {os.path.basename(file_scaricato)}")
        st.session_state.debug_msg_tasco = f"File elaborato: {os.path.basename(file_scaricato)}"
        
        raw_df = pd.read_excel(file_scaricato)
        try: os.remove(file_scaricato)
        except: pass
        
        return process_tasco_raw(raw_df)
            
    except Exception as e:
        log(f"❌ Errore critico TASCO: {str(e)}")
        return pd.DataFrame(columns=['Terminal', 'Vessel', 'ETA', 'ETD'])

def process_tasco_raw(raw_df):
    raw_df = raw_df.dropna(how='all')
    raw_df.columns = [str(c).replace("?","").replace(".","").strip() for c in raw_df.columns]
    
    v_col = None
    if 'Tanker Name' in raw_df.columns: v_col = 'Tanker Name'
    elif 'Tanker' in raw_df.columns: v_col = 'Tanker'
    vessels = raw_df[v_col].tolist() if v_col else ["Sconosciuto"] * len(raw_df)

    b_col = None
    if 'Berth' in raw_df.columns: b_col = 'Berth'
    elif 'Pontile' in raw_df.columns: b_col = 'Pontile'
    
    terminal_labels = []
    if b_col:
        def format_berth(val):
            if pd.isna(val) or str(val).strip() == "":
                return "N.D."
            try:
                return str(int(float(val)))
            except:
                return str(val)

        berth_values = raw_df[b_col].apply(format_berth).tolist()
        terminal_labels = [f"SIOT ({b})" for b in berth_values]
    else:
        terminal_labels = ["SIOT (N.D.)"] * len(vessels)

    current_year = get_ora_trieste().year
    def parse_tasco_date(val):
        val = str(val).strip()
        if not val or val.lower() == 'nan': return pd.NaT
        try:
            if isinstance(val, str) and val.count('.') >= 2:
                return pd.to_datetime(f"{val}{current_year}", format="%d.%m.%Y", dayfirst=True)
        except: pass
        return pd.to_datetime(val, errors='coerce')

    etas = []
    if 'POB' in raw_df.columns:
        etas = raw_df['POB'].apply(parse_tasco_date).tolist()
    else:
        etas = [pd.NaT] * len(vessels)

    etds = []
    if 'TLB' in raw_df.columns:
        temp_etds = raw_df['TLB'].apply(parse_tasco_date)
        etds = [x - timedelta(minutes=30) if pd.notnull(x) else pd.NaT for x in temp_etds]
    else:
        etds = [pd.NaT] * len(vessels)

    data_dict = {'Vessel': vessels, 'ETA': etas, 'ETD': etds}
    return build_clean_df(data_dict, terminal_labels)

# --- AGGIORNAMENTO ---
def aggiorna_dati():
    with st.status("Aggiornamento dati in corso...", expanded=True) as status:
        st.write("🔌 Avvio Browser remoto...")
        driver = get_driver()
        st.write("✅ Browser attivo")
        
        st.write("🛳️ Lettura dati TMT...")
        df_tmt = fetch_tmt_data(driver)
        st.write(f"✅ TMT completato ({len(df_tmt)} navi trovate)")
        
        df_tasco = fetch_tasco_data(driver, status_container=status)
        
        driver.quit()

        frames = []
        if not df_tmt.empty: frames.append(df_tmt)
        if not df_tasco.empty: frames.append(df_tasco)
        
        if frames:
            st.session_state.dati_totali = pd.concat(frames, ignore_index=True)
            st.session_state.ultimo_aggiornamento = get_ora_trieste().strftime("%H:%M:%S")
        else:
            st.session_state.dati_totali = pd.DataFrame(columns=['Terminal', 'Vessel', 'ETA', 'ETD'])
            
        status.update(label="Scaricamento Completato!", state="complete", expanded=False)

# --- NUOVA LOGICA TURNI ---
def calcola_turno_attuale(ora_riferimento):
    t_mattina_start = ora_riferimento.replace(hour=8, minute=0, second=0, microsecond=0)
    t_sera_start = ora_riferimento.replace(hour=20, minute=0, second=0, microsecond=0)
    
    if 8 <= ora_riferimento.hour < 20:
        start = t_mattina_start
        end = t_sera_start
        label = f"Diurno (08-20) del {start.strftime('%d/%m/%Y')}"
    else:
        if ora_riferimento.hour >= 20:
            start = t_sera_start
            end = t_sera_start + timedelta(hours=12)
        else:
            start = t_sera_start - timedelta(days=1)
            end = t_mattina_start
        
        label = f"Notturno (20-08) del {start.strftime('%d/%m/%Y')}"
    
    return start, end, label

def genera_opzioni_future(ora_riferimento):
    opzioni = {}
    _, fine_turno_attuale, _ = calcola_turno_attuale(ora_riferimento)
    cursore = fine_turno_attuale
    
    for _ in range(6):
        start = cursore
        end = cursore + timedelta(hours=12)
        if start.hour == 8:
            tipo = "Diurno (08-20)" 
            data_str = start.strftime('%d/%m/%Y')
        else: 
            tipo = "Notturno (20-08)"
            data_str = start.strftime('%d/%m/%Y')
            
        label = f"{tipo} del {data_str}"
        opzioni[label] = (start, end)
        cursore = end
    return opzioni

# --- FUNZIONE METEO ---
def get_meteo_turno(start_dt, end_dt):
    lat = 45.649  # Trieste
    lon = 13.778
    url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&hourly=temperature_2m,precipitation_probability,weathercode,windspeed_10m,windgusts_10m&timezone=auto"
    
    try:
        response = requests.get(url, timeout=5)
        data = response.json()
        
        if 'hourly' not in data:
            return None

        df_meteo = pd.DataFrame(data['hourly'])
        df_meteo['time'] = pd.to_datetime(df_meteo['time'])
        
        start_naive = start_dt.replace(tzinfo=None)
        end_naive = end_dt.replace(tzinfo=None)
        
        mask = (df_meteo['time'] >= start_naive) & (df_meteo['time'] <= end_naive)
        df_turno = df_meteo[mask]
        
        if df_turno.empty:
            return None
            
        t_min = df_turno['temperature_2m'].min()
        t_max = df_turno['temperature_2m'].max()
        wind_max_kt = round(df_turno['windspeed_10m'].max() * 0.539957, 1)
        gust_max_kt = round(df_turno['windgusts_10m'].max() * 0.539957, 1)
        code = df_turno['weathercode'].max()
        
        icon, desc = "☁️", "Variabile"
        if code == 0: icon, desc = "☀️", "Sereno"
        elif code in [1, 2, 3]: icon, desc = "⛅", "Nuvoloso"
        elif code in [45, 48]: icon, desc = "🌫️", "Nebbia"
        elif code in [51, 53, 55, 61, 63, 65]: icon, desc = "🌧️", "Pioggia"
        elif code in [71, 73, 75, 77]: icon, desc = "❄️", "Neve"
        elif code >= 95: icon, desc = "⛈️", "Temporale"
        
        return {
            "temp": f"{t_min:.0f}° / {t_max:.0f}°",
            "vento": f"{wind_max_kt} kt (Raff: {gust_max_kt})",
            "meteo": f"{icon} {desc}"
        }
        
    except Exception as e:
        return None

# --- STILE E COLORI ---
def style_manovre(row):
    styles = [''] * len(row.index)
    now = get_ora_trieste()
    
    is_past = False
    if pd.notnull(row['SortKey']):
        if row['SortKey'] < now:
            is_past = True

    base_style = 'color: #a0a0a0;' if is_past else '' 
    
    def set_style(col_name, css):
        try:
            idx = row.index.get_loc(col_name)
            styles[idx] = f"{base_style} {css}"
        except KeyError: pass

    if is_past:
        for i in range(len(styles)):
            styles[i] = base_style

    bg_arrivo = '#f2f9f4' if is_past else '#d4edda'
    col_arrivo = '#a0a0a0' if is_past else '#155724' 
    border_arrivo = '#a0a0a0' if is_past else '#155724'

    bg_partenza = '#fdf2f4' if is_past else '#f8d7da'
    col_partenza = '#a0a0a0' if is_past else '#721c24'
    border_partenza = '#a0a0a0' if is_past else '#721c24'

    if 'ARRIVO' in str(row['Tipo']):
        set_style('ARRIVI', f'background-color: {bg_arrivo}; color: {col_arrivo}; font-weight: bold; border: 2px solid {border_arrivo}')
        
    if 'PARTENZA' in str(row['Tipo']):
        set_style('PARTENZE', f'background-color: {bg_partenza}; color: {col_partenza}; font-weight: bold; border: 2px solid {border_partenza}')
        
    return styles

# --- INTERFACCIA ---
st.title("⚓ Monitor Manovre Porto di Trieste 🚢")
st.markdown("I dati vengono prelevati dai siti web TMT e Tasco pertanto includono solo movimenti container e petroliere.")

col_btn, col_sel_mode, col_sel_drop = st.columns([1, 1, 2])

with col_btn:
    if st.button("🔄 AGGIORNA SCARICANDO I DATI", type="primary"):
        aggiorna_dati()

# Caricamento iniziale automatico
if st.session_state.dati_totali.empty and st.session_state.ultimo_aggiornamento is None:
    aggiorna_dati()

# Gestione Selezione Turni
ora_reale = get_ora_trieste()

with col_sel_mode:
    modo_selezione = st.radio("Seleziona vista:", ["Turno attuale", "Turno futuro"], horizontal=True)

start_filter = None
end_filter = None
banner_text = ""

if modo_selezione == "Turno attuale":
    start_filter, end_filter, label_turno = calcola_turno_attuale(ora_reale)
    banner_text = f"**Turno attuale - {label_turno}**"
else:
    opzioni_future = genera_opzioni_future(ora_reale)
    with col_sel_drop:
        scelta_futura = st.selectbox("Seleziona turno futuro:", list(opzioni_future.keys()))
    if scelta_futura:
        start_filter, end_filter = opzioni_future[scelta_futura]
        banner_text = f"**Turno futuro - {scelta_futura}**"

# --- BANNER INFORMATIVO ---
st.info(banner_text)

# --- BLOCCO METEO ---
if start_filter and end_filter:
    meteo = get_meteo_turno(start_filter, end_filter)
    if meteo:
        m1, m2, m3 = st.columns(3)
        m1.metric("🌡️ Temperatura (Min/Max)", meteo["temp"])
        m2.metric("💨 Vento Max (Nodi)", meteo["vento"])
        m3.metric("☔ Previsione", meteo["meteo"])

if st.session_state.ultimo_aggiornamento:
    st.caption(f"Ultimo scaricamento: {st.session_state.ultimo_aggiornamento} (Ora Locale)")

st.divider()

# --- VISUALIZZAZIONE E FILTRO DATI ---
df_total = st.session_state.dati_totali

if not df_total.empty and start_filter and end_filter:
    if 'ETA' in df_total.columns and 'ETD' in df_total.columns:
        mask = ((df_total['ETA'] >= start_filter) & (df_total['ETA'] <= end_filter)) | \
               ((df_total['ETD'] >= start_filter) & (df_total['ETD'] <= end_filter))
        df_filtrato = df_total[mask].copy()
    else:
        df_filtrato = pd.DataFrame()
    
    if not df_filtrato.empty:
        
        def processa_riga(row):
            azioni = []
            orari_rilevanti = []
            
            if pd.notnull(row['ETA']) and start_filter <= row['ETA'] <= end_filter: 
                azioni.append("ARRIVO")
                orari_rilevanti.append(row['ETA'])
                
            if pd.notnull(row['ETD']) and start_filter <= row['ETD'] <= end_filter: 
                azioni.append("PARTENZA")
                orari_rilevanti.append(row['ETD'])
            
            tipo = " + ".join(azioni) if azioni else "-"
            sort_key = min(orari_rilevanti) if orari_rilevanti else pd.NaT
            
            return pd.Series([tipo, sort_key])

        df_filtrato[['Tipo', 'SortKey']] = df_filtrato.apply(processa_riga, axis=1)
        df_filtrato = df_filtrato.sort_values(by='SortKey')
        
        df_view = df_filtrato.rename(columns={'ETA': 'ARRIVI', 'ETD': 'PARTENZE'})
        
        cols_visible = ['Terminal', 'Vessel', 'ARRIVI', 'PARTENZE', 'Tipo', 'SortKey']
        for c in ['Terminal', 'Vessel', 'ARRIVI', 'PARTENZE']:
             if c not in df_view.columns: df_view[c] = ""
        
        st.success(f"Trovate {len(df_filtrato)} manovre totali!")
        
        st.dataframe(
            df_view[cols_visible].style.apply(style_manovre, axis=1).format({
                'ARRIVI': lambda t: t.strftime("%d/%m %H:%M") if pd.notnull(t) else "-",
                'PARTENZE': lambda t: t.strftime("%d/%m %H:%M") if pd.notnull(t) else "-"
            }),
            use_container_width=True,
            column_config={
                "Tipo": None,
                "SortKey": None
            },
            hide_index=True
        )
        
    else:
        st.info("Nessuna manovra prevista nel turno selezionato.")

    st.write("---")
    
    # --- MAPPA TRAFFICO IN TEMPO REALE (NUOVA SEZIONE) ---
    with st.expander("🗺️ Mappa Traffico Navale in Tempo Reale (Trieste)", expanded=False):
        # Embed di VesselFinder centrato su Trieste (Lat 45.65, Lon 13.77)
        components.iframe(
            "https://www.vesselfinder.com/aismap?zoom=13&lat=45.650&lon=13.770&width=100%&height=500&names=true&arrows=true",
            height=500,
            scrolling=False
        )
    
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
