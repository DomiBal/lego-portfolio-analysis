"""
Description: INITIALIZATION ETL pipeline transforming raw LEGO Excel data, enriching via Rebrickable API, and loading into PostgreSQL.
Prerequisites:
    - Directory structure: 
        ROOT/data/raw - Excel flat data
        ROOT/scripts
        ROOT/logs - control log files
        ROOT/.env - personal passwords and keyz, personal real data about my lego collection
    - Third-party packages: pip install enerything, what is not in -venv
"""

import os
from dotenv import load_dotenv
import pandas as pd
import unicodedata
import re
import requests
from datetime import datetime
from sqlalchemy import create_engine

# Setup paths based on your exact ROOT layout
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)  # Moves up from scripts to ROOT

# Load env variables from ROOT
load_dotenv(os.path.join(ROOT_DIR, ".env"))
API_KEY = os.getenv("REBRICKABLE_API_KEY")
DB_PASSWORD = os.getenv("DB_PASSWORD")

# Dynamic configuration for the source data asset with a safe sample fallback
SOURCE_EXCEL_NAME = os.getenv("SOURCE_EXCEL_NAME", "LEGO_sets_sample.xlsx")

# Database configurations
DB_USER = "postgres"
DB_HOST = "localhost"
DB_PORT = "5432"
DB_NAME = "lego_portfolio"

# Remove diacritics and convert string to lowercase for unified processing
def clean_string(text: str) -> str:
    if not isinstance(text, str):
        return str(text)
    return "".join(c for c in unicodedata.normalize('NFKD', text) if not unicodedata.combining(c)).lower().strip()

# Clean currency symbols, white spaces and convert raw value to float
def parse_currency(val) -> float:
    if pd.isna(val):
        return 0.0
    clean_val = str(val).strip().replace(" ", "").replace("€", "").replace(",", "")
    try:
        return float(clean_val)
    except ValueError:
        return 0.0

# Convert 'M/YYYY' string format into database-friendly 'YYYY-MM-01' format
def parse_date_slug(val) -> str:
    if pd.isna(val):
        return None
    # Scenario A: Pandas already parsed the input as a native timestamp datetime object
    if isinstance(val, (datetime, pd.Timestamp)):
        return f"{val.year}-{val.month:02d}-01"
    # Scenario B: Input is treated as a raw string text format
    slug = str(val).strip()
    if not re.match(r"^\d{1,2}/\d{4}$", slug):
        return None
    try:
        parts = slug.split("/")
        return f"{int(parts[1])}-{int(parts[0]):02d}-01"
    except (ValueError, IndexError):
        return None

# Fetch comprehensive specifications and current market value from Rebrickable API
def fetch_rebrickable_specs(set_num: str) -> dict:
    # Default data structure mapping all required variables
    specs = {
        "set_name": "Unknown",
        "theme": "Unknown",
        "release_year": None,
        "pieces": None,
        "minifigs_count": 0,
        "market_price": None,
        "is_retired": False,
        "api_status": "Not_Executed"
    }
    
    # Check if the API key exists in environment variables
    if not API_KEY:
        specs["api_status"] = "Missing_API_Key"
        return specs
        
    # Standardize set ID formatting by removing decimals and white spaces
    clean_set = str(set_num).strip().split(".")[0]
    if clean_set.lower() in ["nan", "n/a", ""]:
        specs["api_status"] = "Invalid_Set_ID"
        return specs

    # Core Rebrickable API endpoint for a specific LEGO set
    url = f"https://rebrickable.com/api/v3/lego/sets/{clean_set}-1/"
    headers = {"Authorization": f"key {API_KEY}"}
    
    try:
        # Execute HTTP GET request with a 10-second timeout policy
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            specs["set_name"] = data.get("name", "Unknown")
            specs["release_year"] = data.get("year")
            specs["pieces"] = data.get("num_parts")
            specs["api_status"] = "Success"
            
            # Map numerical theme_id returned from API into a standard string representation
            specs["theme"] = f"Theme_ID_{data.get('theme_id')}"
            
            # Sub-request to fetch exact minifigures count from the secondary API endpoint
            minifigs_url = f"{url}minifigs/"
            mini_res = requests.get(minifigs_url, headers=headers, timeout=5)
            if mini_res.status_code == 200:
                specs["minifigs_count"] = mini_res.json().get("count", 0)

            # Algorithmic fallback proxy for live market price calculation
            specs["market_price"] = float(data.get("num_parts", 0)) * 0.12
            
            # Dynamic logical evaluation to determine if the set has reached End of Life (EOL)
            specs["is_retired"] = data.get("year", 2026) < 2025

        else:
            specs["api_status"] = f"HTTP_Error_{response.status_code}"
            
    except requests.exceptions.RequestException as e:
        specs["api_status"] = f"Connection_Failed: {str(e)}"
        
    return specs

# Main execution orchestrator loading configured excel, enriching data via API and loading into PostgreSQL
def lego_initial_import() -> None:
    # Define production paths for logging purposes
    log_path = os.path.join(ROOT_DIR, "logs", "lego_initial_import.log")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)

    # Isolated inner helper function for standardized logging
    def write_log(msg: str) -> None:
        line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
        print(line)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    write_log("=== START LEGO INITIAL IMPORT PIPELINE ===")
    
    # Resolve source path dynamically using environment variable configuration
    source_file = os.path.join(ROOT_DIR, "data", "raw", SOURCE_EXCEL_NAME)
    write_log(f"Target runtime file resolved from configuration: {SOURCE_EXCEL_NAME}")
    
    # Fail-safe check to ensure input data asset is present
    if not os.path.exists(source_file):
        write_log(f"FATAL ERROR: Source data file is missing at: {source_file}")
        return
        
    try:
        write_log(f"Extracting source rows from file: {source_file}")
        # Read from sheet 'LEGO_sets', skipping first 20 structural formatting rows
        df_raw = pd.read_excel(source_file, sheet_name="LEGO_sets", skiprows=20)
        
        # Drop rows where critical primary locator 'Set' identifier is missing
        df_raw = df_raw.dropna(subset=["Set"])
        df_raw = df_raw[df_raw["Set"].astype(str).str.lower() != "n/a"]
        
        write_log(f"Staging area successfully initialized with {len(df_raw)} unique source rows.")
        
        # Staging lists to accumulate records for our 3NF target tables
        records_sets = []
        records_purchases = []
        records_market_history = []
        
        # Capture current snapshot date for the historical pricing trend baseline
        current_snapshot_date = datetime.now().strftime("%Y-%m-%d")
        
        # Loop through each row in the spreadsheet to transform and enrich
        for _, row in df_raw.iterrows():
            set_id = str(row["Set"]).strip().split(".")[0]
            write_log(f"Transforming and enriching data for set ID: {set_id} | {row['Názov setu']}")
            
            # Call the upgraded API client module from Phase 2
            api_data = fetch_rebrickable_specs(set_id)
            
            # 1. Populate Dimension structure (Dim_Sets)
            records_sets.append({
                "set_id": set_id,
                "set_name": api_data["set_name"] if api_data["set_name"] != "Unknown" else str(row["Názov setu"]).strip(),
                "theme": str(row["Séria"]).strip() if pd.notna(row["Séria"]) else api_data["theme"],
                "release_year": api_data["release_year"],
                "pieces": api_data["pieces"],
                "minifigs": int(row["Minifigs"]) if pd.notna(row["Minifigs"]) else api_data["minifigs_count"]
            })
            
            # 2. Populate Transactional Fact structure (Fact_Purchases)
            records_purchases.append({
                "set_id": set_id,
                "purchase_price": parse_currency(row["Cena"]),
                "purchase_date": parse_date_slug(row["Dátum"]),
                "owner": str(row["Majiteľ"]).strip(),
                "buyer": str(row["Platba"]).strip()
            })
            
            # 3. Populate Historical Pricing Fact structure (Fact_Market_History)
            if api_data["api_status"] == "Success":
                records_market_history.append({
                    "set_id": set_id,
                    "snapshot_date": current_snapshot_date,
                    "market_price": api_data["market_price"],
                    "is_retired": api_data["is_retired"]
                })

        # Convert structures to clean DataFrames and deduplicate dimension members
        df_dim_sets = pd.DataFrame(records_sets).drop_duplicates(subset=["set_id"])
        df_fact_purchases = pd.DataFrame(records_purchases)
        df_fact_market = pd.DataFrame(records_market_history)
        
        # Build relational connection engine to target PostgreSQL instance
        conn_str = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
        engine = create_engine(conn_str)
        
        write_log("Streaming structured staging tables into target PostgreSQL database instance...")
        
        # Write tables out (using replace for initial catalog setup generation)
        df_dim_sets.to_sql("dim_sets", engine, if_exists="replace", index=False)
        write_log(f"Database catalog sync complete: dim_sets loaded ({len(df_dim_sets)} rows)")
        
        df_fact_purchases.to_sql("fact_purchases", engine, if_exists="replace", index=False)
        write_log(f"Database catalog sync complete: fact_purchases loaded ({len(df_fact_purchases)} records)")
        
        df_fact_market.to_sql("fact_market_history", engine, if_exists="replace", index=False)
        write_log(f"Database catalog sync complete: fact_market_history initiated ({len(df_fact_market)} entries)")
        
        write_log("=== INITIAL IMPORT PIPELINE FINISHED SUCCESSFULLY ===")
        
    except Exception as e:
        write_log(f"FATAL SYSTEM ERROR OCCURRED: {repr(e)}")

# Script execution entry point
if __name__ == "__main__":
    lego_initial_import()