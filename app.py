import streamlit as st
import pandas as pd
from datetime import datetime, time, timedelta
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
import time as time_module

# --- CONFIGURAZIONE ---
st.set_page_config(page_title="Monitor Manovre Porto", layout="wide")

# --- FUNZIONE SETUP BROWSER ---
def get_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    # Imposta una dimensione finestra fissa per evitare layout mobili
    chrome_options.add_argument("--window-size=1920,1080")
    
    service = Service("/usr/bin/chromedriver")
    return webdriver.Chrome(service=service, options=chrome_options)

# --- 1. SCRAPING TMT (Container) ---
def fetch_tmt_data(driver):
    url = "https://www.trieste-marine-terminal.com/it"
    try:
        driver.get(url)
        time_module.sleep(5)
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
        # In produzione silenziamo l'errore per non spaventare, o usiamo st.error per debug
        print(f"Errore TMT: {e}")
    return pd.DataFrame()

# --- 2. SCRAPING TASCO (Petroliere - SIOT) ---
def fetch_tasco_data(driver):
    # Verifica presenza credenziali
    if "tasco" not in st.secrets:
        st.error("⚠️ Configura i Secrets di Streamlit con [tasco] username e password.")
        return pd.DataFrame()

    login_url = "https://tasco.tal-oil.com/ui/login"
    target_url = "https://tasco.tal-oil.com/ui/menuitem-2003"
    
    try:
        # FASE 1: LOGIN
        driver.get(login_url)
        time_module.sleep(5) # Aspettiamo bene che la pagina carichi
        
        # --- NUOVA STRATEGIA DI SELEZIONE ---
        # Invece di cercare per nome, cerchiamo per "TIPO" di campo.
        # Cerchiamo il campo password (che è unico)
        pass_input = driver.find_element(By.CSS_SELECTOR, "input[type='password']")
        
        # Cerchiamo il campo testo generico (che di solito è lo username/email)
        # Proviamo a cercare un input di tipo text o email
        try:
            user_input = driver.find_element(By.CSS_SELECTOR, "input[type='text']")
        except:
            # Se non trova text, prova email
            user_input = driver.find_element(By.CSS_SELECTOR, "input[type='email']")

        # Inserimento dati
        user_input.clear()
        user_input.send_keys(st.secrets["tasco"]["username"])
        
        pass_input.clear()
        pass_input.send_keys(st.secrets["tasco"]["password"])
        
        # Invio
        pass_input.send_keys(Keys.RETURN)
        
        # Attendiamo il login
        time_module.sleep(6) 
        
        # FASE 2: NAVIGAZIONE DIRETTA ALLA TABELLA
        # Andiamo dritti al link della tabella, saltando menu grafici
        driver.get(target_url)
        time_module.sleep(6) # Attesa caricamento dati tabella
        
        # FASE 3: LETTURA DATI
        # Cerchiamo tabella con colonna POB (Pilot On Board - Arrivo)
        dfs = pd.read_html(driver.page_source, match="POB", flavor='html5lib')
        
        if len(dfs) > 0:
            df = dfs[0]
            df.columns = [str(c).strip() for c in df.columns]
            
            # NORMALIZZAZIONE: Rinominiamo le colonne TASCO per farle uguali a TMT
            # POB = Arrivo (ETB), TLB = Partenza (ETD)
            rename_map = {'POB': 'ETB', 'TLB': 'ETD'}
            df = df.rename(columns=rename_map)
            
            # Conversione Date
            for col in ['ETB', 'ETD']:
                if col in df.columns:
                    df[col] = pd.to_datetime(df[col], dayfirst=True, errors='coerce')
            
            df['Terminal'] = 'SIOT (Petroli)'
            
            # Aggiungiamo colonne vuote se mancano per uniformità con TMT
            if 'Vessel' not in df.columns:
                # A volte si chiama "Vessel Name" o "Nave"
                for poss_name in ['Vessel Name', 'Ship', 'Nave']:
                    if poss_name in df.columns:
                        df = df.rename(columns={poss_name: 'Vessel'})
                        break
            
            return df
        else:
            return pd.DataFrame()
            
    except Exception as e:
        # Se fallisce, stampiamo l'errore per capire cosa non va
        st.warning(f"Errore tecnico TASCO: {str(e)}")
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

# --- INTERFACCIA PRINCIPALE ---
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
with st.spinner("Connessione ai terminal TMT e SIOT in corso..."):
    driver = get_driver()
    
    # Eseguiamo scraping parallelo (sequenziale nel codice)
    df_tmt = fetch_tmt_data(driver)
    df_tasco = fetch_tasco_data(driver)
    
    driver.quit()

    # Unione Dati
    frames = []
    if not df_tmt.empty: frames.append(df_tmt)
    if not df_tasco.empty: frames.append(df_tasco)
    
    if frames:
        df_total = pd.concat(frames, ignore_index=True)
    else:
        df_total = pd.DataFrame()

# --- VISUALIZZAZIONE ---
if not df_total.empty:
    # 1. Filtro Temporale Unificato
    # Controlliamo che le colonne esistano prima di filtrare
    if 'ETB' in df_total.columns and 'ETD' in df_total.columns:
        mask = ((df_total['ETB'] >= start) & (df_total['ETB'] <= end)) | ((df_total['ETD'] >= start) & (df_total['ETD'] <= end))
        df_filtrato = df_total[mask].copy()
    else:
        df_filtrato = pd.DataFrame() # Se mancano le colonne chiave, vuoto
    
    # 2. Logica Azione
    def get_azione(row):
        azioni = []
        # Usa pd.notnull per evitare errori su date vuote
        if 'ETB' in row and pd.notnull(row['ETB']) and start <= row['ETB'] <= end: azioni.append("ARRIVO")
        if 'ETD' in row and pd.notnull(row['ETD']) and start <= row['ETD'] <= end: azioni.append("PARTENZA")
        return " + ".join(azioni) if azioni else "-"
        
    if not df_filtrato.empty:
        df_filtrato['Tipo'] = df_filtrato.apply(get_azione, axis=1)
        
        # Preparazione colonne finali
        cols_desired = ['Terminal', 'Tipo', 'Vessel', 'ETB', 'ETD', 'Agent']
        # Assicuriamoci che esistano tutte nel dataframe finale
        for c in cols_desired:
            if c not in df_filtrato.columns:
                df_filtrato[c] = ""
                
        st.success(f"Trovate {len(df_filtrato)} manovre totali (Container + Petroli)!")
        
        st.dataframe(
            df_filtrato[cols_desired].style.apply(style_manovre, axis=1).format({
                'ETB': lambda t: t.strftime("%d/%m %H:%M") if pd.notnull(t) else "-",
                'ETD': lambda t: t.strftime("%d/%m %H:%M") if pd.notnull(t) else "-"
            }),
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("Nessuna manovra prevista nel turno per nessuno dei terminal.")

    # TABELLE COMPLETE IN BASSO
    st.write("---")
    c1, c2 = st.columns(2)
    with c1:
        with st.expander("Tabella Completa TMT"):
            st.dataframe(df_tmt)
    with c2:
        with st.expander("Tabella Completa SIOT (TASCO)"):
            if df_tasco.empty:
                st.warning("Nessun dato SIOT visualizzabile.")
            else:
                st.dataframe(df_tasco)
else:
    st.error("Non sono riuscito a scaricare nessun dato. Riprova.")
