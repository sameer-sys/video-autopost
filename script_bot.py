#!/usr/bin/env python3
"""
ToonPop World Script Bot
Generates 3 viral cartoon-cat short scripts/day + splits into 3 Google Flow prompts.
Sends all 3 scripts directly via Telegram to the user (no email).
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
    "Wait for the ending 😱",
    "You won't believe what happens next",
    "This trick changed everything 🤫",
    "POV: your cat is the CEO of chaos",
    "She's done this 100 times, always works",
    "Stop scrolling, watch till end",
    "Day {n} of cat vs {food}",
]
TITLES = [
    "{c1} Ne {food} Chura Liya 😱",
    "Meri Plate Se {food} Kyu Chura Rahi? 😾",
    "{c1} vs {food} — Who Wins?",
    "Magic {food} Truck Serves Chaos 🪄",
    "{c1} Fell Asleep Mid-Lesson 😹",
    "She Cooked {food}... He Stole It 🍜",
    "Portal Opens To {w} World ✨",
    "Detective {c2} Solves {food} Mystery 🕵️",
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
    style = "9:16 vertical short, vibrant 2D cartoon animation, Studio Ghibli-lite style, orange tabby cat lead, exaggerated expressions, fast motion, bright kitchen lighting, no watermark, smooth cel-shaded look. Google Flow text-to-video, same character reference across all 3 clips for consistency"
    # Actually build prompts from scratch:
    food = random.choice(FOODS).lower()
    w = random.choice(WORLDS)
    c1 = "the orange cat"
    c2 = "the detective parrot"
    prompts = [
        f"Flow clip 1: {c1} sneaks toward {food} in {w}, sneaky eyes, stretches paw, dramatic zoom, {style}.",
        f"Flow clip 2: {c1} grabs {food}, owner spots, epic chase around the counter, slapstick comedy, keep same cat design as clip 1, {style}.",
        f"Flow clip 3: {c1} triumphs with {food}, victory bite, portal to another world opens, fade out with logo, same cat design, {style}.",
    ]
    narration = (
        f"[0-3s HOOK] {hook}\n"
        f"[3-15s SETUP] {c1.capitalize()} tiptoes into {w} — the {food} is calling. Paw out. Eyes wide. Owner is asleep.\n"
        f"[15-25s CHAOS] Grab. Owner wakes. CHASE. Slapstick. Cat vs human around the counter.\n"
        f"[25-30s PAYOFF] Cat wins. First bite. Portal opens. End on loop frame."
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


# ---- Main ----
def main():
    print('=== Script Bot starting ===')
    recent_titles = fetch_recent_titles()
    print(f'Fetched {len(recent_titles)} recent titles from your channel')
    scripts = make_three_scripts(recent_titles)

    st = load_state()
    st.setdefault('sent', []).append({
        'date': datetime.datetime.now().strftime('%Y-%m-%d'),
        'sent': [],  # we track via Telegram logs
        'titles': [s['title'] for s in scripts],
    })
    st['sent'] = st['sent'][-30:]
    save_state(st)

    today = datetime.datetime.now().strftime('%Y-%m-%d')
    for i, s in enumerate(scripts, 1):
        msg = render_script_for_telegram(s, i)
        ok = send_telegram(msg)
        print(f'Sent script {i}/3: title={s["title"]} ok={ok}')
        # small pause so Telegram doesn't rate-limit
        time.sleep(2)

    print('Done.')


if __name__ == '__main__':
    main()