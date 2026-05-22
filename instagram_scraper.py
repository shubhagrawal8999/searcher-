"""
instagram_scraper.py
searches real estate hashtags on Instagram
extracts: name, email/phone from bio, latest post caption
writes to Google Sheet
runs daily via GitHub Actions
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

# real estate hashtags — India focused + global
HASHTAGS = [
    "realestateindia",
    "mumbairealestate",
    "delhirealestate",
    "puneproperties",
    "bangalorerealestate",
    "hyderabadrealestate",
    "realestateagentindia",
    "propertyinmumbai",
    "indianrealtor",
    "realestatebroker",
    "realtorlife",
    "realestateagent",
    "propertydealers",
    "homesofinstagram",
    "luxuryrealestate",
]

MAX_POSTS_PER_HASHTAG = 20  # 15 hashtags x 20 = 300 profiles max


def get_sheet():
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(GOOGLE_CREDS, scopes=scopes)
    client = gspread.authorize(creds)
    # use second sheet tab "Instagram"
    try:
        sheet = client.open_by_key(SHEET_ID).worksheet("Instagram")
    except:
        # create tab if doesn't exist
        sh = client.open_by_key(SHEET_ID)
        sheet = sh.add_worksheet(title="Instagram", rows="1000", cols="15")
    return sheet


def ensure_headers(sheet):
    headers = sheet.row_values(1)
    if not headers:
        sheet.append_row([
            "Name", "Username", "Email", "Phone",
            "Bio", "Latest Post", "Profile URL",
            "Pain Point", "AI Draft", "Your Email",
            "Status", "Sent On", "Source", "Scraped On"
        ])


def get_existing_usernames(sheet):
    records = sheet.get_all_records()
    return set(r.get("Username", "") for r in records)


def extract_email(text):
    """extract email from bio text"""
    if not text:
        return ""
    pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    emails = re.findall(pattern, text)
    # filter out common false positives
    filtered = [e for e in emails if not any(x in e.lower() for x in ['example', 'email', 'youremail'])]
    return filtered[0] if filtered else ""


def extract_phone(text):
    """extract phone number from bio text"""
    if not text:
        return ""
    # matches Indian and international formats
    pattern = r'[\+]?[(]?[0-9]{1,4}[)]?[-\s\.]?[(]?[0-9]{1,4}[)]?[-\s\.]?[0-9]{4,6}[-\s\.]?[0-9]{0,4}'
    phones = re.findall(pattern, text)
    # filter short false positives
    valid = [p.strip() for p in phones if len(re.sub(r'\D', '', p)) >= 10]
    return valid[0] if valid else ""


def scrape_hashtag(hashtag):
    """scrape Instagram profiles from a hashtag"""
    client = ApifyClient(APIFY_TOKEN)

    run_input = {
        "hashtags": [hashtag],
        "resultsLimit": MAX_POSTS_PER_HASHTAG,
        "scrapePostComments": False,
    }

    try:
        run = client.actor("apify/instagram-hashtag-scraper").call(run_input=run_input)
        posts = list(client.dataset(run["defaultDatasetId"]).iterate_items())
        return posts
    except Exception as e:
        print(f"  hashtag scraper error: {e}")
        # fallback to profile scraper
        return []


def scrape_profiles_from_posts(posts):
    """extract unique profiles from post results"""
    profiles = {}
    for post in posts:
        owner = post.get("ownerUsername", "")
        if not owner or owner in profiles:
            continue
        bio = post.get("ownerBio", "") or ""
        full_name = post.get("ownerFullName", "") or owner
        caption = post.get("caption", "") or ""

        profiles[owner] = {
            "name": full_name,
            "username": owner,
            "email": extract_email(bio),
            "phone": extract_phone(bio),
            "bio": bio[:200],  # first 200 chars
            "latest_post": caption[:300],  # first 300 chars of caption
            "profile_url": f"https://instagram.com/{owner}",
        }
    return list(profiles.values())


def write_to_sheet(sheet, profiles, existing_usernames):
    added = 0
    today = datetime.now().strftime("%Y-%m-%d")

    for p in profiles:
        if p["username"] in existing_usernames:
            continue
        # only keep profiles with email OR phone
        if not p["email"] and not p["phone"]:
            continue

        row = [
            p["name"],
            p["username"],
            p["email"],
            p["phone"],
            p["bio"],
            p["latest_post"],
            p["profile_url"],
            "",  # pain point — filled by researcher
            "",  # ai draft — filled by researcher
            "",  # your email — filled by you
            "",  # status
            "",  # sent on
            f"Instagram #{p.get('source_hashtag', '')}",
            today,
        ]
        sheet.append_row(row)
        existing_usernames.add(p["username"])
        added += 1

    return added


def main():
    print("📸 starting Instagram scraper...")
    sheet = get_sheet()
    ensure_headers(sheet)
    existing_usernames = get_existing_usernames(sheet)

    total_added = 0

    for hashtag in HASHTAGS:
        print(f"  scraping: #{hashtag}")
        try:
            posts = scrape_hashtag(hashtag)
            profiles = scrape_profiles_from_posts(posts)

            # tag source hashtag
            for p in profiles:
                p["source_hashtag"] = hashtag

            added = write_to_sheet(sheet, profiles, existing_usernames)
            total_added += added
            print(f"  ✓ {len(profiles)} profiles found → {added} new added")

        except Exception as e:
            print(f"  ✗ failed #{hashtag}: {e}")

    print(f"\n✅ Instagram done. total new: {total_added}")


if __name__ == "__main__":
    main()
