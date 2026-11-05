"""Match website locations to CRM accounts and produce proposals.

Principle: the building (normalised street + zip) identifies a facility. The name is the sign on the door
and is only used as evidence / to find candidates. A name match with a different address is a DIFFERENT facility.

Proposal types
  UPDATE        same address, fix name / parent / care_type        (parent change only if NOT a CHOW case)
  CHOW          same address, needs new parent, but revenue>0 AND AR>0 -> create new acct, point old.chow_current_account
  DUPLICATE     several CRM accounts share one address -> losers get duplicate_of_account + Inactive
  CREATE        website location with no CRM account at that address
  CHOW_OUT      CRM acct under Bellhaven, gone from website, another owner's acct at same address -> point chow_current_account
  NEEDS_REVIEW  can't decide safely -> status Needs Review + note
"""
import hashlib
import json
from collections import defaultdict
from datetime import date
import config as C
from normalize import addr_key, name_similarity, names_same, norm_name

TODAY = date.today().isoformat()


def _f(acc, field, default=None):
    return acc.get(field, default)


def _money(v):
    try:
        return float(str(v).replace("$", "").replace(",", "") or 0)
    except ValueError:
        return 0.0


def map_care(offerings):
    mapped = []
    for o in offerings or []:
        m = C.CARE_MAP.get(o.strip().lower())
        if m and m not in mapped:
            mapped.append(m)
    return mapped


def find_bellhaven_parent(accounts):
    for a in accounts:
        if _f(a, C.F_ID) == C.BELLHAVEN_PARENT_ID:
            return a[C.F_ID]
    for a in accounts:
        if norm_name(_f(a, C.F_NAME, "")).startswith(C.BELLHAVEN_PARENT_NAME_PREFIX) and not _f(a, C.F_PARENT):
            return a[C.F_ID]
    raise RuntimeError("Bellhaven parent account not found")


def is_parent_account(a):
    return not _f(a, C.F_CITY) and not _f(a, C.F_STREET)


def _key(ptype, account_id, payload):
    raw = json.dumps([ptype, account_id, payload], sort_keys=True, default=str)
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def _proposal(ptype, account, site, changes=None, create=None, evidence=None, summary=""):
    aid = _f(account, C.F_ID) if account else None
    p = {
        "type": ptype,
        "account_id": aid,
        "account_name": _f(account, C.F_NAME) if account else None,
        "site_name": site["name"] if site else None,
        "site_url": site["url"] if site else None,
        "summary": summary,
        "changes": changes or {},
        "create": create or {},
        "evidence": evidence or {},
    }
    stable_changes = {k: v for k, v in p["changes"].items() if k != C.F_NOTE}
    p["key"] = _key(ptype, aid, {"changes": stable_changes, "create": p["create"]})
    return p


def _note(existing, text):
    text = f"[{TODAY} crm-sync] {text}"
    return f"{existing} | {text}" if existing else text


def _site_fields(site, bh_parent):
    care = map_care(site["care_offerings"])
    return {
        C.F_NAME: site["name"], C.F_STREET: site["street"], C.F_CITY: site["city"],
        C.F_STATE: site["state"], C.F_ZIP: site["zip"], C.F_PHONE: site["phone"],
        C.F_PARENT: bh_parent, C.F_STATUS: "Active",
        C.F_CARE: care[0] if care else None,
    }


def _rank(acc, site, bh_parent, contacts_by_acc):
    """Survivor priority: under Bellhaven > has revenue > more contacts > contact w/ email > name equals site name."""
    cs = contacts_by_acc.get(_f(acc, C.F_ID), [])
    return (
        1 if _f(acc, C.F_PARENT) == bh_parent else 0,
        1 if _money(_f(acc, C.F_REVENUE)) > 0 else 0,
        len(cs),
        1 if any(c.get("email") for c in cs) else 0,
        1 if site and names_same(_f(acc, C.F_NAME, ""), site["name"], C.NAME_SAME_THRESHOLD) else 0,
    )


def _acc_evidence(acc, contacts_by_acc):
    return {
        "crm_name": _f(acc, C.F_NAME), "crm_street": _f(acc, C.F_STREET), "crm_city": _f(acc, C.F_CITY),
        "crm_state": _f(acc, C.F_STATE), "crm_zip": _f(acc, C.F_ZIP), "crm_parent_id": _f(acc, C.F_PARENT),
        "crm_status": _f(acc, C.F_STATUS), "crm_care_type": _f(acc, C.F_CARE),
        "lifetime_revenue": _f(acc, C.F_REVENUE), "outstanding_ar": _f(acc, C.F_AR),
        "crm_contacts": [f"{c.get('name')} ({c.get('title')})" for c in contacts_by_acc.get(_f(acc, C.F_ID), [])],
    }


def _site_evidence(site):
    return {"site_name": site["name"], "site_street": site["street"], "site_city": site["city"],
            "site_state": site["state"], "site_zip": site["zip"], "site_care": site["care_offerings"],
            "site_administrator": site["administrator"], "site_url": site["url"]}


def build_proposals(site_records, accounts, contacts, parent_names=None):
    bh_parent = find_bellhaven_parent(accounts)
    parent_names = parent_names or {a[C.F_ID]: _f(a, C.F_NAME) for a in accounts if is_parent_account(a)}
    contacts_by_acc = defaultdict(list)
    for c in contacts:
        contacts_by_acc[c.get("account_id")].append(c)

    facilities = [a for a in accounts if not is_parent_account(a)]
    # Accounts already resolved (CHOW'd, marked duplicate, or Inactive) are historical records: they stay out of matching
    # so that a re-run never proposes them again (e.g. the old half of a CHOW is not a 'duplicate' of the new account).
    resolved = {a[C.F_ID] for a in facilities
                if _f(a, C.F_CHOW) or _f(a, C.F_DUP) or _f(a, C.F_STATUS) == "Inactive"}
    facilities = [a for a in facilities if a[C.F_ID] not in resolved]
    by_addr = defaultdict(list)
    for a in facilities:
        by_addr[addr_key(_f(a, C.F_STREET), _f(a, C.F_ZIP))].append(a)

    proposals, touched = [], set()

    # ---------- pass 1: website -> CRM ----------
    for site in site_records:
        k = addr_key(site["street"], site["zip"])
        group = by_addr.get(k, [])
        sev = _site_evidence(site)
        address_stale = False

        if not group:
            # Fallback: SAME name AND same city/state but a different street -> the CRM address is stale, not a new facility.
            same = [a for a in facilities
                    if names_same(_f(a, C.F_NAME, ""), site["name"], C.NAME_SAME_THRESHOLD)
                    and (_f(a, C.F_CITY, "") or "").lower() == site["city"].lower()
                    and _f(a, C.F_STATE) == site["state"]]
            if len(same) == 1:
                group, address_stale = same, True
                sev["address_match"] = "none; matched on identical name + city/state -> CRM street looks stale"

        if not group:
            # look for similarly-named accounts anywhere: evidence only, never a reason to re-parent
            cands = []
            for a in facilities:
                s = name_similarity(_f(a, C.F_NAME, ""), site["name"])
                same_city = (_f(a, C.F_CITY, "") or "").lower() == site["city"].lower() and _f(a, C.F_STATE) == site["state"]
                if s >= C.NAME_CANDIDATE_THRESHOLD or (same_city and s >= C.NAME_CANDIDATE_THRESHOLD // 2):
                    cands.append({"account_id": a[C.F_ID], "name": _f(a, C.F_NAME), "similarity": s,
                                  "street": _f(a, C.F_STREET), "city": _f(a, C.F_CITY), "state": _f(a, C.F_STATE),
                                  "parent": parent_names.get(_f(a, C.F_PARENT), _f(a, C.F_PARENT)),
                                  "verdict": "different address -> different facility, left untouched"})
            ev = {**sev, "address_match": "none in CRM", "similar_name_candidates": cands}
            proposals.append(_proposal("CREATE", None, site, create=_site_fields(site, bh_parent), evidence=ev,
                                       summary=f"Create '{site['name']}' under Bellhaven (no CRM account at {site['street']}, {site['zip']})"))
            continue

        ranked = sorted(group, key=lambda a: _rank(a, site, bh_parent, contacts_by_acc), reverse=True)
        survivor = ranked[0]
        tie = len(ranked) > 1 and _rank(ranked[0], site, bh_parent, contacts_by_acc) == _rank(ranked[1], site, bh_parent, contacts_by_acc)

        if tie:
            for a in group:
                touched.add(a[C.F_ID])
                if _f(a, C.F_STATUS) == "Needs Review":
                    continue  # already flagged on a previous run
                others = [b[C.F_ID] for b in group if b is not a]
                ev = {**sev, **_acc_evidence(a, contacts_by_acc), "same_address_accounts": others,
                      "reason": "multiple CRM accounts at this address with equal survivor priority; human must pick"}
                proposals.append(_proposal("NEEDS_REVIEW", a, site,
                                           changes={C.F_STATUS: "Needs Review",
                                                    C.F_NOTE: _note(_f(a, C.F_NOTE), f"Same address as {others}; website lists '{site['name']}'. Pick survivor manually.")},
                                           evidence=ev, summary=f"Needs Review: {len(group)} accounts share {site['street']} ({site['name']})"))
            continue

        # losers -> duplicates of survivor
        for a in ranked[1:]:
            touched.add(a[C.F_ID])
            ev = {**sev, **_acc_evidence(a, contacts_by_acc), "survivor_id": survivor[C.F_ID], "survivor_name": _f(survivor, C.F_NAME),
                  "survivor_rank": _rank(survivor, site, bh_parent, contacts_by_acc), "loser_rank": _rank(a, site, bh_parent, contacts_by_acc)}
            proposals.append(_proposal("DUPLICATE", a, site,
                                       changes={C.F_DUP: survivor[C.F_ID], C.F_STATUS: "Inactive",
                                                C.F_NOTE: _note(_f(a, C.F_NOTE), f"Duplicate of {survivor[C.F_ID]} ({_f(survivor, C.F_NAME)}) - same address {site['street']}")},
                                       evidence=ev, summary=f"Mark '{_f(a, C.F_NAME)}' duplicate of '{_f(survivor, C.F_NAME)}' (same address)"))

        # survivor -> field fixes
        touched.add(survivor[C.F_ID])
        aev = _acc_evidence(survivor, contacts_by_acc)
        aev["name_similarity"] = name_similarity(_f(survivor, C.F_NAME, ""), site["name"])
        aev["administrator_in_crm_contacts"] = any(
            site["administrator"] and site["administrator"].lower() in (c.get("name") or "").lower()
            for c in contacts_by_acc.get(survivor[C.F_ID], []))
        changes = {}
        if address_stale:
            changes[C.F_STREET] = site["street"]
            changes[C.F_ZIP] = site["zip"]
            aev["address_rule"] = f"CRM street '{_f(survivor, C.F_STREET)}' != website '{site['street']}'; same name + city -> update address"
        if not names_same(_f(survivor, C.F_NAME, ""), site["name"], C.NAME_SAME_THRESHOLD):
            changes[C.F_NAME] = site["name"]
        care = map_care(site["care_offerings"])
        if care and _f(survivor, C.F_CARE) not in care:
            changes[C.F_CARE] = care[0]
        if _f(survivor, C.F_STATUS) != "Active":
            changes[C.F_STATUS] = "Active"
        needs_parent = _f(survivor, C.F_PARENT) != bh_parent

        if needs_parent:
            rev, ar = _money(_f(survivor, C.F_REVENUE)), _money(_f(survivor, C.F_AR))
            aev["old_parent"] = parent_names.get(_f(survivor, C.F_PARENT), _f(survivor, C.F_PARENT)) or "(none)"
            if rev > 0 and ar > 0:
                # SOP: preserve old account untouched, create new under Bellhaven, link via chow_current_account
                aev["chow_rule"] = f"lifetime_revenue={rev:.0f} > 0 AND outstanding_ar={ar:.0f} > 0 -> CHOW path"
                proposals.append(_proposal("CHOW", survivor, site, create=_site_fields(site, bh_parent),
                                           changes={C.F_CHOW: "<new_account_id>",
                                                    C.F_NOTE: _note(_f(survivor, C.F_NOTE), f"CHOW: facility now operated by Bellhaven; new account created, see chow_current_account")},
                                           evidence={**sev, **aev},
                                           summary=f"CHOW: keep '{_f(survivor, C.F_NAME)}' (AR ${ar:,.0f}) untouched, create new '{site['name']}' under Bellhaven, link old->new"))
                continue
            aev["chow_rule"] = f"lifetime_revenue={rev:.0f}, outstanding_ar={ar:.0f} -> not both > 0 -> direct re-parent allowed"
            changes[C.F_PARENT] = bh_parent

        if changes:
            changes[C.F_NOTE] = _note(_f(survivor, C.F_NOTE), "Synced to bellhaven website: " + ", ".join(k for k in changes if k != C.F_NOTE))
            proposals.append(_proposal("UPDATE", survivor, site, changes=changes, evidence={**sev, **aev},
                                       summary=f"Update '{_f(survivor, C.F_NAME)}': " + ", ".join(f"{k}->{v}" for k, v in changes.items() if k != C.F_NOTE)))
        # else: confident match, nothing to do

    # ---------- pass 2: CRM accounts under Bellhaven that are not on the website ----------
    for a in facilities:
        if _f(a, C.F_PARENT) != bh_parent or a[C.F_ID] in touched:
            continue
        if _f(a, C.F_STATUS) in ("Inactive", "Needs Review") or _f(a, C.F_CHOW) or _f(a, C.F_DUP):
            continue  # already resolved or already flagged on a previous run
        k = addr_key(_f(a, C.F_STREET), _f(a, C.F_ZIP))
        others = [b for b in by_addr.get(k, []) if b is not a and _f(b, C.F_PARENT) != bh_parent]
        aev = _acc_evidence(a, contacts_by_acc)
        if others:
            o = others[0]
            new_owner = parent_names.get(_f(o, C.F_PARENT), _f(o, C.F_PARENT)) or "(independent)"
            ev = {**aev, "other_account_id": o[C.F_ID], "other_account_name": _f(o, C.F_NAME), "other_owner": new_owner,
                  "reason": "not on Bellhaven website; another owner's account exists at same address -> facility likely sold"}
            proposals.append(_proposal("CHOW_OUT", a, None,
                                       changes={C.F_CHOW: o[C.F_ID],
                                                C.F_NOTE: _note(_f(a, C.F_NOTE), f"Not on Bellhaven website as of {TODAY}; same address now under {new_owner} ({o[C.F_ID]}). Old account preserved for billing.")},
                                       evidence=ev, summary=f"CHOW out: '{_f(a, C.F_NAME)}' appears sold to {new_owner}; point chow_current_account -> {o[C.F_ID]}"))
        else:
            ev = {**aev, "reason": "not on Bellhaven website; no other CRM account at this address -> closed, sold to unknown owner, or website omission"}
            proposals.append(_proposal("NEEDS_REVIEW", a, None,
                                       changes={C.F_STATUS: "Needs Review",
                                                C.F_NOTE: _note(_f(a, C.F_NOTE), f"Not listed on Bellhaven website as of {TODAY}; no same-address account in CRM. Confirm closed/sold.")},
                                       evidence=ev, summary=f"Needs Review: '{_f(a, C.F_NAME)}' under Bellhaven but not on website"))

    return proposals
