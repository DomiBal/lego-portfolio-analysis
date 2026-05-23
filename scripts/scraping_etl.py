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