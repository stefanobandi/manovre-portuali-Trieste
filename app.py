import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime, time, timedelta

# --- CONFIGURAZIONE ---
st.set_page_config(page_title="Monitor Manovre TMT", layout="wide")

# --- FUNZIONI DI SCRAPING ---
def fetch_tmt_home_data():
    """Scarica la tabella direttamente dalla Home Page di TMT"""
    url = "https://www.trieste-marine-terminal.com/it"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Cerca tutte le tabelle
        tables = soup.find_all('table')
        
        target_df = pd.DataFrame()
        
        # Cerca la tabella giusta controllando se ha le colonne "ETB" o "Vessel"
        for t in tables:
            df_temp = pd.read_html(str(t))[0]
            # Convertiamo i nomi colonne in stringa e rimuoviamo spazi
            cols = [str(c).strip() for c in df_temp.columns]
            df_temp.columns = cols
            
            if "ETB" in cols and "Vessel" in cols:
                target_df = df_temp
                break
        
        if not target_df.empty:
            # Pulizia date: TMT usa formato "dd-mm-yyyy HH:MM:SS"
            # Convertiamo le colonne ETB e ETD in oggetti datetime veri
            for col in ['ETB', 'ETD']:
                if col in target_df.columns:
                    target_df[col] = pd.to_datetime(target_df[col], dayfirst=True, errors='coerce')
            return target_df
        else:
            return pd.DataFrame()
            
    except Exception as e:
        st.error(f"Errore connessione: {e}")
        return pd.DataFrame()

# --- LOGICA TURNI ---
def get_orari_turno(ora_riferimento, tipo_visualizzazione):
    """
    Calcola inizio e fine del turno basandosi sull'ora di riferimento
    e sulla scelta dell'utente (Turno Attuale vs Prossimo).
    """
    # Definiamo i limiti fissi dei turni
    t_mattina_start = ora_riferimento.replace(hour=8, minute=0, second=0, microsecond=0)
    t_sera_start = ora_riferimento.replace(hour=20, minute=0, second=0, microsecond=0)
    
    # Capiamo in che turno siamo ORA
    if 8 <= ora_riferimento.hour < 20:
        # Siamo nel turno DIURNO (08-20)
        attuale_start = t_mattina_start
        attuale_end = t_sera_start
        
        prossimo_start = t_sera_start
        prossimo_end = t_sera_start + timedelta(hours=12) # 08:00 del giorno dopo
        nome_attuale = "Diurno (08:00 - 20:00)"
    else:
        # Siamo nel turno NOTTURNO (20-08)
        # Se sono le 22:00, il turno è iniziato oggi alle 20.
        # Se sono le 05:00, il turno è iniziato ieri alle 20.
        if ora_riferimento.hour >= 20:
            attuale_start = t_sera_start
            attuale_end = t_sera_start + timedelta(hours=12) # 08:00 domani
        else:
            attuale_start = t_sera_start - timedelta(days=1) # 20:00 ieri
            attuale_end = t_mattina_start # 08:00 oggi
            
        prossimo_start = attuale_end
        prossimo_end = prossimo_start + timedelta(hours=12) # 20:00 prossimo
        nome_attuale = "Notturno (20:00 - 08:00)"

    if tipo_visualizzazione == "Turno Attuale":
        return attuale_start, attuale_end, nome_attuale
    else:
        return prossimo_start, prossimo_end, "Prossimo Turno"

# --- INTERFACCIA ---
st.title("⚓ Monitor Manovre Rimorchiatori")

# Sidebar per DEBUG e Test
with st.sidebar:
    st.header("🔧 Debug / Simulazione")
    ora_simulata = st.time_input("Simula Ora", datetime.now().time())
    data_simulata = st.date_input("Simula Data", datetime.now().date())
    # Creiamo un datetime completo combinando data e ora scelte
    dt_riferimento = datetime.combine(data_simulata, ora_simulata)
    st.write(f"Orario sistema simulato: {dt_riferimento}")

# Layout principale
col_btn, col_info, col_sel = st.columns([1, 2, 2])

with col_btn:
    if st.button("🔄 AGGIORNA LISTA", type="primary"):
        st.rerun()

with col_sel:
    scelta_vista = st.radio("Visualizza manovre per:", ["Turno Attuale", "Prossimo Turno"], horizontal=True)

# Calcolo orari turno
inizio_t, fine_t, nome_turno = get_orari_turno(dt_riferimento, scelta_vista)

with col_info:
    st.info(f"Filtro Attivo: **{inizio_t.strftime('%H:%M')} ⮕ {fine_t.strftime('%H:%M')}** ({inizio_t.day}/{inizio_t.month})")

st.divider()

# Recupero Dati
with st.spinner("Lettura dati dalla Home Page TMT..."):
    df = fetch_tmt_home_data()

if not df.empty:
    # --- FILTRO LOGICO ---
    # Una nave è "di interesse" se:
    # 1. Il suo arrivo (ETB) è dentro il mio turno
    # 2. OPPURE la sua partenza (ETD) è dentro il mio turno
    
    mask_arrivo = (df['ETB'] >= inizio_t) & (df['ETB'] <= fine_t)
    mask_partenza = (df['ETD'] >= inizio_t) & (df['ETD'] <= fine_t)
    
    df_filtrato = df[mask_arrivo | mask_partenza].copy()
    
    # Creiamo una colonna "Tipo Manovra" per chiarezza
    def definisci_manovra(row):
        azioni = []
        if inizio_t <= row['ETB'] <= fine_t:
            azioni.append("ARRIVO")
        if inizio_t <= row['ETD'] <= fine_t:
            azioni.append("PARTENZA")
        return " & ".join(azioni) if azioni else "In Banchina"

    if not df_filtrato.empty:
        df_filtrato['Manovra'] = df_filtrato.apply(definisci_manovra, axis=1)
        
        # Mostriamo solo le colonne utili e riordiniamo
        cols_to_show = ['Manovra', 'Vessel', 'ETB', 'ETD', 'Agent']
        # Se qualcuna non esiste nel df originale, non spacchiamo tutto
        cols_final = [c for c in cols_to_show if c in df_filtrato.columns]
        
        st.success(f"Trovate {len(df_filtrato)} manovre nel turno selezionato!")
        st.dataframe(
            df_filtrato[cols_final].style.applymap(
                lambda x: 'background-color: #d4edda' if 'ARRIVO' in str(x) else ('background-color: #f8d7da' if 'PARTENZA' in str(x) else ''),
                subset=['Manovra']
            ), 
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("Nessuna manovra prevista (Arrivo o Partenza) in questo orario.")
        
    with st.expander("Visualizza tabella completa (Tutte le navi)"):
        st.dataframe(df, use_container_width=True)

else:
    st.error("Impossibile scaricare la tabella. Verifica la connessione o se il sito TMT è online.")
