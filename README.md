# Bellhaven → CRM sync

Keeps the CRM's picture of Bellhaven Senior Living's facilities in line with Bellhaven's website: scrapes every
community, matches each to CRM accounts, proposes fixes with evidence, and writes **only human-approved** changes
back through the API. Built to run daily; re-runs never re-propose something already decided.

## Run it

```bash
$env:CRM_TOKEN="bh_wFUWLfEtL5Sy7mrq1CT2QQ"   # PowerShell; export CRM_TOKEN=... on Mac/Linux
pip install -r requirements.txt
python run.py --inspect     # optional: prints one raw account/contact so field names in config.py can be verified
python run.py               # scrape + pull CRM + match -> data/proposals.json (prints the queue)
streamlit run review_app.py # review queue: approve / reject; approved items hit the API immediately
python run.py               # run again: already-decided items are skipped (ledger in data/decisions.sqlite)
```

Files: `scraper.py` (website) · `crm_client.py` (API) · `normalize.py` (address/name normalisation) ·
`matcher.py` (all decision rules) · `apply.py` (write-back) · `ledger.py` (idempotency) · `review_app.py` (UI) ·
`run.py` (pipeline entry) · `config.py` (thresholds, field names, parent id) ·
schedule: `crontab.txt` or `.github/workflows/daily.yml`.

## How matching works

**The building is the identity, the name is just the sign on the door.** Facilities get bought, sold and rebranded;
the street address does not move. So:

1. Normalise `street + zip` on both sides (`Street→St`, `Northwest→NW`, `Pk→Pike`, drop punctuation/suite).
   Accounts sharing a key are the same facility.
2. Name similarity (`rapidfuzz token_set_ratio` after normalising `&/and`, `Centre/Center`, `Rehab/Rehabilitation`,
   dropping `the/of/at`) is **evidence only**. A similar name at a different address is a *different* facility and is
   never touched — it is listed in the proposal's evidence as a decoy so the reviewer sees we considered it.
3. Phone numbers are ignored for matching (they rot fastest). The website's administrator name is shown next to the
   CRM contacts as a third piece of evidence.
4. All 121 accounts are pulled with no filter, so non-Bellhaven look-alikes are visible to the matcher.

### Outcomes

| Situation | Proposal | Write-back |
|---|---|---|
| Same address, everything matches | *(nothing)* | – |
| Same address, outdated name / care type / parent | `UPDATE` | `PATCH` fields + note |
| Same name + same city/state but a different street (no address match) | `UPDATE` (street, zip) | `PATCH` address + note. Reviewer may reject if the CRM billing address legitimately differs from the physical one. |
| …parent change and `lifetime_revenue > 0 AND outstanding_ar > 0` | `CHOW` | `POST` new account under Bellhaven; `PATCH` old account **only** `chow_current_account` (+note). Old name/parent/status untouched. |
| Several accounts at one address | `DUPLICATE` for each loser | `duplicate_of_account = survivor`, `status = Inactive`, note |
| Several accounts at one address, no clear survivor | `NEEDS_REVIEW` on each | `status = Needs Review`, note |
| Website location, no account at that address | `CREATE` | `POST` under Bellhaven |
| Under Bellhaven in CRM, gone from website, another owner's account at same address | `CHOW_OUT` | `chow_current_account → that account`, note. Parent/status untouched (billing may still be open). |
| Under Bellhaven in CRM, gone from website, nothing else at that address | `NEEDS_REVIEW` | `status = Needs Review`, note |

**Survivor rule for duplicates** (in order): already under Bellhaven → has revenue → more contacts → a contact with an
email → name equals website name. A tie after all five means I do not have a defensible reason to pick, so the whole
group goes to Needs Review rather than guessing.

**CHOW rule** is applied literally: both `lifetime_revenue > 0` **and** `outstanding_ar > 0`. Revenue with zero AR
means the account is settled and is re-parented directly.

**No delete / merge exists**, and accounts are foreign keys for contacts, invoices and shift history, so losers are
soft-deleted (`Inactive` + pointer) instead of removed.

**Already-resolved accounts stay out of matching.** Anything Inactive, already flagged Needs Review, or carrying a
`chow_current_account` / `duplicate_of_account` pointer is treated as a historical record, so the old half of a CHOW
is never re-proposed as a duplicate of the new account and a Needs Review flag is not re-proposed every day.

## Cases found in this CRM copy

- Renames at a stable address: Chesterton Senior Commons → Bellhaven of Chesterton, Riverbend Manor → Bellhaven of
  Chagrin Falls, Sunny Acres → Bellhaven Willow Creek, Cedar Trail of Zanesville → Bellhaven of Zanesville, plus
  spelling drift (Centre/Center, Rehab/Rehabilitation, at/of).
- Wrong parent, settled billing → direct re-parent: Crossings of Lima (Harborview), Meadows of Findlay (no parent).
- Wrong parent, open AR → CHOW path: Bellhaven of Marietta, Bellhaven of Tiffin (both still under Cedar Trail).
- Duplicates from ownership history: Monroe (3 accounts), Erie (2), Port Clinton (2), Owosso (2 identical),
  Kettering (3, no clear survivor → Needs Review).
- Stale addresses: Ashtabula and Portsmouth exist under Bellhaven with the right name but a different street.
  The matcher proposes an address update (identical name + same city/state → same facility, not a new account),
  but because the CRM field is the *billing* street, which can legitimately differ from the physical address,
  I rejected these two and will confirm with billing before overwriting. The ledger keeps them from re-appearing.
- Genuinely new on the website, no CRM account at all: Batavia, Carlisle, Amberly Manor (Hudson), Bellhaven at
  Union Square → created under Bellhaven.
- Sold away: Bellhaven of Sandusky (revenue + AR) has a Millstone account at the same address → `CHOW_OUT`.
- Gone from website, nothing else at address: Coldwater, Alliance → Needs Review.
- Decoys with similar names but different buildings, left untouched: Amberly Manor (Colorado Springs, Juniper Point)
  vs Amberly Manor (Hudson OH, new); Union Square Senior Living (240 Market St, Juniper Point) vs Bellhaven at Union
  Square (118 Union Square Dr, new); Maplewood Senior Care Center (Stonebridge) vs Bellhaven of Maplewood.
- Website coverage traps: Bellhaven Meadows of Findlay is only linked from the homepage, not the directory (homepage
  says 35, directory says 34); Amberly Manor has no "Bellhaven" in its name, so a `q=bellhaven` search would miss it.

## Idempotency / daily run

Every proposal has a deterministic key (`sha1(type, account_id, changes, create)`). Decisions are stored in
`data/decisions.sqlite`; `run.py` drops any proposal whose key is already decided. Approved changes also alter the
CRM, so they stop being generated naturally; rejections are suppressed by the ledger. If the website changes
tomorrow a *new* key appears and is reviewed fresh. Schedule: `crontab.txt` (06:00 daily) or the GitHub Actions
workflow (caches the ledger between runs; token from a repo secret).

## What I would do with more time

- Fetch administrator names into the match score instead of showing them as evidence only.
- Diff the website against yesterday's snapshot and surface "new / removed on site" explicitly.
- Add a Slack digest of the pending queue.

## Time spent

2 to 3 Hours, including screen capture
