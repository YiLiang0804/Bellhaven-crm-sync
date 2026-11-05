"""Central configuration. Everything tunable lives here."""
import os

BASE_URL = "https://analyst-assessment-production.up.railway.app"
API_BASE = f"{BASE_URL}/api/v1"
TOKEN = os.environ.get("CRM_TOKEN", "")

# Parent account for Bellhaven in the CRM (auto-detected at runtime as fallback)
BELLHAVEN_PARENT_ID = "0015QAPLGS3FVYEEEM"
BELLHAVEN_PARENT_NAME_PREFIX = "bellhaven senior living"

# Local files
DATA_DIR = "data"
WEBSITE_JSON = f"{DATA_DIR}/website.json"
CRM_JSON = f"{DATA_DIR}/crm_accounts.json"
CONTACTS_JSON = f"{DATA_DIR}/crm_contacts.json"
PROPOSALS_JSON = f"{DATA_DIR}/proposals.json"
LEDGER_DB = f"{DATA_DIR}/decisions.sqlite"

# Matching thresholds
NAME_CANDIDATE_THRESHOLD = 80   # token_set_ratio >= this => "looks similar" (evidence only, never auto-change)
NAME_SAME_THRESHOLD = 97        # >= this after normalisation => treat names as the same (no rename proposed)

# Website care offering -> CRM care_type
CARE_MAP = {
    "short-term rehabilitation & nursing": "Skilled Nursing",
    "skilled nursing": "Skilled Nursing",
    "memory support": "Memory Care",
    "memory care": "Memory Care",
    "assisted living": "Assisted Living",
    "independent living": "Independent Living",
}

# CRM field names (verify once with `python run.py --inspect`)
F_NAME = "name"
F_STREET = "billing_street"
F_CITY = "billing_city"
F_STATE = "billing_state"
F_ZIP = "billing_zip"
F_PHONE = "phone"
F_PARENT = "parent_id"
F_STATUS = "status"
F_CARE = "care_type"
F_REVENUE = "lifetime_revenue"
F_AR = "outstanding_ar"
F_DUP = "duplicate_of_account"
F_CHOW = "chow_current_account"
F_NOTE = "note"
F_ID = "account_id"

