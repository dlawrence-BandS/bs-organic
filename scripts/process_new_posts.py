"""
process_new_posts.py
--------------------
Discovers NEW Instagram posts via the Graph API (no CSV export needed),
auto-classifies them into the 16 dashboard themes, fetches their insights,
and appends them to data/owned_social.json.

Existing posts are never modified by this script (fetch_ig_insights.py
handles refreshing their metrics).

TOKEN SETUP:
  Reads ig_token.txt from the repo root (same as fetch_ig_insights.py).
  Get token from: developers.facebook.com/tools/explorer -> me/accounts
  -> copy the access_token value for Barker and Stonehouse.

Usage (from the bs-organic repo root):
  py scripts\\process_new_posts.py

Requires: pip install requests
"""

import json, time, re
from datetime import datetime
from pathlib import Path
import requests

IG_ID = "17841400079643420"
BASE  = "https://graph.facebook.com/v25.0"
DATA  = Path("data")
POSTS_FILE = DATA / "owned_social.json"

# ── Token ──────────────────────────────────────────────────────────────
TOKEN_FILE = Path("ig_token.txt")
if not TOKEN_FILE.exists():
    print("ERROR: ig_token.txt not found in the repo root.")
    print("Get token from: developers.facebook.com/tools/explorer -> me/accounts")
    raise SystemExit(1)
TOKEN = TOKEN_FILE.read_text().strip()
print(f"Token loaded ({len(TOKEN)} chars)")

# ── Theme classifier ───────────────────────────────────────────────────
# Ordered rules — first match wins. Product themes take priority
# (validated at 76% agreement against the original 229 classified posts).
THEME_RULES = [
    ("Ercol", ["ercol"]),
    ("Garden & Outdoor", ["garden", "outdoor", "patio", "alfresco", "al fresco", "terrace", "parasol"]),
    ("Dining", ["dining", "table"]),
    ("Sofas", ["sofa", "couch", "snuggler", "corner suite", "footstool"]),
    ("Armchairs", ["armchair", "accent chair", "swivel chair", "recliner", " chair "]),
    ("Bedroom", ["bedroom", "bed frame", "bedside", "mattress", "headboard", "wardrobe", "duvet", "bedding", " bed "]),
    ("Storage", ["sideboard", "cabinet", "bookcase", "shelving", "drawers", "console", "storage", "display unit"]),
    ("Christmas", ["christmas", "festive", "xmas", "advent", "wreath", "\U0001f384"]),
    ("Promotions & Sales", ["% off", "summer sale", "winter sale", "autumn offers", "offers start",
                            "final day", "discount", "clearance", "scratchcard", "for less", "sale!", "our sale"]),
    ("Seasonal Looks", ["new look", "latest look", "rustic modern", "organic joy", "warm contemporary",
                        "modern minded", "spirited scandi", "spring collection", "autumn look", "new season with"]),
    ("Brand Collaborations", ["orla kiely", "x linwood", "linwood edit", "collaboration with", "in collaboration"]),
    ("Customer Features", ["jarrold", "stockist"]),
    ("Behind the Scenes", ["behind the scenes", "bts", "filming", "photoshoot", "tv ad",
                           "curtain twitchers", "our team", "life and soul of our business"]),
    ("80th Anniversary", ["80th", "80 years"]),
    ("Style & Trends", ["trend", "styling", "stylist", "styled", "palette", "inspo", "inspiration",
                        "interior", "new arrivals", "newest arrivals", "colour", "style"]),
]

def classify_theme(caption):
    d = " " + (caption or "").lower().replace("\n", " ") + " "
    for theme, keywords in THEME_RULES:
        if any(k in d for k in keywords):
            return theme
    return "General"

TYPE_MAP = {"IMAGE": "Static", "VIDEO": "Reel", "CAROUSEL_ALBUM": "Carousel"}

# ── API helpers ────────────────────────────────────────────────────────
def get(url, params=None, retries=3, quiet=False):
    p = dict(params or {})
    p["access_token"] = TOKEN
    for attempt in range(retries):
        try:
            r = requests.get(url, params=p, timeout=20)
            if r.status_code != 200:
                if not quiet:
                    print(f"  x {r.status_code}: {r.text[:120]}")
                return None
            return r.json()
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2)
            else:
                print(f"  x Connection error: {e}")
                return None

def fetch_post_insights(media_id):
    """Fetch insights with graceful fallbacks for metric availability."""
    metric_sets = [
        "views,reach,saved,shares,likes,comments,total_interactions,follows",
        "views,reach,saved,shares,likes,comments,total_interactions",
        "reach,saved,shares,likes,comments,total_interactions",
        "reach,saved",
    ]
    for i, metrics in enumerate(metric_sets):
        ins = get(f"{BASE}/{media_id}/insights", {"metric": metrics}, quiet=(i < len(metric_sets) - 1))
        if ins and ins.get("data"):
            m = {}
            for entry in ins["data"]:
                if entry.get("values"):
                    m[entry["name"]] = entry["values"][0].get("value", 0)
                else:
                    m[entry["name"]] = entry.get("total_value", 0)
            return m
    return {}

# ── Main ───────────────────────────────────────────────────────────────
def main():
    posts = json.load(open(POSTS_FILE, encoding="utf-8"))
    existing_permalinks = {p["permalink"].rstrip("/") + "/" for p in posts}
    latest_date = max(p["date"] for p in posts)
    next_id = max(p["id"] for p in posts) + 1
    print(f"Existing posts: {len(posts)} (latest: {latest_date})")

    # Fetch recent media — stop paginating once we're older than the latest known post
    print("Checking for new posts...")
    all_media, after, done = [], None, False
    while not done:
        params = {"fields": "id,permalink,caption,media_type,media_url,thumbnail_url,timestamp,like_count,comments_count",
                  "limit": 50}
        if after:
            params["after"] = after
        data = get(f"{BASE}/{IG_ID}/media", params)
        if not data or not data.get("data"):
            break
        for item in data["data"]:
            ts = item.get("timestamp", "")[:10]
            if ts and ts <= latest_date:
                # Older than or equal to newest known post — check remaining then stop
                # (still collect same-day items in case of multiple posts that day)
                if ts < latest_date:
                    done = True
                    break
            all_media.append(item)
        after = data.get("paging", {}).get("cursors", {}).get("after")
        if not after or not data.get("paging", {}).get("next"):
            break
        time.sleep(0.2)

    new_items = [m for m in all_media
                 if (m.get("permalink", "").rstrip("/") + "/") not in existing_permalinks
                 and m.get("timestamp", "")[:10] > "2025-06-30"]
    new_items.sort(key=lambda m: m.get("timestamp", ""))

    if not new_items:
        print("No new posts found — owned_social.json is up to date.")
        return

    print(f"Found {len(new_items)} new post(s):")
    for item in new_items:
        date = item["timestamp"][:10]
        caption = item.get("caption", "") or ""
        theme = classify_theme(caption)
        post_type = TYPE_MAP.get(item.get("media_type", ""), "Static")

        print(f"  {date} [{post_type}] -> {theme}: {caption[:60].strip()}...")
        m = fetch_post_insights(item["id"])
        time.sleep(0.2)

        likes = item.get("like_count", m.get("likes", 0)) or 0
        comments = item.get("comments_count", m.get("comments", 0)) or 0
        saves = m.get("saved", 0)
        shares = m.get("shares", 0)

        posts.append({
            "id": next_id,
            "date": date,
            "month": date[:7],
            "post_type": post_type,
            "description": caption,
            "permalink": item.get("permalink", ""),
            "views": m.get("views", 0),
            "reach": m.get("reach", 0),
            "likes": likes,
            "comments": comments,
            "saves": saves,
            "shares": shares,
            "follows": m.get("follows", 0),
            "theme": theme,
            "engagement": m.get("total_interactions", 0) or (likes + comments + saves + shares),
            "thumbnail_url": item.get("thumbnail_url") or item.get("media_url", ""),
            "api_refreshed": datetime.now().isoformat() + "Z",
        })
        next_id += 1

    with open(POSTS_FILE, "w", encoding="utf-8") as f:
        json.dump(posts, f, indent=2, ensure_ascii=False)
    print(f"\nOK Added {len(new_items)} new post(s) — total now {len(posts)}")
    print(f"OK Saved {POSTS_FILE}")

if __name__ == "__main__":
    main()
