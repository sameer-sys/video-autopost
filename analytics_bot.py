#!/usr/bin/env python3
"""
Channel analytics + competitive intelligence bot.
Runs on GitHub Actions schedule — checks your 3 channels + benchmark channels.
Emails you: subscriber/view growth + competitor tactics to copy.
Saves findings to analytics_state.json (committed back to repo for resume).

ENV NEEDED:
  YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN  (YouTube OAuth)
  FB_PAGE_TOKEN, FB_PAGE_ID                          (Facebook Page)
  IG_TOKEN                                           (Instagram token)
  GMAIL_USER, GMAIL_PASS                            (for email alerts)

USAGE:
  python analytics_bot.py
  (designed to run as one-shot, triggered by cron)
"""
import json, os, re, sys, smtplib, time, urllib.request, urllib.parse, datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

STATE_FILE = 'analytics_state.json'
EMAIL_TO = os.environ.get('EMAIL_TO', 'samesuf786@gmail.com')
EMAIL_FROM = os.environ.get('GMAIL_USER', '')
EMAIL_PASS = os.environ.get('GMAIL_APP_PASSWORD', '')

# ---------------------------------------------------------------------------
# Your channels
# ---------------------------------------------------------------------------
YOUR_YT_CHANNEL_ID = os.environ.get('YOUR_YT_CHANNEL_ID', 'UCx_eggTH3zOcuLDr2iYayoA')
YOUR_IG_USER_ID = os.environ.get('YOUR_IG_USER_ID', '')
YOUR_FB_PAGE_ID = os.environ.get('YOUR_FB_PAGE_ID', '')  # auto-detected if empty

# ---------------------------------------------------------------------------
# Resolve FB Page ID if not given (auto-detection)
# ---------------------------------------------------------------------------
def _resolve_fb_page_id(token_env='FB_PAGE_TOKEN', page_id_env='YOUR_FB_PAGE_ID'):
    """Auto-detect Facebook Page ID from the page token."""
    pid = os.environ.get(page_id_env)
    if pid:
        return pid
    token = os.environ.get(token_env)
    if not token:
        return ''
    try:
        url = f'{GRAPH}/me/accounts?access_token={token}&limit=25'
        j = _get(url, {})
        pages = j.get('data', [])
        # look for ToonPop World
        for p in pages:
            if 'toonpop' in p.get('name', '').lower():
                return p['id']
        # fallback: first page
        if pages:
            return pages[0]['id']
    except Exception as e:
        print('FB page ID auto-detect failed:', e)
    return ''

_your_fb_page_id = _resolve_fb_page_id()

# Benchmark channels — same niche, similar or slightly larger
BENCHMARKS = {
    "carTOONS":      ["UCkAizvmvTgXi0a4aAJ1aF9g"],   # example: popular animation shorts channel
    "dailyToonsHD":  ["UCBJycsmduJ9kymqfajFa1IY"],
    "toonvault":     ["UCq-Fj0bl4Q4WAWnm5NeHcMg"],
    "cartoonClips":  ["UCkAizvmvTgXi0a4aAJ1aFj9"],   # placeholder — fill with real similar-channel IDs
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def yt_refresh_token():
    """Exchange refresh token for access token (no user interaction needed)."""
    body = urllib.parse.urlencode({
        'client_id':    os.environ['YT_CLIENT_ID'],
        'client_secret': os.environ['YT_CLIENT_SECRET'],
        'refresh_token': os.environ['YT_REFRESH_TOKEN'],
        'grant_type':   'refresh_token',
    }).encode()
    req = urllib.request.Request(
        'https://oauth2.googleapis.com/token',
        data=body,
        headers={'Content-Type': 'application/x-www-form-urlencoded'},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)['access_token']


def yt_api(path, access, params=None):
    """Call YouTube Data API v3."""
    url = f'https://www.googleapis.com/youtube/v3/{path}'
    if params:
        url += '?' + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        'Authorization': f'Bearer {access}',
        'User-Agent':    'Mozilla/5.0',
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', 'replace')[:300]
        raise RuntimeError(f'YT API {e.code}: {body}')


def yt_channel_stats(access, channel_id):
    """Get subscriber count + total views for a channel."""
    j = yt_api('channels', access, {
        'part': 'statistics',
        'id':   channel_id,
    })
    if not j.get('items'):
        return None
    s = j['items'][0]['statistics']
    return {
        'subscribers': int(s.get('subscriberCount', 0) or 0),
        'total_views': int(s.get('viewCount', 0) or 0),
        'hidden_subs': s.get('hiddenSubscriberCount', True),
    }


def yt_channel_videos(access, channel_id, days=7):
    """Return recent videos (last `days` days) with view counts."""
    j = yt_api('channels', access, {
        'part': 'contentDetails',
        'id':   channel_id,
    })
    if not j.get('items'):
        return []
    uploads_pl = j['items'][0]['contentDetails']['relatedPlaylists']['uploads']
    now = datetime.datetime.now(datetime.timezone.utc)
    cutoff = now - datetime.timedelta(days=days)
    vids = []
    page = None
    while True:
        p = {'part': 'contentDetails', 'playlistId': uploads_pl, 'maxResults': 50}
        if page:
            p['pageToken'] = page
        pj = yt_api('playlistItems', access, p)
        for it in pj.get('items', []):
            vid = it['contentDetails']['videoId']
            vd = yt_api('videos', access, {
                'part': 'snippet,statistics',
                'id':   vid,
            })
            if vd.get('items'):
                v = vd['items'][0]
                stats = v.get('statistics', {})
                pub = v['snippet']['publishedAt']
                pub_dt = datetime.datetime.fromisoformat(
                    pub.replace('Z', '+00:00'))
                views = int(stats.get('viewCount', 0) or 0)
                vids.append({
                    'id':    vid,
                    'title': v['snippet']['title'],
                    'views': views,
                    'pub':   pub_dt.isoformat(),
                    'delta_hours': (now - pub_dt).total_seconds() / 3600,
                })
        page = pj.get('nextPageToken')
        if not page:
            break
    # only last `days`
    return [v for v in vids if
            (now - datetime.datetime.fromisoformat(v['pub'])).days <= days]


def fb_page_insights(page_token, page_id):
    """Get page followers + recent video posts with views."""
    url = f'https://graph.facebook.com/v18.0/{page_id}'
    params = {
        'fields': 'followers_count,videos.limit(10){id,title,length,video_insights.metric(total_video_impressions_unique)',
        'access_token': page_token,
    }
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    resp = urllib.request.urlopen(req, timeout=30)
    j = json.load(resp)
    insights = {'followers': j.get('followers_count', 0)}
    videos = []
    for v in j.get('videos', {}).get('data', []):
        vid = v.get('id', '').split('_')[-1] if '_' in v.get('id', '') else v.get('id', '')
        ins = v.get('video_insights', {}).get('data', [])
        views = 0
        for i in ins:
            if i.get('name') == 'total_video_impressions_unique':
                vals = i.get('values', [])
                if vals:
                    views = vals[0].get('value', 0)
        videos.append({
            'id':    vid,
            'title': v.get('title', '')[:100],
            'views': views,
        })
    insights['videos'] = videos
    return insights


def ig_basic(ig_user_id, ig_token):
    """Get IG follower count (basic display)."""
    url = f'https://graph.instagram.com/{ig_user_id}'
    params = {'fields': 'followers_count,media_count', 'access_token': ig_token}
    req = urllib.request.Request(url + '?' + urllib.parse.urlencode(params))
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def send_email(subject, body_html):
    """Send HTML email via Gmail SMTP."""
    if not (EMAIL_FROM and EMAIL_PASS):
        print('No email configured; printing to stdout instead.')
        print(f'SUBJECT: {subject}')
        print(body_html)
        return
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = EMAIL_FROM
    msg['To'] = EMAIL_TO
    msg.attach(MIMEText(body_html, 'html'))
    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(EMAIL_FROM, EMAIL_PASS)
            server.send_message(msg)
        print('Email sent to', EMAIL_TO)
    except Exception as e:
        print('Email send failed:', e)
        print(body_html)


# ---------------------------------------------------------------------------
# Core: gather stats + benchmark + build email
# ---------------------------------------------------------------------------
def load_state():
    try:
        return json.load(open(STATE_FILE))
    except Exception:
        return {'checks': []}


def save_state(st):
    json.dump(st, open(STATE_FILE, 'w'), indent=2)


def fmt_k(n):
    """Format number as K/M."""
    if n >= 1_000_000:
        return f'{n / 1_000_000:.1f}M'
    if n >= 1_000:
        return f'{n / 1_000:.0f}K'
    return str(n)


def analyze():
    """Main analysis routine."""
    if not os.environ.get('YT_CLIENT_ID'):
        print('Missing YT_CLIENT_ID — cannot run YouTube analytics.')
        sys.exit(0)

    access = yt_refresh_token()
    st = load_state()
    check_ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
    findings = {'ts': check_ts, 'your_channels': {}, 'benchmarks': {}}

    # --- YOUR channels ---
    # YouTube
    if YOUR_YT_CHANNEL_ID:
        stats = yt_channel_stats(access, YOUR_YT_CHANNEL_ID)
        if stats:
            vids = yt_channel_videos(access, YOUR_YT_CHANNEL_ID, days=7)
            avg_views = (sum(v['views'] for v in vids) / len(vids)) if vids else 0
            findings['your_channels']['youtube'] = {
                'subscribers': stats['subscribers'],
                'total_views': stats['total_views'],
                'videos':     len(vids),
                'avg_views_7d': int(avg_views),
            }

    # Facebook
    if YOUR_FB_PAGE_ID and FB_PAGE_TOKEN:
        try:
            findings['your_channels']['facebook'] = fb_page_insights(
                FB_PAGE_TOKEN, YOUR_FB_PAGE_ID)
        except Exception as e:
            findings['your_channels']['facebook'] = {'error': str(e)}

    # Instagram
    if YOUR_IG_USER_ID and IG_TOKEN:
        try:
            findings['your_channels']['instagram'] = ig_basic(
                YOUR_IG_USER_ID, IG_TOKEN)
        except Exception as e:
            findings['your_channels']['instagram'] = {'error': str(e)}

    # --- Benchmark channels ---
    # Compare your recent video views against the top video of each benchmark
    benchmark_insights = []
    for bench_name, channel_ids in BENCHMARKS.items():
        if not channel_ids:
            continue
        cid = channel_ids[0]
        stats = yt_channel_stats(access, cid)
        if not stats:
            continue
        vids = yt_channel_videos(access, cid, days=14)
        if not vids:
            continue
        top = max(vids, key=lambda v: v['views'])
        your_yt = findings['your_channels'].get('youtube', {})
        your_avg = your_yt.get('avg_views_7d', 1)
        view_ratio = top['views'] / max(your_avg, 1)

        if view_ratio >= 3:
            insight = (
                f"🚨 <b>{bench_name}</b> posted \"{top['title']}\" "
                f"({fmt_k(top['views'])} views in {top['delta_hours']:.0f}h) "
                f"— {view_ratio:.1f}x your avg. Their hook is working. "
                f"<i>Check their thumbnail/title and replicate the pattern.</i>"
            )
            benchmark_insights.append(insight)

        findings['benchmarks'][bench_name] = {
            'subscribers': stats['subscribers'],
            'top_video_views': top['views'],
            'top_title': top['title'][:100],
            'age_hours': f"{top['delta_hours']:.1f}",
            'vs_your_avg': f"{view_ratio:.1f}x",
        }

    # --- Compare to last check ---
    last_check = st.get('checks', [])
    prev = last_check[-1] if last_check else {}
    growth_lines = []

    yt_prev = prev.get('your_channels', {}).get('youtube', {})
    yt_curr = findings['your_channels'].get('youtube', {})
    if yt_prev and yt_curr:
        sub_delta = yt_curr.get('subscribers', 0) - yt_prev.get('subscribers', 0)
        growth_lines.append(
            f"<b>YouTube:</b> {fmt_k(yt_curr.get('subscribers', 0))} subs "
            f"({'+' if sub_delta >= 0 else ''}{sub_delta} since last check)")

    # --- Build email ---
    html = f"""
    <html><body style="font-family: Arial, sans-serif; max-width: 700px;">
    <h2>ToonPop World — Channel Analytics Report</h2>
    <p><small>Checked at: {check_ts}</small></p>

    <h3>Your Channels</h3>
    <ul>
    """
    for plat, data in findings['your_channels'].items():
        if 'error' in data:
            html += f"<li><b>{plat.title()}:</b> ⚠️ {data['error'][:100]}</li>"
        elif plat == 'youtube':
            html += (f"<li><b>YouTube:</b> {fmt_k(data['subscribers'])} subs · "
                     f"{fmt_k(data['total_views'])} total views · "
                     f"{data['videos']} videos (7d) · "
                     f"avg {fmt_k(data['avg_views_7d'])} views/video)</li>")
        elif plat == 'facebook':
            html += f"<li><b>Facebook:</b> {fmt_k(data.get('followers', 0))} followers · "
            html += f"{len(data.get('videos', []))} recent videos</li>"
        elif plat == 'instagram':
            html += f"<li><b>Instagram:</b> {fmt_k(data.get('followers_count', 0))} followers · "
            html += f"{data.get('media_count', 0)} posts</li>"
    html += "</ul>"

    html += "<h3>Growth Since Last Check</h3><ul>"
    for line in growth_lines:
        html += f"<li>{line}</li>"
    if not growth_lines:
        html += "<li><i>No baseline for comparison yet. Check again in a few hours for growth data.</i></li>"
    html += "</ul>"

    html += "<h3>Competitor Tactics to Copy</h3>"
    if benchmark_insights:
        html += "<ul>" + "".join(f"<li>{i}</li>" for i in benchmark_insights) + "</ul>"
    else:
        html += ("<p><i>No benchmark videos significantly outperforming yours "
                 "this cycle. You're holding steady or they haven't posted "
                 "anything viral yet.</i></p>\n")

    html += "<h3>Action Checklist</h3><ul>"
    # Auto-suggest based on findings
    if yt_curr:
        if yt_curr.get('avg_views_7d', 0) < yt_curr.get('subscribers', 0) * 0.3:
            html += "<li>📉 <b>View/subscriber ratio low</b> — thumbnails or hooks may be missing the mark. "
            html += "Review top 3 performing benchmark titles this week.</li>"
        if yt_curr.get('subscribers', 0) >= 900 and yt_curr.get('total_views', 0) >= 3500:
            html += "<li>✅ <b>You're close to monetization!</b> "
            yt_subs = yt_curr.get('subscribers', 0)
            yt_views = yt_curr.get('total_views', 0)
            html += f"Need {max(0, 1000 - yt_subs)} more subs and "
            html += f"{max(0, 4000 - yt_views)} more watch hours.</li>"
    html += "</ul>"

    html += f"""
    <hr><p><small>
    Channel Insights Bot · <a href="https://github.com/sameer-sys/video-autopost">video-autopost</a> repo<br>
    Next check: in 6 hours. Reply to this email with action items you want applied.
    </small></p>
    </body></html>
    """

    subject = f"ToonPop Analytics — {fmt_k(findings['your_channels'].get('youtube', {}).get('subscribers', 0))} YT subs · {datetime.datetime.now():-%H:%M}"
    send_email(subject, html)

    # Save state
    st.setdefault('checks', []).append(findings)
    st['checks'] = st['checks'][-50:]  # keep last 50 checks (~12 days)
    save_state(st)
    print('Analysis complete — findings saved to', STATE_FILE)


if __name__ == '__main__':
    analyze()
