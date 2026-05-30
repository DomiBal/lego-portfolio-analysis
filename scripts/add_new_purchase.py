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