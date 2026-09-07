#!/usr/bin/env python3
"""
Script Bot — ON-DEMAND (triggered by Trend Bot immediately after topic pick).
Generates 3 Flow prompts + Hindi hook/thumbnail/narration for today's trend.
Called by Trend Bot immediately after picking topic (instant cycle).
Saves to script_state.json, sends 3 prompts to Telegram.
"""
import json, os, random, urllib.request, urllib.parse, datetime

STATE_FILE = 'script_state.json'
TREND_FILE = 'trend_state.json'
TOKEN = os.environ.get('TELEGRAM_TOKEN', '')
CHAT_ID = os.environ.get('CHAT_ID', '')

CAST = {
    'momo': "same orange tabby cartoon cat",
    'maggi': "same orange tabby cartoon cat",
    'portal': "same orange tabby cartoon cat",
    'detective': "same cartoon detective parrot",
    'chor': "same cartoon officer cat chasing a naughty dog",
    'police': "same cartoon officer cat chasing a naughty dog",
    'future': "same orange tabby cartoon cat from year 2050",
    'party': "same naughty baby sister cartoon cat",
    'sleep': "same genius baby cartoon cat",
    'race': "same orange tabby cartoon cat on a tiny bike",
    'song': "same cute white persian cartoon cat",
    'pizza': "same orange tabby cartoon cat",
    'magic': "same orange tabby cartoon cat",
    'challenge': "same orange tabby cartoon cat",
}

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

FOODS = [
    "steaming hot momos", "Maggi noodles", "paneer tikka",
    "pani puri golas", "chocolate bar", "cheesy pizza",
    "gulab jamun", "ice cream cone", "samosa plate",
    "crispy jalebi", "hot dosa", "spicy biryani",
]

WORLDS = [
    "kitchen counter at night",
    "momos shop in Mumbai",
    "school canteen",
    "bathroom during bath time",
    "Magic Potion food truck",
    "Helicopter Tiffin delivery sky",
    "Candy Land portal",
    "Momo World portal",
    "future 2050 lab",
]

def tg_send(text):
    if not (TOKEN and CHAT_ID):
        print('no telegram creds'); return False
    url = f'https://api.telegram.org/bot{TOKEN}/sendMessage?' + urllib.parse.urlencode(
        {'chat_id': CHAT_ID, 'text': text})
    with urllib.request.urlopen(url, timeout=30) as r:
        json.load(r)
    return True

def load_trend():
    try:
        h = json.load(open('trend_state.json')).get('history', [])
        if h:
            return h[-1]
    except Exception:
        pass
    return {'trend': 'Momo Heist', 'keyword': 'momo', 'hook': 'मोमोज़ मेरे हैं!'}

def fill_template(t):
    c1 = random.choice(["orange tabby cartoon cat", "same orange tabby cat", "her tiny brother cat",
                        "a detective parrot", "a naughty baby sister cat"])
    c2 = random.choice([c for c in ["orange tabby cartoon cat", "detective parrot", "tiny brother cat",
                                    "naughty baby sister cat"] if c != c1])
    return t.format(c1=c1, c2=c2,
                    food=random.choice(FOODS).lower(),
                    w=random.choice(WORLDS),
                    w2=random.choice(WORLDS),
                    n=random.randint(2, 99))

def make_script():
    trend = load_trend()
    trend_name = trend.get('trend', 'Momo Heist')
    trend_kw = trend.get('keyword', 'momo')
    hook = trend.get('hook', 'एंड तक देखो 😱')
    
    cat = CAST.get(trend_kw, "same orange tabby cartoon cat")
    food = random.choice(FOODS).lower()
    w = random.choice(WORLDS)
    
    prompts = [
        f"{cat} tiptoeing toward a plate of {food} on a {w}, sneaky look, paw reaching out, cat whispers in Hindi '{hook}', 9:16 vertical cartoon, bright colors",
        f"{cat} grabbing the {food} and running while owner chases shouting in Hindi 'रुक! वापस कर!', slapstick kitchen chase, 9:16 vertical cartoon, fast funny motion",
        f"{cat} happily eating the {food}, victory smile, cat says in Hindi 'मज़ा आ गया!', sparkling background, 9:16 vertical cartoon, warm light",
    ]
    
    narration = (
        f"[0-3s हुक] {hook}\n"
        f"[3-15s सेटअप] {cat} {w} में दबे पाँव — {food} बुला रहा है। पंजा बाहर। आँखें बड़ी। मालिक सो रहा है।\n"
        f"[15-25s धमाल] पकड़ा। मालिक जागा। पीछा। धमाल। बिल्ली vs इंसान।\n"
        f"[25-30s एंड] बिल्ली जीती। पहला निवाला। लूप फ्रेम पर एंड।"
    )
    
    hashtags = "#shorts #cartoon #toonpopworld #funny #catshorts #viral #hinglish #animation"
    
    title = random.choice(TITLES).format(
        c1="orange tabby cat", c2="detective parrot", food=food, w=random.choice(WORLDS))[:60]
    
    return {
        'title': title,
        'hook': hook,
        'food': food,
        'world': w,
        'prompts': prompts,
        'narration': narration,
        'hashtags': hashtags,
    }

def render_script_for_telegram(script):
    lines = [
        f"🎬 Script Ready — {script['title']}",
        f"Hook (first 1.5s text): {script['hook']}",
        "",
        "📹 3 Flow Prompts (paste each into Google Flow):",
    ]
    for i, p in enumerate(script['prompts'], 1):
        lines.append(f"  {i}. {p}")
    lines += [
        "",
        "📝 Narration / Scene Beats:",
        script['narration'],
        "",
        f"Hashtags: {script['hashtags']}",
        "",
        "—",
        f"Generated {datetime.datetime.now():%Y-%m-%d %H:%M UTC}",
    ]
    return '\n'.join(lines)

def tg_send(text):
    if not (TOKEN and CHAT_ID):
        print('no telegram creds'); return False
    url = f'https://api.telegram.org/bot{TOKEN}/sendMessage?' + urllib.parse.urlencode(
        {'chat_id': CHAT_ID, 'text': text})
    with urllib.request.urlopen(url, timeout=30) as r:
        json.load(r)
    return True

def load_state():
    try:
        return json.load(open('script_state.json'))
    except Exception:
        return {'sent': []}

def save_state(st):
    json.dump(st, open('script_state.json', 'w'), indent=2)

def main():
    print('=== Script Bot (on-demand) starting ===')
    trend = load_trend()
    print(f"Trend received: {trend.get('trend')}")
    
    # Generate 3 scripts for 3 videos
    scripts = [make_script() for _ in range(3)]
    
    st = load_state()
    today = datetime.datetime.now().strftime('%Y-%m-%d')
    st.setdefault('sent', []).append({
        'date': today,
        'titles': [s['title'] for s in scripts],
    })
    st['sent'] = st['sent'][-30:]
    save_state(st)
    
    for i, s in enumerate(scripts, 1):
        msg = render_script_for_telegram(s)
        ok = tg_send(msg)
        print(f'Sent script {i}/3: {s["title"]} ok={ok}')
        import time
        time.sleep(1)
    
    print('Done — 3 scripts sent to Telegram.')

if __name__ == '__main__':
    import datetime
    main()