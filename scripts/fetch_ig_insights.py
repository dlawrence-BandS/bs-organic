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

SAFETY (added Nov 2026):
  - If the token has expired, or Instagram sends no insights at all, the
    script stops with exit code 1 BEFORE saving anything. refresh.bat then
    stops too, so blank data never gets pushed to the dashboard.
  - If a later step only partly fails, the previous figures are kept
    rather than overwritten with blanks, and a "Heads up" list is printed.

BOOSTED POSTS (added Nov 2026):
  Boosted posts get paid reach and views, which skews the organic numbers.
  Each post is marked boosted: true/false so the dashboard can leave them
  out. A post counts as boosted if Instagram lists an ad for it, or if its
  link is in data/boosted.txt (for any Instagram misses).

ORGANIC vs BOOST NUMBERS (added Nov 2026):
  Instagram's own figures are organic only, so the main post numbers come
  from Instagram. (The older numbers from the Business Suite export included
  ad results on boosted posts; those are kept aside as views_with_ads /
  follows_with_ads.) The boost's paid results come from Meta Ads, using the
  token in meta_ads.token (never uploaded: .gitignore blocks *.token files).
  Without that file the refresh still runs; cards just show organic only.

Usage:
  python scripts/fetch_ig_insights.py

Requires: pip install requests
"""

import json, re, sys, time
from datetime import datetime, timedelta
from pathlib import Path
import requests

IG_ID   = "17841400079643420"
BASE    = "https://graph.facebook.com/v25.0"
DATA    = Path("data")
WARNINGS = []


def stop(reason):
    """Stop before anything is saved, so refresh.bat doesn't push blanks."""
    print()
    print("=" * 64)
    print("  STOPPED: " + reason)
    print("  Nothing has been saved or pushed. The dashboard is unchanged.")
    print()
    print("  1. Get a new token: Graph API Explorer > me/accounts")
    print("  2. Paste it into ig_token.txt and save")
    print("  3. Run refresh.bat again")
    print()
    print("  If a new token doesn't fix it, screenshot this window for Claude.")
    print("=" * 64)
    sys.exit(1)


# Read token from file to avoid paste corruption issues
TOKEN_FILE = Path("ig_token.txt")
if not TOKEN_FILE.exists():
    print("ERROR: ig_token.txt not found.")
    print("Create ig_token.txt in the bs-organic folder with just your access token on one line.")
    print("Get token from: developers.facebook.com/tools/explorer → me/accounts")
    sys.exit(1)

# utf-8-sig drops the hidden marker Notepad sometimes adds, and stray quote
# marks are removed in case the token was copied with them
TOKEN = TOKEN_FILE.read_text(encoding="utf-8-sig", errors="ignore").strip().strip("\"'").strip()
print(f"Token loaded ({len(TOKEN)} chars)")


def get(url, params=None, retries=3, quiet=False, token=None):
    p = dict(params or {})
    p["access_token"] = token or TOKEN
    for attempt in range(retries):
        try:
            r = requests.get(url, params=p, timeout=20)
            if r.status_code != 200:
                if not quiet:
                    print(f"  ✗ {r.status_code}: {r.text[:160]}")
                return None
            return r.json()
        except Exception as e:
            if attempt < retries-1:
                time.sleep(2)
            elif not quiet:
                print(f"  ✗ Connection error: {e}")
    return None


def save(filename, data):
    path = DATA / filename
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"  ✓ Saved {path}")


def load_existing(filename, default):
    try:
        with open(DATA / filename, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def metric_value(entry):
    v = entry["values"][0].get("value", 0) if entry.get("values") else entry.get("total_value", 0)
    if isinstance(v, dict):
        v = v.get("value", 0)
    return v if isinstance(v, (int, float)) else 0


# ── 1. ACCOUNT BASICS (doubles as the token check) ──
print("\n[1/6] Checking the token...")
account = get(f"{BASE}/{IG_ID}", {"fields": "id,username,name,biography,followers_count,follows_count,media_count,profile_picture_url,website"})
if not account or not account.get("id"):
    stop("your Instagram token has expired or is wrong.")
print(f"  ✓ Token works: @{account.get('username')} | {account.get('followers_count',0):,} followers")

# ── 2. ACCOUNT INSIGHTS (max 30 days per call) ──
print("\n[2/6] Account insights (last 30 days)...")
since = int((datetime.now() - timedelta(days=29)).timestamp())
until = int(datetime.now().timestamp())

insights_data = {"updated_at": datetime.now().isoformat()+"Z", "metrics": {}}

# v25 supported daily metrics
daily_metrics = [
    ("reach",              "day"),
    ("follower_count",     "day"),
    ("website_clicks",     "day"),
    ("profile_views",      "day"),
    ("accounts_engaged",   "day"),
    ("total_interactions", "day"),
    ("likes",              "day"),
    ("comments",           "day"),
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

# Nothing back at all = token/permission problem, so stop before saving
if not insights_data["metrics"]:
    stop("Instagram didn't send any insights (usually an expired token).")

# Some metrics missing: keep last refresh's figures for those
old_metrics = load_existing("ig_insights.json", {}).get("metrics", {})
missing = [m for m, _ in daily_metrics if m not in insights_data["metrics"]]
for m in missing:
    if m in old_metrics:
        insights_data["metrics"][m] = old_metrics[m]
if missing:
    WARNINGS.append("Account insights didn't update for: " + ", ".join(missing))

save("ig_account.json", account)
save("ig_insights.json", insights_data)

# ── 3. STORIES ──
print("\n[3/6] Stories...")
result = get(f"{BASE}/{IG_ID}/stories", {"fields": "id,timestamp,media_type,media_url,thumbnail_url"})
if result is None:
    print("  Couldn't fetch stories - keeping the existing file")
    WARNINGS.append("Stories didn't update")
else:
    stories_data = {"updated_at": datetime.now().isoformat()+"Z", "stories": []}
    for story in result.get("data", []):
        ins = get(f"{BASE}/{story['id']}/insights", {"metric": "views,reach,replies"})
        metrics = {}
        if ins and ins.get("data"):
            for m in ins["data"]:
                metrics[m["name"]] = m.get("values",[{}])[0].get("value",0) if m.get("values") else m.get("total_value",0)
        stories_data["stories"].append({**story, "insights": metrics})
        time.sleep(0.15)
    if stories_data["stories"]:
        print(f"  {len(stories_data['stories'])} active stories")
    else:
        print("  No active stories (expire after 24hrs)")
    save("ig_stories.json", stories_data)

# ── 4. AUDIENCE DEMOGRAPHICS ──
print("\n[4/6] Audience demographics...")
old_audience = load_existing("ig_audience.json", {})
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

not_updated = []
for key, metric, extra in demo_calls:
    params = {"metric": metric, "period": "lifetime", "timeframe": "this_month", "metric_type": "total_value", **extra}
    result = get(f"{BASE}/{IG_ID}/insights", params)
    flat = {}
    if result and result.get("data"):
        tv = result["data"][0].get("total_value", {})
        # Flatten breakdown into dict
        for bd in tv.get("breakdowns", []):
            for item in bd.get("results", []):
                label = " ".join(item.get("dimension_values", []))
                flat[label] = item.get("value", 0)
    if flat:
        audience_data[key] = flat
        print(f"  ✓ {key}: {len(flat)} entries")
    else:
        # Keep last refresh's figures rather than blanking the chart
        audience_data[key] = old_audience.get(key) or {}
        not_updated.append(key)
    time.sleep(0.3)

if not_updated:
    print("  Kept previous figures for: " + ", ".join(not_updated))
    WARNINGS.append("Audience didn't update for: " + ", ".join(not_updated))
save("ig_audience.json", audience_data)

# ── 5. UPDATE POST METRICS (only for posts in owned_social.json) ──
print("\n[5/6] Refreshing metrics for dashboard posts...")
posts = json.load(open(DATA / "owned_social.json", encoding="utf-8"))


def norm(permalink):
    return (permalink or "").rstrip("/") + "/"


def shortcode(link):
    m = re.search(r"instagram\.com/(?:[^/?#]+/)?(?:p|reel|reels|tv)/([A-Za-z0-9_-]+)", link or "")
    return m.group(1) if m else None


wanted = {norm(p.get("permalink")) for p in posts if p.get("permalink")}
oldest = min((p.get("date") or "9999")[:10] for p in posts) if posts else ""

# Page through the account's media (newest first) until every dashboard post
# is found. This used to stop at 300 items, which skipped the oldest posts.
# It also asks which posts have been boosted; if Instagram won't say, it
# carries on without that.
print(f"  Finding {len(wanted)} dashboard posts on Instagram...")
MEDIA_FIELDS = "id,permalink,timestamp,like_count,comments_count,media_type"
boost_info = True
pl_to_item, after, pages = {}, None, 0
while pages < 60:
    params = {"fields": MEDIA_FIELDS + (",boost_ads_list" if boost_info else ""), "limit": 50}
    if after:
        params["after"] = after
    data = get(f"{BASE}/{IG_ID}/media", params, quiet=boost_info)
    if data is None and boost_info:
        boost_info = False      # retry this page without the boost question
        continue
    items = (data or {}).get("data", [])
    if not items:
        break
    pages += 1
    for item in items:
        pl = norm(item.get("permalink"))
        if pl in wanted:
            pl_to_item[pl] = item
    last_day = (items[-1].get("timestamp") or "")[:10]
    paging = data.get("paging", {})
    after = paging.get("cursors", {}).get("after")
    if len(pl_to_item) >= len(wanted) or (last_day and last_day < oldest) or not paging.get("next") or not after:
        break
    time.sleep(0.2)

print(f"  Found {len(pl_to_item)}/{len(wanted)} posts")
not_found = len(wanted) - len(pl_to_item)
if not_found and pl_to_item:
    WARNINGS.append(f"{not_found} posts weren't found on Instagram (deleted or archived?), so they kept their old numbers")

# ── BOOSTED POSTS ──
# Instagram's ad list for a post is remembered between runs, so a post stays
# marked once boosted. data/boosted.txt adds any Instagram misses.
BOOST_FILE = DATA / "boosted.txt"
if not BOOST_FILE.exists():
    BOOST_FILE.write_text(
        "# Boosted posts\n"
        "# Posts Instagram reports as boosted are marked automatically.\n"
        "# Paste the link of any it misses below, one per line.\n",
        encoding="utf-8")
listed = set()
for line in BOOST_FILE.read_text(encoding="utf-8-sig", errors="ignore").splitlines():
    code = shortcode(line.strip())
    if code and not line.strip().startswith("#"):
        listed.add(code)


def boost_ad_ids(item):
    b = item.get("boost_ads_list")
    if isinstance(b, dict):
        b = b.get("data", [])
    if not isinstance(b, list):
        return []
    return [str(x.get("ad_id") or x.get("id") or "ad") if isinstance(x, dict) else str(x) for x in b if x]


flags_changed = False
for post in posts:
    item = pl_to_item.get(norm(post.get("permalink")))
    ads = set(post.get("boost_ads") or [])
    if item:
        ads |= set(boost_ad_ids(item))
    if ads:
        post["boost_ads"] = sorted(ads)
    boosted = bool(ads) or shortcode(post.get("permalink")) in listed
    if post.get("boosted") != boosted:
        flags_changed = True
    post["boosted"] = boosted

boosted_posts = sorted((p for p in posts if p["boosted"]), key=lambda p: p.get("date", ""))
how = "checked with Instagram + data\\boosted.txt" if boost_info else "Instagram wouldn't say, so only data\\boosted.txt counts"
print(f"  Boosted posts found: {len(boosted_posts)} ({how})")
for p in boosted_posts:
    print(f"    {p.get('date')}  {p.get('post_type')}  {p.get('theme')}")

BASE_METRICS = "reach,saved,shares,likes,comments,total_interactions"


def post_insights(media_id, media_type):
    # Ask for views too (and follows on non-video posts). If Instagram refuses
    # a metric for that post type, fall back to the shorter lists.
    tries = [f"{BASE_METRICS},views", BASE_METRICS, "reach,saved"]
    if media_type != "VIDEO":
        tries.insert(0, f"{BASE_METRICS},views,follows")
    for metrics in tries:
        ins = get(f"{BASE}/{media_id}/insights", {"metric": metrics}, quiet=True)
        if ins and ins.get("data"):
            return {e["name"]: metric_value(e) for e in ins["data"]}
    return {}


updated = 0
for i, post in enumerate(posts):
    item = pl_to_item.get(norm(post.get("permalink")))
    if not item:
        continue

    m = post_insights(item["id"], item.get("media_type", ""))
    label = post.get("date", str(i+1))

    if m.get("reach", 0) > 0:
        post["reach"]      = m.get("reach", 0)
        post["likes"]      = item.get("like_count", m.get("likes", 0))
        post["comments"]   = item.get("comments_count", m.get("comments", 0))
        post["saves"]      = m.get("saved", 0)
        post["shares"]     = m.get("shares", 0)
        post["engagement"] = m.get("total_interactions", 0) or post["likes"]+post["comments"]+post["saves"]+post["shares"]
        # Instagram's own figures are organic only. The older numbers from the
        # Business Suite export included ad results on boosted posts, so those
        # are kept aside as *_with_ads and the organic figure is shown instead.
        if m.get("views"):
            if post.get("boosted") and (post.get("views") or 0) > m["views"] and "views_with_ads" not in post:
                post["views_with_ads"] = post["views"]
            post["views"] = m["views"]
        if "follows" in m:
            if post.get("boosted") and (post.get("follows") or 0) > m["follows"] and "follows_with_ads" not in post:
                post["follows_with_ads"] = post["follows"]
            post["follows"] = m["follows"]
        elif post.get("boosted") and post.get("follows") and "views_with_ads" in post and "follows_with_ads" not in post:
            # Reels get no follows figure from Instagram, and on posts whose old
            # numbers included the ads, the organic figure is unknown until the
            # boost's follows can be taken off it (step 6)
            post["follows_with_ads"] = post["follows"]
            post["follows"] = None
        post["api_refreshed"] = datetime.now().isoformat()+"Z"
        updated += 1
        print(f"  {i+1}/{len(posts)}: {label} ✓")
    else:
        print(f"  {i+1}/{len(posts)}: {label} (no reach data)")
    time.sleep(0.2)

print(f"\n  Updated {updated}/{len(posts)} posts with fresh metrics")
if not updated:
    print("  Post numbers didn't update (nothing came back)")
    WARNINGS.append("Post numbers didn't update")

# ── 6. BOOST RESULTS (the paid side, from Meta Ads) ──
print("\n[6/6] Boost results from Meta Ads...")
ADS_TOKEN_FILE = Path("meta_ads.token")
CURRENCY = {"GBP": "£", "EUR": "€", "USD": "$"}
to_check = [p for p in posts if p.get("boosted") and p.get("boost_ads")]
ads_token = None
if ADS_TOKEN_FILE.exists():
    ads_token = ADS_TOKEN_FILE.read_text(encoding="utf-8-sig", errors="ignore").strip().strip("\"'").strip()


def ad_results(ad_id, token):
    res = get(f"{BASE}/{ad_id}/insights",
              {"fields": "impressions,reach,spend,actions,account_currency", "date_preset": "maximum"},
              quiet=True, token=token)
    if res is None:
        return None
    out = {"views": 0, "reach": 0, "likes": 0, "saves": 0, "follows": None, "spend": 0.0, "currency": ""}
    for row in res.get("data", []):
        out["views"] += int(float(row.get("impressions") or 0))   # paid impressions = paid views
        out["reach"] += int(float(row.get("reach") or 0))
        out["spend"] += float(row.get("spend") or 0)
        out["currency"] = row.get("account_currency") or out["currency"]
        for a in row.get("actions") or []:
            kind, val = a.get("action_type", ""), int(float(a.get("value") or 0))
            if kind == "post_reaction":
                out["likes"] += val
            elif kind == "onsite_conversion.post_save":
                out["saves"] += val
            elif "follow" in kind:
                out["follows"] = (out["follows"] or 0) + val
    return out


boost_changed = False
if not to_check:
    print("  No boosted posts to look up")
else:
    # Use the Meta Ads token if there is one; otherwise see if the Instagram token can read ads
    token = ads_token
    if not token and ad_results(to_check[0]["boost_ads"][0], TOKEN) is not None:
        token = TOKEN
    if not token:
        print("  Skipped: add the Meta Ads token as meta_ads.token to load boost results")
        WARNINGS.append("Boost results not loaded (no meta_ads.token file)")
    else:
        done, missing = 0, 0
        for post in to_check:
            parts = [ad_results(ad_id, token) for ad_id in post["boost_ads"]]
            time.sleep(0.2)
            if any(r is None for r in parts):
                missing += 1      # keep any earlier boost results rather than half a set
                continue
            follows = [r["follows"] for r in parts if r["follows"] is not None]
            boost = {
                "views":    sum(r["views"] for r in parts),
                "reach":    sum(r["reach"] for r in parts),
                "likes":    sum(r["likes"] for r in parts),
                "saves":    sum(r["saves"] for r in parts),
                "follows":  sum(follows) if follows else None,
                "spend":    round(sum(r["spend"] for r in parts), 2),
                "currency": next((CURRENCY.get(r["currency"], r["currency"] + " ") for r in parts if r["currency"]), "£"),
                "updated":  datetime.now().isoformat()+"Z",
            }
            post["boost"] = boost
            # Organic follows for older boosted reels = the old total minus the boost's follows
            if post.get("follows") is None and post.get("follows_with_ads") is not None and boost["follows"] is not None:
                post["follows"] = max(0, post["follows_with_ads"] - boost["follows"])
            done += 1
            boost_changed = True
        print(f"  Boost results for {done}/{len(to_check)} boosted posts")
        if missing:
            print("  Some couldn't be read: the Meta Ads token may have expired, or not cover that ad account")
            WARNINGS.append(f"Boost results missing for {missing} posts")

if updated or flags_changed or boost_changed:
    save("owned_social.json", posts)

if WARNINGS:
    print("\nHeads up (the rest updated fine, these kept their previous figures):")
    for w in WARNINGS:
        print("  - " + w)

print(f"\n✓ Done! Files saved to data/")
