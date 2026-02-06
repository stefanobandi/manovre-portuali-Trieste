import streamlit as st
import pandas as pd
from datetime import datetime, time, timedelta
import os
import glob
import time as time_module
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# --- CONFIGURAZIONE ---
st.set_page_config(page_title="Monitor Manovre Porto", layout="wide")

# --- FUNZIONE SETUP BROWSER CON DOWNLOAD ---
def get_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    
    # CONFIGURAZIONE DOWNLOAD
    # Diciamo a Chrome di scaricare i file nella cartella corrente del server
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

# --- 1. SCRAPING TMT (Container) ---
def fetch_tmt_data(driver):
    url = "https://www.trieste-marine-terminal.com/it"
    try:
        driver.get(url)
        time_module.sleep(3)
        dfs = pd.read_html(driver.page_source, match="Vessel", flavor='html5lib')
        if len(dfs) > 0:
            df = dfs[0]
            df.columns = [str(c).strip() for c in df.columns]
            for col in ['ETB', 'ETD']:
                if col in df.columns:
                    df[col] = pd.to_datetime(df[col], dayfirst=True, errors='coerce')
            df['Terminal'] = 'TMT (Molo VII)' 
            return df
    except Exception as e:
        print(f"Errore TMT: {e}")
    return pd.DataFrame()

# --- 2. SCRAPING TASCO (Via Excel Export) ---
def fetch_tasco_data(driver):
    if "tasco" not in st.secrets:
        st.error("⚠️ Configura i Secrets [tasco]!")
        return pd.DataFrame()

    login_url = "https://tasco.tal-oil.com/ui/login"
    
    st.toast("Accesso SIOT... (1/4)", icon="⛽")
    
    try:
        wait = WebDriverWait(driver, 20)
        
        # --- FASE 1: LOGIN ---
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

        # --- FASE 2: TIMOS ---
        st.toast("Apro TIMOS... (2/4)", icon="🖱️")
        try:
            btn_timos = wait.until(EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), 'Access to TIMOS')]")))
            btn_timos.click()
        except:
            st.error("Pulsante TIMOS non trovato.")
            return pd.DataFrame()
        time_module.sleep(5)

        # --- FASE 3: BLACKBOARD ---
        st.toast("Apro Blackboard... (3/4)", icon="📊")
        try:
            btn_bb = wait.until(EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), 'Terminal Basic Blackboard')]")))
            btn_bb.click()
        except:
            st.error("Pulsante Blackboard non trovato.")
            return pd.DataFrame()
        time_module.sleep(8)

        # --- FASE 4: CLICK SU EXPORT ---
        st.toast("Scarico Excel... (4/4)", icon="📥")
        
        # Pulizia cartella: rimuoviamo vecchi file xls/xlsx prima di scaricare
        for f in glob.glob("*.xls*"):
            try: os.remove(f)
            except: pass

        # Cerchiamo il tasto Export
        try:
            # Cerca un elemento che contiene la parola "Export" (tasto o link)
            btn_export = wait.until(EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), 'Export')]")))
            btn_export.click()
        except:
            # Se fallisce, proviamo a cercare un'icona o un titolo specifico se me lo descrivi meglio
            # Per ora proviamo un selettore generico "Export"
            st.error("Non trovo il tasto 'Export'.")
            return pd.DataFrame()
            
        # --- FASE 5: ATTESA DOWNLOAD ---
        # Aspettiamo che compaia un file .xlsx o .xls
        file_scaricato = None
        for i in range(15): # Aspetta max 15 secondi
            files = glob.glob("*.xls*") # Cerca file Excel
            if files:
                file_scaricato = files[0] # Prendi il primo trovato
                break
            time_module.sleep(1)
            
        if not file_scaricato:
            st.error("Timeout: Il file Excel non è stato scaricato.")
            return pd.DataFrame()
            
        st.success(f"File scaricato: {file_scaricato}")
        
        # --- FASE 6: LETTURA EXCEL ---
        # Pandas legge direttamente l'Excel
        df = pd.read_excel(file_scaricato)
        
        # Pulizia File (opzionale, per non intasare il server)
        try: os.remove(file_scaricato)
        except: pass
        
        return process_tasco_df(df)
            
    except Exception as e:
        st.error(f"Errore Tecnico TASCO: {str(e)}")
        return pd.DataFrame()

def process_tasco_df(df):
    """Funzione di pulizia specifica per la tabella TASCO"""
    # Rimuove righe vuote o intestazioni ripetute
    df = df.dropna(how='all')
    
    # Pulisce nomi colonne
    df.columns = [str(c).replace("?","").replace(".","").strip() for c in df.columns]
    
    # Rinomina colonne
    rename_map = {'POB': 'ETB', 'TLB': 'ETD', 'Tanker Name': 'Vessel', 'Tanker': 'Vessel'}
    df = df.rename(columns=rename_map)
    
    # Gestione anno corrente
    current_year = datetime.now().year
    
    def parse_tasco_date(val):
        val = str(val).strip()
        if not val or val.lower() == 'nan': return pd.NaT
        # Formato Excel spesso è già datetime, ma se è stringa "05.02."
        try:
            if isinstance(val, str) and val.count('.') >= 2: # es 05.02.
                return pd.to_datetime(f"{val}{current_year}", format="%d.%m.%Y", dayfirst=True)
        except: pass
        
        # Se arriva come datetime da Excel, perfetto
        return pd.to_datetime(val, errors='coerce')

    for col in ['ETB', 'ETD']:
        if col in df.columns:
            df[col] = df[col].apply(parse_tasco_date)

    df['Terminal'] = 'SIOT (Petroli)'
    return df

# --- LOGICA TURNI (INVARIATA) ---
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

# --- STILE E COLORI ---
def style_manovre(row):
    styles = [''] * len(row.index)
    def set_style(col_name, css):
        try:
            idx = row.index.get_loc(col_name)
            styles[idx] = css
        except KeyError: pass

    if 'ARRIVO' in str(row['Tipo']):
        set_style('Tipo', 'background-color: #d4edda; color: black; font-weight: bold')
        set_style('ETB', 'background-color: #d4edda; color: #155724; font-weight: bold; border: 2px solid #155724')
        
    if 'PARTENZA' in str(row['Tipo']):
        set_style('Tipo', 'background-color: #f8d7da; color: black; font-weight: bold')
        set_style('ETD', 'background-color: #f8d7da; color: #721c24; font-weight: bold; border: 2px solid #721c24')
        
    return styles

# --- INTERFACCIA ---
st.title("⚓ Monitor Manovre Porto di Trieste")

# Sidebar
st.sidebar.header("🔧 Simulazione")
ora_simulata = st.sidebar.time_input("Ora", datetime.now().time())
data_simulata = st.sidebar.date_input("Data", datetime.now().date())
dt_rif = datetime.combine(data_simulata, ora_simulata)

col_btn, col_info, col_sel = st.columns([1, 2, 2])

with col_btn:
    if st.button("🔄 AGGIORNA TUTTO", type="primary"):
        st.rerun()

with col_sel:
    scelta_vista = st.radio("Filtra per:", ["Turno Attuale", "Prossimo Turno"], horizontal=True)

start, end, nome_turno = get_orari_turno(dt_rif, scelta_vista)

with col_info:
    st.info(f"Turno: **{nome_turno}**\nFiltro: {start.strftime('%H:%M')} - {end.strftime('%H:%M')}")

st.divider()

# --- ESECUZIONE ---
with st.spinner("Scaricamento dati in corso..."):
    driver = get_driver()
    df_tmt = fetch_tmt_data(driver)
    df_tasco = fetch_tasco_data(driver)
    driver.quit()

    frames = []
    if not df_tmt.empty: frames.append(df_tmt)
    if not df_tasco.empty: frames.append(df_tasco)
    
    if frames:
        df_total = pd.concat(frames, ignore_index=True)
    else:
        df_total = pd.DataFrame()

# --- VISUALIZZAZIONE ---
if not df_total.empty:
    if 'ETB' in df_total.columns and 'ETD' in df_total.columns:
        mask = ((df_total['ETB'] >= start) & (df_total['ETB'] <= end)) | ((df_total['ETD'] >= start) & (df_total['ETD'] <= end))
        df_filtrato = df_total[mask].copy()
    else:
        df_filtrato = pd.DataFrame()
    
    def get_azione(row):
        azioni = []
        if 'ETB' in row and pd.notnull(row['ETB']) and start <= row['ETB'] <= end: azioni.append("ARRIVO")
        if 'ETD' in row and pd.notnull(row['ETD']) and start <= row['ETD'] <= end: azioni.append("PARTENZA")
        return " + ".join(azioni) if azioni else "-"
        
    if not df_filtrato.empty:
        df_filtrato['Tipo'] = df_filtrato.apply(get_azione, axis=1)
        
        cols_desired = ['Terminal', 'Tipo', 'Vessel', 'ETB', 'ETD', 'Agent']
        for c in cols_desired:
            if c not in df_filtrato.columns:
                df_filtrato[c] = ""
                
        st.success(f"Trovate {len(df_filtrato)} manovre totali!")
        
        st.dataframe(
            df_filtrato[cols_desired].style.apply(style_manovre, axis=1).format({
                'ETB': lambda t: t.strftime("%d/%m %H:%M") if pd.notnull(t) else "-",
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
        with st.expander("Tabella TMT"):
            st.dataframe(df_tmt)
    with c2:
        with st.expander("Tabella SIOT"):
            if df_tasco.empty:
                st.warning("Dati SIOT non disponibili.")
            else:
                st.dataframe(df_tasco)
else:
    st.error("Nessun dato scaricato.")
