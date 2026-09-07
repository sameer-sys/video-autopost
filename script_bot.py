#!/usr/bin/env python3
"""
ToonPop World Script Bot — BATCH MODE (PM1).
One batch = 3 Google Flow prompts = 1 video (30s).
Loop: send batch N → CEO makes video → sends to @Toonpop_upload_bot
→ posting bot uploads → auto-sends batch N+1. Up to 5/day, more on demand.
Batch 1 fires on schedule (09:30 IST). Batches 2+ fire after each upload
(telegram_loop.py calls next_batch() post-upload).
Runs on GitHub Actions schedule.

Niche: funny cartoon-cat shorts (Hinglish), food + mischief + fantasy.
Each script: 30s total, 3 Google Flow clips (~8-10s each), hook in first 1.5s.

ENV (in GitHub Actions secrets, set in bot-workflow.yml):
  TELEGRAM_TOKEN, CHAT_ID       (your bot chats with @Toonpop_upload_bot)
  YOUR_YT_CHANNEL_ID            (for trend-source sampling)

This bot sends the 3 scripts as Telegram messages directly. The user can
copy/paste the Flow prompts, generate clips in Google Flow, stitch in CapCut, then send the
30s MP4 to @Toonpop_upload_bot — the posting bot handles the rest.
"""
import json, os, re, time, urllib.request, urllib.parse, datetime, random
from html import escape

STATE_FILE = 'script_state.json'

CHAT_ID = os.environ.get('CHAT_ID', '')
TOKEN = os.environ.get('TELEGRAM_TOKEN', '')
YT_CHANNEL_ID = os.environ.get('YOUR_YT_CHANNEL_ID', 'UCx_eggTH3zOcuLDr2iYayoA')


def api_telegram(method, params=None, files=None):
    """Thin Telegram Bot API wrapper (no Composio dependency)."""
    url = f'https://api.telegram.org/bot{TOKEN}/{method}'
    if files:
        import subprocess
        args = ['curl', '-s']
        for k, v in (params or {}).items():
            args += ['-F', f'{k}={v}']
        for k, path in files.items():
            args += ['-F', f'{k}=@{path}']
        args.append(url)
        r = subprocess.run(args, capture_output=True, text=True)
        return json.loads(r.stdout)
    else:
        import urllib.request
        q = url + '?' + urllib.parse.urlencode(params or {})
        try:
            with urllib.request.urlopen(q, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            body = e.read().decode('utf-8', 'replace')[:200]
            raise RuntimeError(f'Telegram API error {e.code}: {body}')


def yt_refresh():
    body = urllib.parse.urlencode({
        'client_id': os.environ['YT_CLIENT_ID'],
        'client_secret': os.environ['YT_CLIENT_SECRET'],
        'refresh_token': os.environ['YT_REFRESH_TOKEN'],
        'grant_type': 'refresh_token',
    }).encode()
    req = urllib.request.Request(
        'https://oauth2.googleapis.com/token',
        data=body,
        headers={'Content-Type': 'application/x-www-form-urlencoded'},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)['access_token']


def yt_get(path, access, params=None):
    url = f'https://www.googleapis.com/youtube/v3/{path}'
    if params:
        url += '?' + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={'Authorization': f'Bearer {access}'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def fetch_recent_titles():
    try:
        access = yt_refresh()
        j = yt_get('search', access, {
            'channelId': YT_CHANNEL_ID,
            'part': 'snippet',
            'order': 'date',
            'maxResults': 10,
            'type': 'video',
        })
        titles = [it['snippet']['title'] for it in j.get('items', [])]
        return titles
    except Exception as e:
        print('YT fetch failed:', e)
        return []


# ---- Niche seed data (your actual channel territory) ----
CHARACTERS = [
    "an orange cartoon cat (ToonPop mascot)",
    "the same orange cat",
    "her tiny brother cat",
    "a detective parrot",
    "a naughty baby sister cat",
]
WORLDS = [
    "kitchen counter at night",
    "fridge that opens into a portal",
    "momos shop in Mumbai",
    "school canteen",
    "bathroom during bath time",
    "Magic Potion food truck",
    "Helicopter Tiffin delivery sky",
    "Candy Land portal",
    "Momo World portal",
    "future 2050 lab",
]
FOODS = [
    "steaming hot momos", "Maggi noodles", "paneer tikka",
    "pani puri golas", "chocolate bar", "cheesy pizza",
    "gulab jamun", "ice cream cone", "samosa plate",
]
TROPE_TEMPLATES = [
    "thief/steal: {c1} steals {food} from {w}, owner catches, funny chase",
    "portal: {c1} opens a portal from {w} to {w2}, brings back {food}",
    "challenge: {c1} enters a {food} eating challenge, dramatic finish",
    "trick: {c1} tries a {food} hack, it backfires hilariously",
    "competition: {c1} vs {c2}, who finishes {food} first, twist ending",
    "detective: {c2} investigates missing {food}, {c1} is suspect",
    "future: {c1} from 2050 visits, shows the future of {food}, then leaves",
    "magic: a magic {food} object comes alive, chaos, {c1} chases it",
    "party: {c1} demands a party every time, escalates, owner gives in",
    "lesson: {c1} tries to teach a lesson, falls asleep mid-lesson",
    "race: {c1} enters a {food} race, obstacle, mud-splash ending",
    "song: {food} starts singing a Bollywood song, {c1} is shocked",
]
HOOKS = [
    # Hindi hooks (CEO: video language = Hindi)
    "एंड तक देखो 😱",
    "यकीन नहीं होगा आगे क्या हुआ",
    "ये ट्रिक सब बदल देगी 🤫",
    "POV: तुम्हारी बिल्ली ही बॉस है",
    "ये 100 बार कर चुकी, हर बार काम करता",
    "रुको, एंड तक देखो",
    "बिल्ली vs {food} डे {n}",
]
TITLES = [
    "{c1} Ne {food} Chura Liya 😱",
    "मेरी प्लेट से {food} क्यों चुराया? 😾",
    "{c1} vs {food} — कौन जीतेगा?",
    "जादुई {food} ठेला 🪄",
    "{c1} सो गया पढ़ाई में 😹",
    "उसने {food} बनाया... इसने चुरा लिया 🍜",
    "{w} की दुनिया का पोर्टल ✨",
    "जासूस {c2} ने {food} का राज़ खोला 🕵️",
]


# ---- One 30s script: 3 Google Flow prompts, hook, narration ----
def pick_trope(recent_titles):
    if recent_titles:
        text = ' '.join(recent_titles).lower()
        keyword_map = {
            'portal': 'portal: {c1} opens a portal from {w} to {w2}, brings back {food}',
            'momo': 'thief/steal: {c1} steals {food} from {w}, owner catches, funny chase',
            'maggi': 'thief/steal: {c1} steals {food} from {w}, owner catches, funny chase',
            'detective': 'detective: {c2} investigates missing {food}, {c1} is suspect',
            'race': 'race: {c1} enters a {food} race, obstacle, mud-splash ending',
            'sleep': 'lesson: {c1} tries to teach a lesson, falls asleep mid-lesson',
            'party': 'party: {c1} demands a party every time, escalates, owner gives in',
            'future': 'future: {c1} from 2050 visits, shows the future of {food}, then leaves',
            'magic': 'magic: a magic {food} object comes alive, chaos, {c1} chases it',
        }
        for kw, trope in keyword_map.items():
            if kw in text:
                return trope
    return random.choice(TROPE_TEMPLATES)


def fill_template(t):
    c1 = random.choice(CHARACTERS)
    c2 = random.choice([c for c in CHARACTERS if c != c1])
    return t.format(
        c1=c1, c2=c2,
        food=random.choice(FOODS).lower(),
        w=random.choice(WORLDS),
        w2=random.choice(WORLDS),
        n=random.randint(2, 99),
    )


def make_script():
    trope = fill_template(random.choice(TROPE_TEMPLATES))
    title_template = random.choice(TITLES)
    title = fill_template(title_template)
    hook = random.choice(HOOKS).format(n=random.randint(2, 99))
    # FLOW-SAFE rules (Google Flow / Veo limits, PM-enforced):
    # - ONE action per clip, <40 words, no dialogue, no on-screen text requests
    # - same character anchor every clip ("same orange tabby cat")
    # - 9:16 vertical, simple setting, no multi-scene jumps inside one clip
    cat = "same orange tabby cartoon cat"
    food = random.choice(FOODS).lower()
    w = random.choice(WORLDS)
    c1 = "the orange cat"
    prompts = [
        f"{cat} tiptoeing toward a plate of {food} on a {w}, sneaky look, paw reaching out, 9:16 vertical cartoon, bright colors",
        f"{cat} grabbing the {food} and running while owner chases, slapstick kitchen chase, 9:16 vertical cartoon, fast funny motion",
        f"{cat} happily eating the {food}, victory smile, sparkling background, 9:16 vertical cartoon, warm light",
    ]
    narration = (
        f"[0-3s हुक] {hook}\n"
        f"[3-15s सेटअप] {c1.capitalize()} {w} में दबे पाँव — {food} बुला रहा है। पंजा बाहर। आँखें बड़ी। मालिक सो रहा है।\n"
        f"[15-25s धमाल] पकड़ा। मालिक जागा। पीछा। धमाल। बिल्ली vs इंसान।\n"
        f"[25-30s एंड] बिल्ली जीती। पहला निवाला। लूप फ्रेम पर एंड।"
    )
    hashtags = "#shorts #cartoon #toonpopworld #funny #catshorts #viral #hinglish #animation"
    return {
        'title': title,
        'hook': hook,
        'food': food,
        'world': w,
        'prompts': prompts,
        'narration': narration,
        'hashtags': hashtags,
    }


def make_three_scripts(recent_titles):
    return [make_script() for _ in range(3)]


# ---- Telegram send helpers ----
def send_telegram(text, parse_mode='Markdown'):
    if not CHAT_ID or not TOKEN:
        print('No Telegram creds, skipping')
        return False
    try:
        api_telegram('sendMessage', {'chat_id': CHAT_ID, 'text': text, 'parse_mode': parse_mode})
        return True
    except Exception as e:
        print(f'Telegram send failed: {e}')
        return False


def send_html(html_text):
    """Send as HTML (HTML parse mode — good for formatted script text)."""
    return send_telegram(html_text, parse_mode='HTML')


# ---- State ----
def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {'sent': []}


def save_state(st):
    with open(STATE_FILE, 'w') as f:
        json.dump(st, f, indent=2)


def render_script_for_telegram(script, idx):
    """Render one script as a readable Telegram message."""
    title = script['title']
    hook = script['hook']
    food = script['food']
    world = script['world']
    trope = script.get('trope', '')
    narration = script['narration']
    hashtags = script['hashtags']
    prompts = script['prompts']

    lines = [
        f"💡 Idea {idx} — {title}",
        f"Trope: {trope}",
        f"Hook (overlay text first 1.5s): {hook}",
        "",
        "📹 Three Google Flow prompts (paste into Flow text-to-video):",
    ]
    for i, p in enumerate(prompts, 1):
        lines.append(f"  {i}. {p}")
    lines += [
        "",
        "📝 Narration / scene beats:",
        narration,
        "",
        f"Hashtags: {hashtags}",
        "",
        "—",
        f"Generated {datetime.datetime.now():%Y-%m-%d %H:%M UTC}",
    ]
    return '\n'.join(lines)


# ---- Batch mode: one batch = 1 video ----
def today_key():
    return datetime.datetime.now().strftime('%Y-%m-%d')


def next_batch(send=True):
    """Build batch N for today, send via Telegram, track in state.
    Returns (batch_no, message). Importable by telegram_loop.py."""
    st = load_state()
    today = today_key()
    if st.get('date') != today:
        st = {'date': today, 'batches': []}
    n = len(st.get('batches', [])) + 1
    s = make_script()
    msg = ("[Script Bot] 🎬 Batch %d — 1 video (3 Flow prompts):\n\n" % n
           + render_script_for_telegram(s, n))
    ok = send_telegram(msg) if send else True
    st.setdefault('batches', []).append({'n': n, 'title': s['title'], 'sent': ok})
    save_state({**st, 'date': today})
    print(f'Batch {n}: {s["title"]} ok={ok}')
    return n, msg


# ---- Main ----
def pm_pick(scripts):
    """PM1 picks 1 winner daily — CEO only makes the winner video."""
    try:
        trend = json.load(open('trend_state.json')).get('history', [])[-1].get('trend', '')
    except Exception:
        trend = ''
    if trend:
        for i, s in enumerate(scripts):
            blob = (s['title'] + ' ' + s.get('trope', '')).lower()
            if trend.split()[0].lower() in blob:
                return i
    return 0


def main():
    print('=== Script Bot starting (batch 1 of day) ===')
    n, _ = next_batch(send=True)
    print(f'Done. Batch {n} sent. Batches 2+ fire after each upload.')


if __name__ == '__main__':
    main()