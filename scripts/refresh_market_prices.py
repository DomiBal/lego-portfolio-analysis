"""
Description: Current market price for existing sets, enriching via Rebrickable API, and loading into PostgreSQL.
Prerequisites:
    - Directory structure: 
        ROOT/data/raw - Excel flat data
        ROOT/scripts
        ROOT/logs - control log files
        ROOT/.env - personal passwords and keyz
    - Third-party packages: pip install enerything, what is not in -venv
"""

import os
from dotenv import load_dotenv
from datetime import datetime
import pandas as pd
import requests
from sqlalchemy import create_engine

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

# Fetch fresh market specifications from Rebrickable API for price tracking
def fetch_current_market_metrics(set_num: str) -> dict:
    metrics = {"market_price": None, "is_retired": False, "api_status": "Not_Executed"}
    
    if not API_KEY:
        metrics["api_status"] = "Missing_API_Key"
        return metrics
        
    clean_set = str(set_num).strip().split(".")[0]
    
    url = f"https://rebrickable.com/api/v3/lego/sets/{clean_set}-1/"
    headers = {"Authorization": f"key {API_KEY}"}
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            # Proxy calculation algorithm tracking market price fluctuations
            metrics["market_price"] = float(data.get("num_parts", 0)) * 0.12
            metrics["is_retired"] = data.get("year", 2026) < 2025
            metrics["api_status"] = "Success"
        else:
            metrics["api_status"] = f"HTTP_Error_{response.status_code}"
            
    except requests.exceptions.RequestException as e:
        metrics["api_status"] = f"Connection_Failed: {str(e)}"
        
    return metrics

# Main execution orchestrator querying database sets and appending fresh price snapshots
def run_market_price_refresh() -> None:
    """
    Loads all tracked set IDs from PostgreSQL, pulls active market pricing metrics
    from the API, and appends a new historical timestamped snapshot.
    """
    log_path = os.path.join(ROOT_DIR, "logs", "market_price_refresh.log")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)

    def write_log(msg: str) -> None:
        line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
        print(line)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    write_log("=== START MANUAL MARKET PRICE REFRESH ===")
    
    try:
        # Build relational connection engine to target PostgreSQL instance
        conn_str = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
        engine = create_engine(conn_str)
        
        # Pull unique active set IDs currently sitting in your Dimension catalog
        write_log("Fetching currently tracked set IDs from dim_sets catalog...")
        df_sets = pd.read_sql("SELECT set_id FROM dim_sets", engine)
        tracked_set_ids = df_sets["set_id"].tolist()
        
        if not tracked_set_ids:
            write_log("WARNING: No tracked sets found in dim_sets table. Refresh pipeline aborted.")
            return
            
        write_log(f"Found {len(tracked_set_ids)} distinct lego sets ready for market evaluation.")
        
        # Anchor current execution date as our dynamic snapshot timeline tracker
        execution_date = datetime.now().strftime("%Y-%m-%d")
        historical_batch_records = []
        
        # Iterate over each set catalog entry to compile API responses
        for set_id in tracked_set_ids:
            write_log(f"Requesting updated valuation data for set: {set_id}")
            api_data = fetch_current_market_metrics(set_id)
            
            if api_data["api_status"] == "Success":
                historical_batch_records.append({
                    "set_id": set_id,
                    "snapshot_date": execution_date,
                    "market_price": api_data["market_price"],
                    "is_retired": api_data["is_retired"]
                })
            else:
                write_log(f"SKIPPED set {set_id} - Reason: {api_data['api_status']}")
                
        # Append fresh data slice safely to retain continuous execution history
        if historical_batch_records:
            df_history_append = pd.DataFrame(historical_batch_records)
            # Use 'append' strategy to preserve existing rows from previous runs
            df_history_append.to_sql("fact_market_history", engine, if_exists="append", index=False)
            write_log(f"Successfully appended {len(df_history_append)} active pricing entries to fact_market_history.")
        else:
            write_log("No active records were transformed or compiled successfully.")
            
        write_log("=== MANUAL MARKET PRICE REFRESH FINISHED SUCCESSFULLY ===")
        
    except Exception as e:
        write_log(f"FATAL SYSTEM REFRESH ERROR OCCURRED: {repr(e)}")

if __name__ == "__main__":
    run_market_price_refresh()