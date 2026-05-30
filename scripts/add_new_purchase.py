"""
Description: Adding a new purchased LEGO set, enriching via Rebrickable API, and loading into PostgreSQL existing dbs.
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
import re
import requests
from datetime import datetime
import pandas as pd
from sqlalchemy import create_engine, text

# Setup paths based on your exact ROOT layout
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)  # Moves up from scripts to ROOT

# Load env variables from ROOT
load_dotenv(os.path.join(ROOT_DIR, ".env"))
API_KEY = os.getenv("REBRICKABLE_API_KEY")
DB_PASSWORD = os.getenv("DB_PASSWORD")

# Database configurations
DB_USER = "postgres"
DB_HOST = "localhost"
DB_PORT = "5432"
DB_NAME = "lego_portfolio"

# Convert 'M/YYYY' string format into database-friendly 'YYYY-MM-01' format
def parse_date_slug(val: str) -> str:
    slug = str(val).strip()
    if not re.match(r"^\d{1,2}/\d{4}$", slug):
        return None
    try:
        parts = slug.split("/")
        return f"{int(parts[1])}-{int(parts[0]):02d}-01"
    except (ValueError, IndexError):
        return None
    
# Fetch comprehensive specifications and estimated market metrics from Rebrickable API
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
            
            # Map numerical theme_id returned from API into a standard string representation - real name
            theme_id = data.get("theme_id")
            if theme_id:
                theme_url = f"https://rebrickable.com/api/v3/lego/themes/{theme_id}/"
                theme_res = requests.get(theme_url, headers=headers, timeout=5)
                if theme_res.status_code == 200:
                    specs["theme"] = theme_res.json().get("name", "Unknown")
                else:
                    specs["theme"] = f"Theme_ID_{theme_id}"
            
            # Sub-request to fetch exact minifigures count from the secondary API endpoint
            minifigs_url = f"{url}minifigs/"
            mini_res = requests.get(minifigs_url, headers=headers, timeout=5)
            if mini_res.status_code == 200:
                specs["minifigs_count"] = mini_res.json().get("count", 0)

            # Algorithmic fallback proxy for live market price calculation
            specs["market_price"] = float(data.get("num_parts", 0)) * 0.12
           
            # Resolve current calendar year dynamically to prevent future hardcoding issues
            current_calendar_year = datetime.now().year
            set_release_year = data.get("year", current_calendar_year)
            
            # Dynamic EOL evaluation: if a set is older than 3 years from the current date, tag as retired
            specs["is_retired"] = set_release_year < (current_calendar_year - 3)
        
        else:
            specs["api_status"] = f"HTTP_Error_{response.status_code}"
            
    except requests.exceptions.RequestException as e:
        specs["api_status"] = f"Connection_Failed: {str(e)}"
        
    return specs

# Main interactive orchestration logic capturing user prompts and updating database
def execute_interactive_purchase_load() -> None:
    print("\n=============================================")
    print("   LEGO PORTFOLIO - ADD NEW PURCHASE TOOL    ")
    print("=============================================\n")
    
    # Step 1: Collect LEGO Set Number immediately
    set_id = input("Enter LEGO Set Number (e.g. 75355): ").strip()
    if not set_id:
        print("ERROR: Set Number cannot be empty. Process aborted.")
        return

    # Step 2: Validate set identity with Rebrickable API
    print(f"Validating set {set_id} with Rebrickable API...")
    api_data = fetch_rebrickable_specs(set_id)
    if api_data["api_status"] != "Success":
        print(f"FATAL ERROR: Set {set_id} not found in API. Reason: {api_data['api_status']}. Ingestion stopped.")
        return
        
    print(f"MATCH FOUND: {api_data['set_name']} ({api_data['theme']})")
    
    # Initialize database connection to check active catalog state
    conn_str = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    engine = create_engine(conn_str)
    
    # Step 3: Duplicate Verification Barrier
    try:
        with engine.connect() as conn:
            check_query = text("SELECT COUNT(1) FROM dim_sets WHERE set_id = :set_id")
            exists = conn.execute(check_query, {"set_id": set_id}).scalar()
            
            if exists:
                print(f"\n--> WARNING: Set {set_id} is already cataloged in your database.")
                confirm = input("Is this a legitimate second purchase of the same set? (y/n): ").strip().lower()
                
                if confirm != 'y':
                    print("\nProcess aborted by user. No data was requested or written.")
                    print("==============================================================\n")
                    return
                else:
                    print("Confirmation received. Proceeding to transactional details...")
                    
    except Exception as e:
        print(f"Database connection pre-check failed: {repr(e)}")
        return

    # Step 4: Collect financial and personal metrics
    print("\n--- Enter Purchase Details ---")
    try:
        purchase_price = float(input("Enter Purchase Price in EUR (e.g., 149.99): ").strip())
    except ValueError:
        print("ERROR: Invalid price format. Process aborted.")
        return
        
    raw_date = input("Enter Purchase Date in M/YYYY format (e.g., 5/2026): ").strip()
    db_date = parse_date_slug(raw_date)
    if not db_date:
        print("ERROR: Invalid date format. Must be M/YYYY. Process aborted.")
        return
        
    owner = input("Enter Owner Name (D or L): ").strip()
    buyer = input("Enter Buyer Name (D or L): ").strip()
    
    # Step 5: Execute safe incremental database streaming load
    try:
        with engine.connect() as conn:
            # Insert into dimension catalog if it's a completely new unique asset
            if not exists:
                print("New unique catalog entry detected. Inserting into dim_sets...")
                ins_dim = text("""
                    INSERT INTO dim_sets (set_id, set_name, theme, release_year, pieces, minifigs)
                    VALUES (:set_id, :set_name, :theme, :release_year, :pieces, :minifigs)
                """)
                conn.execute(ins_dim, {
                    "set_id": set_id,
                    "set_name": api_data["set_name"],
                    "theme": api_data["theme"],
                    "release_year": api_data["release_year"],
                    "pieces": api_data["pieces"],
                    "minifigs": api_data["minifigs_count"]
                })
                
            # Always stream the purchase metrics fact record
            print("Recording transactional metrics into fact_purchases...")
            ins_fact = text("""
                INSERT INTO fact_purchases (set_id, purchase_price, purchase_date, owner, buyer)
                VALUES (:set_id, :purchase_price, :purchase_date, :owner, :buyer)
            """)
            conn.execute(ins_fact, {
                "set_id": set_id,
                "purchase_price": purchase_price,
                "purchase_date": db_date,
                "owner": owner,
                "buyer": buyer
            })
            
            # Initialize pricing timeline historical checkpoint if missing for today
            current_snapshot_date = datetime.now().strftime("%Y-%m-%d")
            check_snap = text("""
                SELECT COUNT(1) FROM fact_market_history 
                WHERE set_id = :set_id AND snapshot_date = :snap_date
            """)
            snap_exists = conn.execute(check_snap, {"set_id": set_id, "snap_date": current_snapshot_date}).scalar()
            
            if not snap_exists:
                print("Initializing historical price trend log entry in fact_market_history...")
                ins_market = text("""
                    INSERT INTO fact_market_history (set_id, snapshot_date, market_price, is_retired)
                    VALUES (:set_id, :snapshot_date, :market_price, :is_retired)
                """)
                conn.execute(ins_market, {
                    "set_id": set_id,
                    "snapshot_date": current_snapshot_date,
                    "market_price": api_data["market_price"],
                    "is_retired": api_data["is_retired"]
                })
            
            # Commit total transaction block smoothly
            conn.commit()
                
        print("\nSUCCESS: New purchase data asset successfully streamed to PostgreSQL datastore!")
        print("==============================================================================\n")
        
    except Exception as e:
        print(f"\nFATAL SYSTEM ERROR OCCURRED DURING INGESTION: {repr(e)}\n")

if __name__ == "__main__":
    execute_interactive_purchase_load()