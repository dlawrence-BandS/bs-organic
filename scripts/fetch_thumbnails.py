"""
fetch_thumbnails.py
-------------------
Fetches thumbnail URLs for all B&S Instagram posts from the Graph API
and adds them to data/owned_social.json.

Run once (or after adding new posts) from the bs-organic repo root:
  python scripts/fetch_thumbnails.py

Requires: pip install requests
"""

import json, time, sys
import requests

IG_ACCOUNT_ID = "17841400079643420"

# Paste your page access token here (from Graph API Explorer)
# Token from me/accounts response for Barker and Stonehouse page
PAGE_TOKEN = "EAAGHkHhmf4kBR19co3RdkvHBBlCxljFN4bs0tZCx89dTINlOHaX8K4d4ZCXGWk8LnSFLaIJgaloZBfKfTMm4a1ZANsyoRPtKGDQb2Mhl5RU2XUmKvpKVe6GgDzAuXIH3jJJnaQOq58O7czBO8BVHPxCZBnBZCWlybynRp08XZAZCcLo1cYs0MzhQmnOTtaYBo8pZC37WM1IoqKxhNQSYbYZAJyZA8eI1rZBzNctqAJUZD"

DATA_PATH = "data/owned_social.json"

def fetch_all_media():
    """Fetch all media from IG account, paginating through results."""
    all_media = []
    url = (
        f"https://graph.facebook.com/v25.0/{IG_ACCOUNT_ID}/media"
        f"?fields=id,permalink,thumbnail_url,media_url,media_type,timestamp"
        f"&limit=50&access_token={PAGE_TOKEN}"
    )

    page = 1
    while url:
        print(f"  Fetching page {page}...", end=" ")
        r = requests.get(url, timeout=15)
        if r.status_code != 200:
            print(f"\n  Error {r.status_code}: {r.text[:200]}")
            break
        data = r.json()
        items = data.get("data", [])
        all_media.extend(items)
        print(f"{len(items)} items (total: {len(all_media)})")
        url = data.get("paging", {}).get("next")
        page += 1
        time.sleep(0.25)

    return all_media

def main():
    print("Fetching media from Instagram Graph API...")
    media = fetch_all_media()
    print(f"\nTotal media fetched: {len(media)}")

    # Build permalink -> thumbnail map
    thumb_map = {}
    for item in media:
        pl = item.get("permalink", "").rstrip("/") + "/"
        # Reels have thumbnail_url, images have media_url
        thumb = item.get("thumbnail_url") or item.get("media_url")
        if pl and thumb:
            thumb_map[pl] = thumb

    print(f"Thumbnails mapped: {len(thumb_map)}")

    # Load existing data
    with open(DATA_PATH, encoding="utf-8") as f:
        posts = json.load(f)

    # Inject thumbnails
    matched = 0
    for post in posts:
        pl = post.get("permalink", "").rstrip("/") + "/"
        if pl in thumb_map:
            post["thumbnail_url"] = thumb_map[pl]
            matched += 1

    print(f"Posts updated with thumbnails: {matched} / {len(posts)}")

    # Save
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(posts, f, indent=2, ensure_ascii=False)
    print(f"✓ Saved {DATA_PATH}")

    # Show unmatched
    unmatched = [p for p in posts if not p.get("thumbnail_url")]
    if unmatched:
        print(f"\n{len(unmatched)} posts without thumbnails:")
        for p in unmatched[:5]:
            print(f"  {p['date']} {p.get('permalink','no permalink')[:60]}")

if __name__ == "__main__":
    main()
