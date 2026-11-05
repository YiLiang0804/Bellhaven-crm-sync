"""Thin wrapper around the CRM sandbox API. All reads and writes go through here."""
import json
import requests
import config

HEADERS = {"Authorization": f"Bearer {config.TOKEN}", "Content-Type": "application/json"}


def _unwrap_list(payload):
    """API may return a bare list or {"items": [...]} / {"accounts": [...]} / {"data": [...]}."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("items", "accounts", "contacts", "data", "results"):
            if isinstance(payload.get(key), list):
                return payload[key]
        for v in payload.values():
            if isinstance(v, list):
                return v
    raise ValueError(f"Unexpected list payload shape: {str(payload)[:200]}")


def _get(path, **params):
    r = requests.get(f"{config.API_BASE}{path}", headers=HEADERS, params=params, timeout=30)
    if r.status_code >= 400:
        raise RuntimeError(f"GET {path} -> {r.status_code}: {r.text[:300]}")
    return r.json()


def _paginate(path, **params):
    out, page, size = [], 1, 50
    while True:
        batch = _unwrap_list(_get(path, page=page, page_size=size, **params))
        out.extend(batch)
        if len(batch) < size:
            break
        page += 1
    return out


def get_all_accounts():
    """Pull EVERY account, no filter (we must see non-Bellhaven decoys too)."""
    return _paginate("/accounts")


def get_all_contacts():
    return _paginate("/contacts")


def get_account(account_id):
    return _get(f"/accounts/{account_id}")


def create_account(fields: dict):
    r = requests.post(f"{config.API_BASE}/accounts", headers=HEADERS, data=json.dumps(fields), timeout=30)
    if r.status_code >= 400:
        raise RuntimeError(f"POST /accounts -> {r.status_code}: {r.text[:300]}")
    return r.json()


def update_account(account_id, fields: dict):
    r = requests.patch(f"{config.API_BASE}/accounts/{account_id}", headers=HEADERS,
                       data=json.dumps(fields), timeout=30)
    if r.status_code >= 400:
        raise RuntimeError(f"PATCH /accounts/{account_id} -> {r.status_code}: {r.text[:300]}")
    return r.json()


def me():
    return _get("/me")
