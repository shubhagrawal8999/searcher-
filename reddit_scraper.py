"""
reddit_scraper.py
searches real estate subreddits for agents posting pain points
extracts: username, post content, pain signal
cross-references with any contact info they shared
writes to Google Sheet "Reddit" tab
runs daily via GitHub Actions
"""

import os
import re
import gspread
import json
import requests
import time
from google.oauth2.service_account import Credentials
from datetime import datetime

# --- config ---
SHEET_ID = os.environ["SHEET_ID"]
GOOGLE_CREDS = json.loads(os.environ["GOOGLE_CREDS"])

# subreddits to search
SUBREDDITS = [
    "realtors",
    "RealEstate",
    "RealEstateInvesting",
    "smallbusiness",
    "entrepreneur",
    "freelance",
    "indiabusiness",
    "IndiaInvestments",
]

# pain keywords — things real estate agents say when struggling
PAIN_KEYWORDS = [
    "follow up",
    "losing leads",
    "missed lead",
    "can't keep up",
    "overwhelmed",
    "manually",
    "too many leads",
    "no time",
    "forgot to call",
    "lead went cold",
    "ghost",
    "ghosted",
    "no response",
    "spreadsheet",
    "keeping track",
    "CRM",
    "drowning",
    "busy showing",
    "missed call",
    "too busy",
]

REDDIT_HEADERS = {
    "User-Agent": "ZubhaiResearch/1.0 (research bot)"
}


def get_sheet():
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(GOOGLE_CREDS, scopes=scopes)
    client = gspread.authorize(creds)
    try:
        sheet = client.open_by_key(SHEET_ID).worksheet("Reddit")
    except:
        sh = client.open_by_key(SHEET_ID)
        sheet = sh.add_worksheet(title="Reddit", rows="1000", cols="12")
    return sheet


def ensure_headers(sheet):
    headers = sheet.row_values(1)
    if not headers:
        sheet.append_row([
            "Username", "Subreddit", "Post Title",
            "Pain Quote",  # exact words they used
            "Post URL", "Contact Info",
            "Pain Point", "AI Draft", "Your Message",
            "Status", "Sent On", "Scraped On"
        ])


def get_existing_urls(sheet):
    records = sheet.get_all_records()
    return set(r.get("Post URL", "") for r in records)


def extract_contact_from_text(text):
    """sometimes people share email/phone in posts"""
    email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    phone_pattern = r'[\+]?[0-9]{10,13}'
    emails = re.findall(email_pattern, text or "")
    phones = re.findall(phone_pattern, text or "")
    contact = ""
    if emails:
        contact += emails[0]
    if phones:
        contact += f" | {phones[0]}" if contact else phones[0]
    return contact


def find_pain_quote(text, keywords):
    """extract the sentence that contains the pain keyword"""
    if not text:
        return ""
    sentences = re.split(r'[.!?\n]', text)
    for keyword in keywords:
        for sentence in sentences:
            if keyword.lower() in sentence.lower():
                clean = sentence.strip()
                if len(clean) > 20:  # not too short
                    return clean[:200]  # max 200 chars
    return ""


def search_subreddit(subreddit, keyword, limit=10):
    """search a subreddit for posts containing keyword"""
    url = f"https://www.reddit.com/r/{subreddit}/search.json"
    params = {
        "q": keyword,
        "restrict_sr": "true",
        "sort": "new",
        "limit": limit,
        "t": "month",  # last month only
    }
    try:
        resp = requests.get(url, headers=REDDIT_HEADERS, params=params, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("data", {}).get("children", [])
        return []
    except Exception as e:
        print(f"    reddit error: {e}")
        return []


def main():
    print("🔴 starting Reddit scraper...")
    sheet = get_sheet()
    ensure_headers(sheet)
    existing_urls = get_existing_urls(sheet)
    today = datetime.now().strftime("%Y-%m-%d")

    total_added = 0

    for subreddit in SUBREDDITS:
        for keyword in PAIN_KEYWORDS[:8]:  # top 8 keywords to stay within rate limits
            print(f"  r/{subreddit} — '{keyword}'")
            posts = search_subreddit(subreddit, keyword)

            for post_data in posts:
                post = post_data.get("data", {})
                url = f"https://reddit.com{post.get('permalink', '')}"

                if url in existing_urls:
                    continue

                title = post.get("title", "")
                body = post.get("selftext", "")
                full_text = f"{title} {body}"
                username = post.get("author", "")

                # skip deleted/bot accounts
                if username in ["[deleted]", "AutoModerator", ""]:
                    continue

                # find exact pain quote
                pain_quote = find_pain_quote(full_text, PAIN_KEYWORDS)
                if not pain_quote:
                    continue  # no clear pain signal, skip

                contact = extract_contact_from_text(full_text)

                row = [
                    username,
                    subreddit,
                    title[:150],
                    pain_quote,
                    url,
                    contact,
                    "",  # pain point — researcher fills
                    "",  # ai draft — researcher fills
                    "",  # your message
                    "",  # status
                    "",  # sent on
                    today,
                ]
                sheet.append_row(row)
                existing_urls.add(url)
                total_added += 1

            time.sleep(1.5)  # respect reddit rate limits

    print(f"\n✅ Reddit done. total new: {total_added}")


if __name__ == "__main__":
    main()
