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