#!/usr/bin/env python3
"""Poll YouTube Analytics API for channel stats. Runs locally via Hermes cron."""
import json, os, requests, time, sys
from datetime import datetime
from hermes_tools import write_file

# Load channel config
CHANNELS = {
    "YouTube_main": "UCxxxxxxxxxxxxx",  # Replace with your channel ID
    "Instagram": "toonpopworld",        # @handle
    "Facebook": "toonpopworld.page"       # page ID
}

def get_yt_stats(channel_id: str, api_key: str) -> dict | None:
    """Fetch raw subscriber + view counts from YouTube Data API v3."""
    try:
        resp = requests.get(
            "https://www.googleapis.com/youtube/v3/channels",
            params={
                "part": "statistics,status",
                "id": channel_id,
                "key": api_key,
                "_": str(int(time.time()))  # cache-buster
            },
            timeout=30
        )
        if resp.status_code != 200:
            return {"error": f"HTTP {resp.status_code}", "detail": resp.text[:200]}
        data = resp.json()
        if not data.get("items"):
            return {"error": "No channel found or private"}
        stats = data["items"][0]["statistics"]
        status = data["items"][0]["status"]

        return {
            "subscribers": int(stats.get("subscriberCount", 0)),
            "total_views": int(stats.get("viewCount", 0)),
            "video_count": int(stats.get("videoCount", 0)),
            "hidden_subs": stats.get("hiddenSubscriberCount", False),
            "monetized": status.get("madeForKids", False) is False,  # monetization eligibility hint
            "updated_at": datetime.now().isoformat()
        }
    except Exception as e:
        return {"error": str(e)}

def check_monetization_readiness(stats: dict) -> list[str]:
    """Check if channel meets YouTube Partner Program requirements."""
    alerts = []

    # YPP requirements: 1000 subs + 4000 watch hours (last 12 mo)
    if stats.get("subscribers", 0) >= 1000:
        alerts.append("✅ Sub count ready (1000+ required)")
    else:
        needed = 1000 - stats.get("subscribers", 0)
        alerts.append(f"⏳ Need {needed} more subs for YPP")

    # Watch hours proxy: estimate from avg views × video count × 0.3
    # (rough estimate — real audit needs YouTube Analytics API)
    est_hours = stats.get("total_views", 0) * stats.get("video_count", 0) * 0.3 / 3600
    if est_hours >= 4000:
        alerts.append("✅ Estimated watch hours ready (4000+ required)")
    else:
        needed = 4000 - est_hours
        alerts.append(f"⏳ Need ~{needed:.0f} more watch hours")

    return alerts

def check_content_health(stats: dict) -> list[str]:
    """Basic content quality signals."""
    alerts = []

    if stats.get("video_count", 0) < 12:
        alerts.append(f"⚠️ Upload cadence low ({stats['video_count']} videos) — aim for 1-2/month")
    elif stats.get("video_count", 0) >= 24:
        alerts.append("✅ Upload cadence healthy")

    if not stats.get("monetized", False):
        alerts.append("⚠️ Channel marked as 'made for kids' — blocks monetization")

    if stats.get("hidden_subs"):
        alerts.append("⚠️ Subscribers hidden — you won't see growth trends")

    return alerts

if __name__ == "__main__":
    # Your API key from Google Cloud Console (YouTube Data API v3)
    API_KEY = os.environ.get("YOUTUBE_API_KEY", "MISSING_KEY")

    if API_KEY == "MISSING_KEY":
        print("ERROR: Set YOUTUBE_API_KEY env var (Google Cloud Console → APIs & Services → Credentials)")
        sys.exit(1)

    results = {}
    for platform, identifier in CHANNELS.items():
        if platform == "YouTube_main":
            stats = get_yt_stats(identifier, API_KEY)
            results[platform] = stats

            if "error" in stats:
                print(f"❌ {platform}: {stats['error']}")
                continue

            # Check readiness
            ypp_alerts = check_monetization_readiness(stats)
            health_alerts = check_content_health(stats)

            # Write to Hermes memory for trend tracking
            write_file(
                path="/c/Users/Master/AppData/Local/hermes/stats_snapshots/" +
                     f"{platform}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                content=json.dumps(stats, indent=2)
            )

            print(f"\n📊 {platform}")
            print(f"  Subscribers: {stats['subscribers']:,}")
            print(f"  Total views: {stats['total_views']:,}")
            print(f"  Videos: {stats['video_count']}")
            for alert in ypp_alerts:
                print(f"  {alert}")
            for alert in health_alerts:
                print(f"  {alert}")

    print("\n✅ Stats snapshot saved to Hermes memory.")
