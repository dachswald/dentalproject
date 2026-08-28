import streamlit as st
import pandas as pd
import sqlite3
import subprocess
import sys

# Dashboard Page Settings
st.set_page_config(page_title="US Dentist Crawler Dashboard", layout="wide")
st.title("🦷 US Independent Dentist Finder")

DB_FILE = "dentists.db"

def get_connection():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS dentists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            practice_name TEXT,
            owner_or_management TEXT,
            address TEXT,
            phone TEXT,
            website TEXT,
            owner_email TEXT,
            owner_linkedin_url TEXT,
            state TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    return conn

conn = get_connection()

# ----------------- SIDEBAR CONTROLS -----------------
st.sidebar.header("Crawler Settings")

state = st.sidebar.selectbox(
    "Target State",
    ["AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", 
     "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", 
     "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", 
     "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", 
     "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY"]
)

limit = st.sidebar.number_input("Maximum Practices to Crawl", min_value=10, max_value=5000, value=1000, step=100)

# --- Action 1: Run Web Crawler ---
if st.sidebar.button("🚀 Run Live Crawler"):
    with st.status(f"Crawling independent dentists in {state}...", expanded=True) as status:
        st.write("Initializing crawler process...")
        
        # Uses sys.executable to ensure it uses the exact same Python interpreter
        process = subprocess.Popen(
            [sys.executable, "main.py", "crawl", "--state", state, "--limit", str(limit)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )
        
        # Stream crawler output live into the dashboard
        output_container = st.empty()
        log_lines = []
        for line in process.stdout:
            log_lines.append(line)
            output_container.code("".join(log_lines[-10:])) # Show last 10 lines
        
        process.wait()
        
        if process.returncode == 0:
            status.update(label=f"Successfully crawled {state}!", state="complete", expanded=False)
            st.rerun() # Refresh table automatically
        else:
            status.update(label="Crawler encountered an error", state="error")

# --- Action 2: Run Contact Enrichment ---
if st.sidebar.button("🔍 Enrich Pending Leads (Emails & LinkedIn)"):
    with st.status("Enriching contacts with emails & LinkedIn...", expanded=True) as status:
        process = subprocess.Popen(
            [sys.executable, "main.py", "enrich", "--limit", "25"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )
        
        for line in process.stdout:
            st.text(line.strip())
            
        process.wait()
        status.update(label="Enrichment finished!", state="complete")
        st.rerun()

# ----------------- MAIN DASHBOARD -----------------
# Load current SQLite data
try:
    df = pd.read_sql_query("SELECT * FROM dentists ORDER BY id DESC", conn)
except Exception:
    df = pd.DataFrame()

# KPI Metrics
c1, c2, c3 = st.columns(3)
c1.metric("Total Records in DB", len(df))
c2.metric("Enriched Emails", int(df['owner_email'].notna().sum()) if not df.empty and 'owner_email' in df else 0)
c3.metric("LinkedIn Matches", int(df['owner_linkedin_url'].notna().sum()) if not df.empty and 'owner_linkedin_url' in df else 0)

st.divider()

# Filter & Display Table
if not df.empty:
    filter_state = st.selectbox("Filter table by State", ["ALL"] + sorted(list(df['state'].dropna().unique())))
    display_df = df if filter_state == "ALL" else df[df['state'] == filter_state]

    st.subheader(f"Captured Records ({len(display_df)})")
    st.dataframe(display_df, use_container_width=True)

    # CRM Export Button
    csv = display_df.to_csv(index=False).encode('utf-8')
    st.download_button(
        label=f"📥 Download {filter_state} Leads as CSV for CRM",
        data=csv,
        file_name=f"independent_dentists_{filter_state.lower()}.csv",
        mime="text/csv"
    )
else:
    st.info("Your database is currently empty. Select a state on the left and click **'Run Live Crawler'** to begin collecting leads.")