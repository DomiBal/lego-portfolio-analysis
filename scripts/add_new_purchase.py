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
    
