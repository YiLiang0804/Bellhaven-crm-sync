"""Human review queue. Run:  streamlit run review_app.py
Nothing is written to the CRM unless a reviewer clicks Approve."""
import json
import streamlit as st
import config as C
import ledger
from apply import apply_proposal

st.set_page_config(page_title="Bellhaven CRM Sync - Review", layout="wide")
st.title("Bellhaven -> CRM sync: review queue")

try:
    proposals = json.load(open(C.PROPOSALS_JSON))
except FileNotFoundError:
    st.error("No proposals.json yet. Run `python run.py` first.")
    st.stop()

done = ledger.decided_keys()
pending = [p for p in proposals if p["key"] not in done]

types = sorted({p["type"] for p in pending})
with st.sidebar:
    st.metric("Pending", len(pending))
    st.metric("Decided", len(done))
    sel = st.multiselect("Filter by type", types, default=types)
    if st.checkbox("Show decision history"):
        for h in ledger.history():
            st.write(f"{h['decided_at'][:19]} **{h['decision']}** {h['proposal']['type']} - {h['proposal']['summary']}")

EXPLAIN = {
    "UPDATE": "Same address in CRM; fix fields to match website. Parent change here passed the CHOW check (not both revenue>0 and AR>0).",
    "CHOW": "Same address, wrong parent, but revenue>0 AND AR>0 -> old account must stay untouched. Creates a new account under Bellhaven and sets chow_current_account on the old one.",
    "DUPLICATE": "Several CRM accounts share one address. Loser gets duplicate_of_account -> survivor and status Inactive (no delete in this API).",
    "CREATE": "Website location with no CRM account at that address. Similar-name candidates (if any) have a different address and are left alone.",
    "CHOW_OUT": "Under Bellhaven in CRM but gone from website; another owner's account exists at the same address -> likely sold. Only chow_current_account + note are set.",
    "NEEDS_REVIEW": "Not enough evidence to act automatically. Sets status Needs Review + note so a human follows up.",
}

for p in [p for p in pending if p["type"] in sel]:
    with st.expander(f"[{p['type']}] {p['summary']}", expanded=False):
        st.caption(EXPLAIN.get(p["type"], ""))
        c1, c2 = st.columns(2)
        ev = p["evidence"]
        site_ev = {k: v for k, v in ev.items() if k.startswith("site_")}
        crm_ev = {k: v for k, v in ev.items() if not k.startswith("site_")}
        with c1:
            st.markdown("**Website says**")
            st.json(site_ev) if site_ev else st.write("(no website record - account is not on the site)")
        with c2:
            st.markdown("**CRM says / reasoning**")
            st.json(crm_ev)
        if p["changes"]:
            st.markdown(f"**PATCH /accounts/{p['account_id']}**")
            st.json(p["changes"])
        if p["create"]:
            st.markdown("**POST /accounts (new account)**")
            st.json(p["create"])
        if p.get("site_url"):
            st.markdown(f"[open website page]({p['site_url']})  ·  "
                        f"[open CRM record]({C.BASE_URL}/crm/{C.TOKEN}/accounts/{p['account_id']})" if p["account_id"] else f"[open website page]({p['site_url']})")

        b1, b2, _ = st.columns([1, 1, 6])
        if b1.button("Approve", key="a" + p["key"], type="primary"):
            try:
                res = apply_proposal(p)
                ledger.record(p["key"], "approved", p, res)
                st.success(f"Applied: {res}")
                st.rerun()
            except Exception as e:
                st.error(f"API error, nothing recorded: {e}")
        if b2.button("Reject", key="r" + p["key"]):
            ledger.record(p["key"], "rejected", p)
            st.info("Rejected - will not be proposed again.")
            st.rerun()

if not pending:
    st.success("Queue empty.")
