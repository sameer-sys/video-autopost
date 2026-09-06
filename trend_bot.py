#!/usr/bin/env python3
"""
ToonPop Trend Picker Bot (PM1 → sub-bot #1) — v2 OUTSIDE-IN.
CEO rule: NEVER pick trends from our own small channel.
Hunt OUTSIDE every morning:
  1. YouTube niche search: "funny cartoon cat short" sorted by viewCount (7d)
  2. YouTube mostPopular chart (Film/Animation) — what's blowing up
  3. Our last 10 titles used ONLY to avoid repeats, never as source.
Picks 1 winner + 2 backups → Telegram → trend_state.json for script bot.

ENV: TELEGRAM_TOKEN, CHAT_ID, YT_CLIENT_ID, YT_CLIENT_SECRET,
     YT_REFRESH_TOKEN, YOUR_YT_CHANNEL_ID
"""
import json, os, random, re, datetime, urllib.request, urllib.parse
from collections import Counter

STATE_FILE = 'trend_state.json'
TOKEN = os.environ.get('TELEGRAM_TOKEN', '')
CHAT_ID = os.environ.get('CHAT_ID', '')
YT_CHANNEL_ID = os.environ.get('YOUR_YT_CHANNEL_ID', 'UCx_eggTH3zOcuLDr2iYayoA')

NICHE_QUERIES = [
    "funny cartoon cat short",
    "cartoon shorts viral",
    "funny animation short",
]

HOOK_ANGLES = {
    'momo': ("Momo Heist", "POV: cat eyes the momos, owner turns back 😱"),
    'maggi': ("Maggi Steal", "She cooked Maggi... he stole it 🍜"),
    'noodle': ("Noodle Grab", "Noodles gone in 3 seconds 🍜"),
    'pizza': ("Pizza Heist", "Cheesiest pizza theft ever 🍕"),
    'ice cream': ("Ice Cream Chase", "Ice cream came alive and ran 🍦"),
    'portal': ("Portal Kitchen", "My fridge opened a portal ✨"),
    'detective': ("Detective Parrot", "A detective parrot solved it 🕵️"),
    'police': ("Chor-Police Chase", "Officer cat on duty 👮🐱"),
    'race': ("Mud Race", "Race ended in mud 🚲"),
    'challenge': ("Food Challenge", "Challenge accepted, chaos next 🥠"),
    'future': ("Future Cat 2050", "A cat from 2050 visited me 🚀"),
    'magic': ("Magic Food Alive", "This food came alive?! 😱"),
    'party': ("Party Demand", "She demands a party 🎉"),
    'sleep': ("Sleepy Lesson", "Mid-lesson nap 😹"),
    'song': ("Singing Food", "It started singing?! 🎤"),
    'prank': ("Prank Gone Wrong", "Prank backfired 😂"),
    'baby': ("Baby Cat Chaos", "Tiny cat, big chaos 🍼"),
    'dog': ("Cat vs Dog", "Cat vs dog round 100 🐱🐶"),
}


def tg_send(text):
    if not (TOKEN and CHAT_ID):
        print('no telegram creds'); return False
    url = f'https://api.telegram.org/bot{TOKEN}/sendMessage?' + urllib.parse.urlencode(
        {'chat_id': CHAT_ID, 'text': text})
    with urllib.request.urlopen(url, timeout=30) as r:
        json.load(r)
    return True


def yt_token():
    body = urllib.parse.urlencode({
        'client_id': os.environ['YT_CLIENT_ID'],
        'client_secret': os.environ['YT_CLIENT_SECRET'],
        'refresh_token': os.environ['YT_REFRESH_TOKEN'],
        'grant_type': 'refresh_token'}).encode()
    req = urllib.request.Request('https://oauth2.googleapis.com/token', data=body,
        headers={'Content-Type': 'application/x-www-form-urlencoded'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)['access_token']


def yt_search(access, query, days=7, n=15):
    after = (datetime.datetime.now(datetime.timezone.utc)
             - datetime.timedelta(days=days)).strftime('%Y-%m-%dT%H:%M:%SZ')
    url = 'https://www.googleapis.com/youtube/v3/search?' + urllib.parse.urlencode({
        'q': query, 'part': 'snippet', 'order': 'viewCount',
        'publishedAfter': after, 'maxResults': n, 'type': 'video',
        'videoDuration': 'short'})
    req = urllib.request.Request(url, headers={'Authorization': f'Bearer {access}'})
    with urllib.request.urlopen(req, timeout=30) as r:
        j = json.load(r)
    return [(it['snippet']['title'], it['id'].get('videoId', ''))
            for it in j.get('items', [])]


def yt_popular(access, n=15):
    url = 'https://www.googleapis.com/youtube/v3/videos?' + urllib.parse.urlencode({
        'part': 'snippet,statistics', 'chart': 'mostPopular',
        'videoCategoryId': '1', 'maxResults': n, 'regionCode': 'IN'})
    req = urllib.request.Request(url, headers={'Authorization': f'Bearer {access}'})
    with urllib.request.urlopen(req, timeout=30) as r:
        j = json.load(r)
    out = []
    for it in j.get('items', []):
        out.append((it['snippet']['title'],
                    int(it.get('statistics', {}).get('viewCount', 0) or 0)))
    return out


def own_titles(access):
    try:
        url = 'https://www.googleapis.com/youtube/v3/search?' + urllib.parse.urlencode({
            'channelId': YT_CHANNEL_ID, 'part': 'snippet', 'order': 'date',
            'maxResults': 10, 'type': 'video'})
        req = urllib.request.Request(url, headers={'Authorization': f'Bearer {access}'})
        with urllib.request.urlopen(req, timeout=30) as r:
            j = json.load(r)
        return [it['snippet']['title'] for it in j.get('items', [])]
    except Exception:
        return []


def keyword_hits(titles):
    words = re.findall(r'[a-z ]+', ' '.join(titles).lower())
    bag = ' '.join(words)
    hits = {}
    for kw in HOOK_ANGLES:
        c = bag.count(kw)
        if c:
            hits[kw] = c
    return hits


def load_state():
    try:
        return json.load(open(STATE_FILE))
    except Exception:
        return {'history': []}


def main():
    print('=== Trend Picker v2 (outside-in) ===')
    access = yt_token()
    niche_titles, sources = [], []
    for q in NICHE_QUERIES:
        try:
            found = yt_search(access, q)
            niche_titles += [t for t, _ in found]
            sources.append(f"{q}: {len(found)}")
        except Exception as e:
            print('niche search failed:', q, e)
    try:
        pop = yt_popular(access)
        pop_titles = [t for t, _ in pop]
        top_pop = sorted(pop, key=lambda x: -x[1])[:3]
    except Exception as e:
        print('popular chart failed:', e)
        pop_titles, top_pop = [], []
    mine = own_titles(access)
    print('niche:', len(niche_titles), '| popular:', len(pop_titles), '| mine:', len(mine))

    hits = keyword_hits(niche_titles + pop_titles)
    st = load_state()
    used = {h['trend'] for h in st.get('history', [])[-6:]}
    ranked = sorted(hits.items(), key=lambda x: -x[1])
    winner_kw = next((k for k, _ in ranked if HOOK_ANGLES[k][0] not in used), None)
    if not winner_kw:
        fresh = [k for k in HOOK_ANGLES if HOOK_ANGLES[k][0] not in used]
        winner_kw = random.choice(fresh or list(HOOK_ANGLES))
    name, hook = HOOK_ANGLES[winner_kw]
    rest = [k for k in HOOK_ANGLES if k != winner_kw and HOOK_ANGLES[k][0] not in used]
    backups = random.sample(rest, min(2, len(rest)))
    today = datetime.datetime.now().strftime('%Y-%m-%d')
    st.setdefault('history', []).append({'date': today, 'trend': name,
                                         'keyword': winner_kw})
    st['history'] = st['history'][-30:]
    json.dump(st, open(STATE_FILE, 'w'), indent=2)
    ev = [t for t in (niche_titles + pop_titles) if winner_kw in t.lower()][:2]
    msg = (f"[Trend Bot] 🔥 {today} (OUTSIDE hunt)\nWinner: {name}\nHook: {hook}\n"
           f"Evidence: {hits.get(winner_kw, 1)}x niche hits"
           + (f" e.g. '{ev[0][:60]}'" if ev else "") + "\n"
           f"Backup 1: {HOOK_ANGLES[backups[0]][0] if backups else '-'}\n"
           f"Backup 2: {HOOK_ANGLES[backups[1]][0] if len(backups) > 1 else '-'}\n"
           f"Sources: {'; '.join(sources) or 'fallback rotation'}")
    print(tg_send(msg), name)


if __name__ == '__main__':
    main()
