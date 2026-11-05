"""Write an APPROVED proposal to the CRM. Only ever called from the review app after a human click."""
import config as C
import crm_client


def apply_proposal(p: dict) -> dict:
    t = p["type"]
    if t == "CREATE":
        created = crm_client.create_account(p["create"])
        return {"created": created.get(C.F_ID, created)}

    if t == "CHOW":
        # 1) new account under correct parent; 2) old account: ONLY chow_current_account (+ note), nothing else
        created = crm_client.create_account(p["create"])
        new_id = created.get(C.F_ID) or created.get("account_id")
        patch = {C.F_CHOW: new_id}
        if C.F_NOTE in p["changes"]:
            patch[C.F_NOTE] = p["changes"][C.F_NOTE]
        updated = crm_client.update_account(p["account_id"], patch)
        return {"created": new_id, "updated_old": p["account_id"], "patch": patch}

    if t in ("UPDATE", "DUPLICATE", "CHOW_OUT", "NEEDS_REVIEW"):
        updated = crm_client.update_account(p["account_id"], p["changes"])
        return {"updated": p["account_id"], "patch": p["changes"]}

    raise ValueError(f"unknown proposal type {t}")
