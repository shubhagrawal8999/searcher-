"""
researcher.py (updated)
reads unresearched rows from ALL sheet tabs:
Instagram, Facebook, Reddit, Sheet1 (Google Maps)
→ Jina reads website if available
→ GPT generates specific pain point + draft message
→ writes back to same row
"""

import os
import gspread
import requests
from openai import OpenAI
from google.oauth2.service_account import Credentials
import json
import time

# --- config ---
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
SHEET_ID = os.environ["SHEET_ID"]
GOOGLE_CREDS = json.loads(os.environ["GOOGLE_CREDS"])

openai_client = OpenAI(api_key=OPENAI_API_KEY)

GPT_SYSTEM_PROMPT = """
You are helping Shubh write outreach messages to real estate agents.

Shubh runs Zubhai (zubhai.com) — he builds AI automations for small businesses.
He is NOT selling anything. He genuinely wants to help.
He is funny, warm, direct. Like a helpful friend who knows tech.

NEVER say: "I hope this finds you well", "leverage", "synergy", "solutions", "touch base", "I came across your profile"

Return ONLY valid JSON. No markdown. No preamble.
"""

GPT_USER_PROMPT = """
Person: {name}
Platform they were found on: {platform}
Their bio/post: {context}
Their exact words about a struggle (if any): {pain_quote}
Website content: {website_text}

Based on what they ACTUALLY said or posted, identify:
1. their specific pain point (not generic — use their actual context)
2. write an outreach message

Return ONLY this JSON:
{{
  "pain_point": "one specific sentence using their actual context. reference real details. not generic.",
  "draft_message": "max 75 words. line 1: warm opener referencing something specific about them or what they posted. line 2: name their exact pain using their own words if possible. line 3: offer to show them one specific thing that helps — no price, no pitch. line 4: — Shubh, zubhai.com. casual tone. like texting a friend. zero corporate words."
}}
"""

TABS_TO_PROCESS = ["Sheet1", "Instagram", "Facebook", "Reddit"]

# column names per tab where pain point and draft live
TAB_COLUMNS = {
    "Sheet1":    {"pain": "Pain Point", "draft": "AI Draft",    "context_cols": ["Reviews Signal"], "website_col": "Website", "name_col": "Name"},
    "Instagram": {"pain": "Pain Point", "draft": "AI Draft",    "context_cols": ["Bio", "Latest Post"], "website_col": None, "name_col": "Name"},
    "Facebook":  {"pain": "Pain Point", "draft": "AI Draft",    "context_cols": ["Pain Quote"], "website_col": None, "name_col": "Name"},
    "Reddit":    {"pain": "Pain Point", "draft": "AI Draft",    "context_cols": ["Pain Quote", "Post Title"], "website_col": None, "name_col": "Username"},
}


def get_spreadsheet():
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(GOOGLE_CREDS, scopes=scopes)
    client = gspread.authorize(creds)
    return client.open_by_key(SHEET_ID)


def read_website(url):
    if not url or not str(url).startswith("http"):
        return ""
    try:
        resp = requests.get(f"https://r.jina.ai/{url}", timeout=12)
        return resp.text[:1500] if resp.status_code == 200 else ""
    except:
        return ""


def generate_research(name, platform, context, pain_quote, website_text):
    prompt = GPT_USER_PROMPT.format(
        name=name or "this person",
        platform=platform,
        context=context[:500] if context else "not available",
        pain_quote=pain_quote[:300] if pain_quote else "none",
        website_text=website_text[:800] if website_text else "not available",
    )
    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": GPT_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.85,
            max_tokens=400,
        )
        raw = response.choices[0].message.content.strip()
        # strip markdown if present
        raw = raw.replace("```json", "").replace("```", "").strip()
        return json.loads(raw)
    except Exception as e:
        print(f"    GPT error: {e}")
        return None


def process_tab(spreadsheet, tab_name):
    cfg = TAB_COLUMNS.get(tab_name)
    if not cfg:
        return 0

    try:
        sheet = spreadsheet.worksheet(tab_name)
    except:
        print(f"  tab '{tab_name}' not found — skipping")
        return 0

    records = sheet.get_all_records()
    headers = sheet.row_values(1)
    col = {h: i + 1 for i, h in enumerate(headers)}

    # check required columns exist
    pain_col = col.get(cfg["pain"])
    draft_col = col.get(cfg["draft"])
    if not pain_col or not draft_col:
        print(f"  missing columns in {tab_name} — check headers")
        return 0

    processed = 0

    for i, row in enumerate(records):
        row_num = i + 2

        # skip if already researched
        if row.get(cfg["pain"]) or row.get(cfg["draft"]):
            continue

        # build context from available columns
        context_parts = []
        for c in cfg["context_cols"]:
            val = row.get(c, "")
            if val:
                context_parts.append(str(val))
        context = " | ".join(context_parts)

        # skip if no context at all
        if not context.strip():
            continue

        name = row.get(cfg["name_col"], "")
        pain_quote = row.get("Pain Quote", "") if "Pain Quote" in row else ""
        website = row.get(cfg["website_col"], "") if cfg["website_col"] else ""
        website_text = read_website(website) if website else ""

        print(f"  [{tab_name}] researching: {name or 'unknown'}")

        result = generate_research(name, tab_name, context, pain_quote, website_text)
        if not result:
            continue

        sheet.update_cell(row_num, pain_col, result.get("pain_point", ""))
        sheet.update_cell(row_num, draft_col, result.get("draft_message", ""))

        processed += 1
        print(f"  ✓ done: {name or 'unknown'}")
        time.sleep(2)

        if processed >= 50:
            print(f"  50 limit reached for {tab_name}")
            break

    return processed


def main():
    print("🧠 starting researcher (all tabs)...")
    spreadsheet = get_spreadsheet()
    total = 0

    for tab in TABS_TO_PROCESS:
        print(f"\n--- processing tab: {tab} ---")
        count = process_tab(spreadsheet, tab)
        total += count
        print(f"  done: {count} rows researched")

    print(f"\n✅ total researched: {total}")


if __name__ == "__main__":
    main()
