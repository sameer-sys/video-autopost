#!/usr/bin/env python3
"""
ToonPop Adder Bot (PM1 → sub-bot #4)
Prepares title/caption/hashtags BEFORE upload — IG Reels API locks
caption at publish time, so everything is built pre-post.
Reads trend_state.json (today's trend) + builds per-platform package.
Saves adder_state.json for telegram_loop.py to consume at upload.

Platform tricks baked in (from CEO's links + manager research):
  YT: SEO title (hook first, <60 chars), 3-5 tags, #shorts first
  IG: keywords in caption FIRST line, 5-8 hashtags, trending audio note
  FB: share-style text, 3-5 hashtags, same-day cross-post

ENV: none needed for package build. TELEGRAM_TOKEN/CHAT_ID only to notify.
"""
import json, os, random, datetime, urllib.request, urllib.parse

STATE_FILE = 'adder_state.json'
TREND_FILE = 'trend_state.json'
TOKEN = os.environ.get('TELEGRAM_TOKEN', '')
CHAT_ID = os.environ.get('CHAT_ID', '')

TAG_SETS = {
    'yt': ['#shorts', '#cartoon', '#toonpopworld', '#funny', '#catshorts'],
    'ig': ['#reels', '#cartoon', '#toonpopworld', '#funny', '#catshorts',
           '#viral', '#animation', '#hinglish'],
    'fb': ['#reels', '#toonpopworld', '#cartoon', '#funny'],
}

TITLE_TPL = [
    "{trend} 😱 #shorts",
    "POV: {trend} 🐱 #cartoon",
    "{trend} — Wait For End! 🤫",
]


def load_trend():
    try:
        h = json.load(open(TREND_FILE)).get('history', [])
        if h:
            return h[-1]['trend']
    except Exception:
        pass
    return 'Momo Heist'


def build_package(trend=None):
    trend = trend or load_trend()
    title = random.choice(TITLE_TPL).format(trend=trend)[:60]
    hook_line = f"{trend} — watch till end 😱"
    desc = (f"{hook_line}\n\n🎬 ToonPop World daily cartoon!\n"
            f"Follow for daily shorts 🍿")
    # Comma-separated string for YT API; clean hashtags for IG/FB
    yt_tags = ','.join([t.lstrip('#') for t in TAG_SETS['yt']])
    ig_hashtags = ' '.join(TAG_SETS['ig'])
    fb_hashtags = ' '.join(TAG_SETS['fb'])
    return {
        'trend': trend,
        'yt': {'title': title, 'description': desc,
               'tags': yt_tags},
        'ig': {'caption': f"{hook_line}\n{desc}\n{ig_hashtags}"},
        'fb': {'text': f"{hook_line}\n{desc}\n{fb_hashtags}"},
        'hook_text': hook_line,
    }


def main():
    print('=== Adder starting ===')
    pkg = build_package()
    pkg['date'] = datetime.datetime.now().strftime('%Y-%m-%d')
    json.dump(pkg, open(STATE_FILE, 'w'), indent=2)
    print('package saved:', pkg['yt']['title'])
    if TOKEN and CHAT_ID:
        msg = (f"[Adder Bot] ✅ package ready\nYT: {pkg['yt']['title']}\n"
               f"Hook: {pkg['hook_text']}")
        url = f'https://api.telegram.org/bot{TOKEN}/sendMessage?' + urllib.parse.urlencode(
            {'chat_id': CHAT_ID, 'text': msg})
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                json.load(r)
            print('notified')
        except Exception as e:
            print('notify failed:', e)


if __name__ == '__main__':
    main()
