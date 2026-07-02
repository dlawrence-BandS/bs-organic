"""
fetch_ig_insights.py
--------------------
Fetches 5 data sources from the Instagram Graph API and saves them
to the data/ folder for the organic social dashboard.

TOKEN SETUP:
  Create a file called 'ig_token.txt' in the bs-organic folder
  with just the access token on one line (nothing else).
  Get token from: developers.facebook.com/tools/explorer → me/accounts
  → copy the access_token value from Barker and Stonehouse.

Usage:
  python scripts/fetch_ig_insights.py

Requires: pip install requests
"""

import json, time
from datetime import datetime, timedelta
from pathlib import Path
import requests

IG_ID   = "17841400079643420"
BASE    = "https://graph.facebook.com/v25.0"
DATA    = Path("data")

# Read token from file to avoid paste corruption issues
TOKEN_FILE = Path("ig_token.txt")
if not TOKEN_FILE.exists():
    print("ERROR: ig_token.txt not found.")
    print("Create ig_token.txt in the bs-organic folder with just your access token on one line.")
    print("Get token from: developers.facebook.com/tools/explorer → me/accounts")
    exit(1)

TOKEN = TOKEN_FILE.read_text().strip()
print(f"Token loaded ({len(TOKEN)} chars)")

def get(url, params=None, retries=3):
    p = dict(params or {})
    p["access_token"] = TOKEN
    for attempt in range(retries):
        try:
            r = requests.get(url, params=p, timeout=20)
            if r.status_code != 200:
                print(f"  ✗ {r.status_code}: {r.text[:120]}")
                return None
            return r.json()
        except Exception as e:
            if attempt < retries-1:
                time.sleep(2)
            else:
                print(f"  ✗ Connection error: {e}")
                return None

def save(filename, data):
    path = DATA / filename
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"  ✓ Saved {path}")

# ── 1. ACCOUNT BASICS ──
print("\n[1/5] Account basics...")
account = get(f"{BASE}/{IG_ID}", {"fields": "id,username,name,biography,followers_count,follows_count,media_count,profile_picture_url,website"})
if account:
    save("ig_account.json", account)
    print(f"  @{account.get('username')} | {account.get('followers_count',0):,} followers")

# ── 2. ACCOUNT INSIGHTS (max 30 days per call) ──
print("\n[2/5] Account insights (last 30 days)...")
since = int((datetime.now() - timedelta(days=29)).timestamp())
until = int(datetime.now().timestamp())

insights_data = {"updated_at": datetime.now().isoformat()+"Z", "metrics": {}}

# v25 supported daily metrics
daily_metrics = [
    ("reach",           "day"),
    ("follower_count",  "day"),
    ("website_clicks",  "day"),
    ("profile_views",   "day"),
    ("accounts_engaged","day"),
    ("total_interactions", "day"),    ("likes",           "day"),
    ("comments",        "day"),
]

TOTAL_VALUE_METRICS = {"profile_views","website_clicks","accounts_engaged","total_interactions","likes","comments"}

for metric, period in daily_metrics:
    params = {
        "metric": metric,
        "period": period,
        "since":  since,
        "until":  until,
    }
    if metric in TOTAL_VALUE_METRICS:
        params["metric_type"] = "total_value"
    result = get(f"{BASE}/{IG_ID}/insights", params)
    if result and result.get("data"):
        d = result["data"][0]
        # Handle both value formats
        if "total_value" in d:
            insights_data["metrics"][metric] = d["total_value"].get("breakdowns",[]) or d["total_value"]
        elif "values" in d:
            insights_data["metrics"][metric] = d["values"]
        else:
            insights_data["metrics"][metric] = d
        print(f"  ✓ {metric}")
    time.sleep(0.25)

save("ig_insights.json", insights_data)

# ── 3. STORIES ──
print("\n[3/5] Stories...")
stories_data = {"updated_at": datetime.now().isoformat()+"Z", "stories": []}
result = get(f"{BASE}/{IG_ID}/stories", {"fields": "id,timestamp,media_type,media_url,thumbnail_url"})
if result and result.get("data"):
    for story in result["data"]:
        ins = get(f"{BASE}/{story['id']}/insights", {"metric": "views,reach,replies"})
        metrics = {}
        if ins and ins.get("data"):
            for m in ins["data"]:
                metrics[m["name"]] = m.get("values",[{}])[0].get("value",0) if m.get("values") else m.get("total_value",0)
        stories_data["stories"].append({**story, "insights": metrics})
        time.sleep(0.15)
    print(f"  {len(stories_data['stories'])} active stories")
else:
    print("  No active stories (expire after 24hrs)")
save("ig_stories.json", stories_data)

# ── 4. AUDIENCE DEMOGRAPHICS ──
print("\n[4/5] Audience demographics...")
audience_data = {"updated_at": datetime.now().isoformat()+"Z"}

# v25 demographics: metric=follower_demographics, ONE breakdown per call,
# period=lifetime + timeframe + metric_type=total_value all required
demo_calls = [
    ("audience_age",     "follower_demographics", {"breakdown": "age"}),
    ("audience_gender",  "follower_demographics", {"breakdown": "gender"}),
    ("audience_city",    "follower_demographics", {"breakdown": "city"}),
    ("audience_country", "follower_demographics", {"breakdown": "country"}),
    # best-effort combined (some versions accept multi-breakdown; harmless if it 400s)
    ("audience_gender_age", "follower_demographics", {"breakdown": "age,gender"}),
]

for key, metric, extra in demo_calls:
    params = {"metric": metric, "period": "lifetime", "timeframe": "this_month", "metric_type": "total_value", **extra}
    result = get(f"{BASE}/{IG_ID}/insights", params)
    if result and result.get("data"):
        d = result["data"][0]
        tv = d.get("total_value", {})
        bds = tv.get("breakdowns", [])
        if bds:
            # Flatten breakdown into dict
            flat = {}
            for bd in bds:
                for item in bd.get("results", []):
                    dim_values = item.get("dimension_values", [])
                    val = item.get("value", 0)
                    label = " ".join(dim_values)
                    flat[label] = val
            audience_data[key] = flat
            print(f"  ✓ {key}: {len(flat)} entries")
        else:
            audience_data[key] = {}
    else:
        audience_data[key] = {}
    time.sleep(0.3)

save("ig_audience.json", audience_data)

# ── 5. UPDATE POST METRICS (only for posts in owned_social.json) ──
print("\n[5/5] Refreshing metrics for dashboard posts only...")
posts = json.load(open(DATA / "owned_social.json", encoding="utf-8"))

# Extract shortcodes from permalinks to get media IDs
def get_shortcode(permalink):
    import re
    m = re.search(r'/(reel|p)/([A-Za-z0-9_-]+)', permalink)
    return m.group(2) if m else None

# First get a lookup of shortcode -> media_id from the API
print(f"  Fetching media IDs for {len(posts)} posts...")
all_media = []
url = f"{BASE}/{IG_ID}/media"
after = None
page = 1
while True:
    params = {"fields": "id,permalink,like_count,comments_count,media_type,shortcode", "limit": 50, "access_token": TOKEN}
    if after:
        params["after"] = after
    r = requests.get(url, params=params, timeout=20)
    data = r.json()
    items = data.get("data", [])
    if not items:
        break
    all_media.extend(items)
    cursor = data.get("paging", {}).get("cursors", {}).get("after")
    if not data.get("paging", {}).get("next") or not cursor:
        break
    after = cursor
    page += 1
    time.sleep(0.2)
    # Stop once we have enough — our posts are all recent
    if len(all_media) >= 300:
        print(f"  Fetched {len(all_media)} recent media items — stopping")
        break

print(f"  Got {len(all_media)} media items")

# Build permalink -> media_id map
pl_to_id = {}
for item in all_media:
    pl = item.get("permalink","").rstrip("/")+"/"
    pl_to_id[pl] = item

# Fetch insights only for our 229 posts
updated = 0
for i, post in enumerate(posts):
    pl = post.get("permalink","").rstrip("/")+"/"
    media_item = pl_to_id.get(pl)
    if not media_item:
        continue

    mid = media_item["id"]
    ins = get(f"{BASE}/{mid}/insights", {"metric": "reach,saved,shares,likes,comments,total_interactions"})
    if not ins:
        ins = get(f"{BASE}/{mid}/insights", {"metric": "reach,saved"})

    m = {}
    if ins and ins.get("data"):
        for entry in ins["data"]:
            m[entry["name"]] = entry.get("values",[{}])[0].get("value",0) if entry.get("values") else entry.get("total_value",0)

    if m.get("reach",0) > 0:
        post["reach"]      = m.get("reach",0)
        post["likes"]      = media_item.get("like_count", m.get("likes",0))
        post["comments"]   = media_item.get("comments_count", m.get("comments",0))
        post["saves"]      = m.get("saved",0)
        post["shares"]     = m.get("shares",0)
        post["engagement"] = m.get("total_interactions",0) or post["likes"]+post["comments"]+post["saves"]+post["shares"]
        post["api_refreshed"] = datetime.now().isoformat()+"Z"
        updated += 1

    label = post.get('date', str(i+1))
    print(f"  {i+1}/{len(posts)}: {label} ✓" if m.get("reach",0) > 0 else f"  {i+1}/{len(posts)}: {label} (no reach data)")
    time.sleep(0.2)

print(f"\n  Updated {updated}/{len(posts)} posts with fresh metrics")
save("owned_social.json", posts)

print(f"\n✓ Done! Files saved to data/")
