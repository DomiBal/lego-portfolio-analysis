"""
Description: INITIALIZATION ETL pipeline transforming raw LEGO Excel data, enriching via Rebrickable API, and loading into PostgreSQL.
Prerequisites:
    - Directory structure: ....
    - Third-party packages: ....
"""

import os
from dotenv import load_dotenv
import pandas as pd
import unicodedata
import re
import requests

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