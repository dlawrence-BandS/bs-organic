"""
fetch_thumbnails.py
-------------------
Downloads post thumbnails into a local thumbs/ folder and points
data/owned_social.json at those local files.

WHY LOCAL: Instagram CDN URLs are signed and expire after ~4 days
(the oe= parameter is a hex expiry timestamp). Hotlinking them means
every image on the dashboard breaks within a week. Downloading them
into the repo once means they never expire.

Safe to re-run any time — posts that already have a local thumbnail
on disk are skipped, so it only downloads what's missing.

TOKEN SETUP:
  Reads ig_token.txt from the repo root (never hardcode tokens here -
  the repo is public).

Usage (from the bs-organic repo root):
  py scripts\\fetch_thumbnails.py

Requires: pip install requests
"""

import json, time
from pathlib import Path
import requests

IG_ACCOUNT_ID = "17841400079643420"
BASE = "https://graph.facebook.com/v25.0"
DATA_PATH = Path("data/owned_social.json")
THUMBS_DIR = Path("thumbs")

TOKEN_FILE = Path("ig_token.txt")
if not TOKEN_FILE.exists():
    print("ERROR: ig_token.txt not found in the repo root.")
    print("Get token from: developers.facebook.com/tools/explorer -> me/accounts")
    raise SystemExit(1)
TOKEN = TOKEN_FILE.read_text().strip()


def fetch_all_media(needed_count):
    """Fetch media from the IG account, paginating until we have enough."""
    all_media = []
    url = (
        f"{BASE}/{IG_ACCOUNT_ID}/media"
        f"?fields=id,permalink,thumbnail_url,media_url,media_type,timestamp"
        f"&limit=50&access_token={TOKEN}"
    )
    page = 1
    while url:
        print(f"  Fetching media page {page}...", end=" ")
        r = requests.get(url, timeout=15)
        if r.status_code != 200:
            print(f"\n  Error {r.status_code}: {r.text[:200]}")
            break
        data = r.json()
        items = data.get("data", [])
        all_media.extend(items)
        print(f"{len(items)} items (total: {len(all_media)})")
        # Our dashboard only covers posts from Jul 2025 onwards — stop once
        # we've paged past the oldest one we could possibly need.
        if items and items[-1].get("timestamp", "")[:10] < "2025-06-01":
            print("  Reached posts older than the dashboard window - stopping")
            break
        url = data.get("paging", {}).get("next")
        page += 1
        time.sleep(0.25)
    return all_media


def main():
    THUMBS_DIR.mkdir(exist_ok=True)
    posts = json.load(open(DATA_PATH, encoding="utf-8"))

    # Which posts need a thumbnail downloaded?
    def has_local_thumb(p):
        t = p.get("thumbnail_url", "")
        return t.startswith("thumbs/") and (Path(t).exists())

    missing = [p for p in posts if not has_local_thumb(p)]
    print(f"Posts needing local thumbnails: {len(missing)} / {len(posts)}")
    if not missing:
        print("Nothing to do - all thumbnails already local.")
        return

    print("Fetching fresh media URLs from Instagram Graph API...")
    media = fetch_all_media(len(missing))

    # permalink -> fresh CDN url
    url_map = {}
    for item in media:
        pl = item.get("permalink", "").rstrip("/") + "/"
        thumb = item.get("thumbnail_url") or item.get("media_url")
        if pl and thumb:
            url_map[pl] = thumb

    downloaded, failed = 0, 0
    for p in missing:
        pl = p.get("permalink", "").rstrip("/") + "/"
        cdn_url = url_map.get(pl)
        if not cdn_url:
            failed += 1
            continue
        dest = THUMBS_DIR / f"{p['id']}.jpg"
        try:
            r = requests.get(cdn_url, timeout=20)
            if r.status_code == 200 and r.content:
                dest.write_bytes(r.content)
                p["thumbnail_url"] = f"thumbs/{p['id']}.jpg"
                downloaded += 1
                if downloaded % 25 == 0:
                    print(f"  {downloaded} downloaded...")
            else:
                failed += 1
        except Exception as e:
            print(f"  x {p['date']}: {e}")
            failed += 1
        time.sleep(0.15)

    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(posts, f, indent=2, ensure_ascii=False)

    print(f"\nOK Downloaded {downloaded} thumbnails to {THUMBS_DIR}/")
    if failed:
        print(f"   {failed} posts had no matching media / failed download")
    print(f"OK Saved {DATA_PATH}")
    print("\nRemember: git add thumbs/ data/ before committing (refresh.bat does this).")


if __name__ == "__main__":
    main()
