"""
facebook_scraper.py
scrapes Facebook groups for real estate agents posting pain
extracts: name, post content, pain signal, contact if visible
writes to Google Sheet "Facebook" tab
runs daily via GitHub Actions
uses Apify Facebook Groups scraper
"""

import os
import re
import gspread
import json
from apify_client import ApifyClient
from google.oauth2.service_account import Credentials
from datetime import datetime

# --- config ---
APIFY_TOKEN = os.environ["APIFY_TOKEN"]
SHEET_ID = os.environ["SHEET_ID"]
GOOGLE_CREDS = json.loads(os.environ["GOOGLE_CREDS"])

# Facebook groups — real estate agents India + global
# these are public groups — no login needed
FACEBOOK_GROUPS = [
    "https://www.facebook.com/groups/realestateindianetwork",
    "https://www.facebook.com/groups/indianrealestateagents",
    "https://www.facebook.com/groups/realestateentrepreneurs",
    "https://www.facebook.com/groups/realestatebusiness",
    "https://www.facebook.com/groups/realtorsofinstagram",
    "https://www.facebook.com/groups/smallbusinessowners",
    "https://www.facebook.com/groups/entrepreneursofIndia",
]

PAIN_KEYWORDS = [
    "follow up",
    "losing leads",
    "overwhelmed",
    "manually",
    "no time",
    "forgot",
    "missed",
    "ghost",
    "spreadsheet",
    "drowning",
    "busy",
    "too many",
    "can't keep",
    "help",
    "struggling",
    "nightmare",
    "pain",
    "waste time",
]


def get_sheet():
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(GOOGLE_CREDS, scopes=scopes)
    client = gspread.authorize(creds)
    try:
        sheet = client.open_by_key(SHEET_ID).worksheet("Facebook")
    except:
        sh = client.open_by_key(SHEET_ID)
        sheet = sh.add_worksheet(title="Facebook", rows="1000", cols="12")
    return sheet


def ensure_headers(sheet):
    headers = sheet.row_values(1)
    if not headers:
        sheet.append_row([
            "Name", "Profile URL", "Group",
            "Pain Quote",
            "Post URL", "Contact Info",
            "Pain Point", "AI Draft", "Your Message",
            "Status", "Sent On", "Scraped On"
        ])


def get_existing_urls(sheet):
    records = sheet.get_all_records()
    return set(r.get("Post URL", "") for r in records)


def extract_contact(text):
    if not text:
        return ""
    email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    phone_pattern = r'[\+]?[0-9]{10,13}'
    emails = re.findall(email_pattern, text)
    phones = re.findall(phone_pattern, text)
    parts = []
    if emails:
        parts.append(emails[0])
    if phones:
        parts.append(phones[0])
    return " | ".join(parts)


def find_pain_quote(text):
    if not text:
        return ""
    sentences = re.split(r'[.!?\n]', text)
    for keyword in PAIN_KEYWORDS:
        for sentence in sentences:
            if keyword.lower() in sentence.lower():
                clean = sentence.strip()
                if len(clean) > 15:
                    return clean[:200]
    return ""


def has_pain_signal(text):
    if not text:
        return False
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in PAIN_KEYWORDS)


def scrape_group(group_url):
    client = ApifyClient(APIFY_TOKEN)
    run_input = {
        "startUrls": [{"url": group_url}],
        "maxPosts": 30,
        "maxPostComments": 0,  # skip comments for speed
        "maxProfileImageDownloads": 0,
    }
    try:
        run = client.actor("apify/facebook-groups-scraper").call(run_input=run_input)
        posts = list(client.dataset(run["defaultDatasetId"]).iterate_items())
        return posts
    except Exception as e:
        print(f"  facebook error: {e}")
        return []


def main():
    print("📘 starting Facebook scraper...")
    sheet = get_sheet()
    ensure_headers(sheet)
    existing_urls = get_existing_urls(sheet)
    today = datetime.now().strftime("%Y-%m-%d")
    total_added = 0

    for group_url in FACEBOOK_GROUPS:
        group_name = group_url.split("/groups/")[-1]
        print(f"  scraping group: {group_name}")

        posts = scrape_group(group_url)
        print(f"  found {len(posts)} posts")

        for post in posts:
            post_url = post.get("url", "") or post.get("postUrl", "")
            if not post_url or post_url in existing_urls:
                continue

            text = post.get("text", "") or post.get("message", "") or ""
            if not has_pain_signal(text):
                continue  # skip posts with no pain signal

            pain_quote = find_pain_quote(text)
            if not pain_quote:
                continue

            name = post.get("authorName", "") or post.get("author", {}).get("name", "")
            profile_url = post.get("authorUrl", "") or ""
            contact = extract_contact(text)

            row = [
                name,
                profile_url,
                group_name,
                pain_quote,
                post_url,
                contact,
                "",  # pain point
                "",  # ai draft
                "",  # your message
                "",  # status
                "",  # sent on
                today,
            ]
            sheet.append_row(row)
            existing_urls.add(post_url)
            total_added += 1

        print(f"  ✓ added posts with pain signal from {group_name}")

    print(f"\n✅ Facebook done. total new: {total_added}")


if __name__ == "__main__":
    main()
