"""Daily pipeline: scrape -> pull CRM -> match -> drop already-decided -> write proposals.json

  python run.py              full run
  python run.py --dry-run    same, but also prints the proposal table
  python run.py --inspect    print one raw CRM account + one contact so field names can be verified
  python run.py --offline    skip scraping/CRM pull, re-match from cached data/*.json
"""
import argparse
import json
import os
import sys
import config as C
import crm_client
import ledger
import scraper
from matcher import build_proposals


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--inspect", action="store_true")
    ap.add_argument("--offline", action="store_true")
    args = ap.parse_args()
    os.makedirs(C.DATA_DIR, exist_ok=True)

    if args.inspect:
        print("me:", json.dumps(crm_client.me(), indent=2))
        accs = crm_client.get_all_accounts()
        print(f"{len(accs)} accounts. first raw record:\n", json.dumps(accs[0], indent=2))
        cons = crm_client.get_all_contacts()
        print(f"{len(cons)} contacts. first raw record:\n", json.dumps(cons[0] if cons else {}, indent=2))
        return

    if args.offline:
        site = json.load(open(C.WEBSITE_JSON))
        accounts = json.load(open(C.CRM_JSON))
        contacts = json.load(open(C.CONTACTS_JSON))
    else:
        site = scraper.scrape()
        json.dump(site, open(C.WEBSITE_JSON, "w"), indent=2)
        accounts = crm_client.get_all_accounts()
        json.dump(accounts, open(C.CRM_JSON, "w"), indent=2)
        contacts = crm_client.get_all_contacts()
        json.dump(contacts, open(C.CONTACTS_JSON, "w"), indent=2)
    print(f"website: {len(site)} locations | crm: {len(accounts)} accounts, {len(contacts)} contacts")

    proposals = build_proposals(site, accounts, contacts)
    done = ledger.decided_keys()
    fresh = [p for p in proposals if p["key"] not in done]
    skipped = len(proposals) - len(fresh)
    json.dump(fresh, open(C.PROPOSALS_JSON, "w"), indent=2)
    print(f"{len(proposals)} proposals generated, {skipped} already decided (skipped), {len(fresh)} pending -> {C.PROPOSALS_JSON}")

    if args.dry_run or True:
        from collections import Counter
        print("by type:", dict(Counter(p["type"] for p in fresh)))
        for p in fresh:
            print(f"  [{p['type']:<12}] {p['summary']}")


if __name__ == "__main__":
    main()
