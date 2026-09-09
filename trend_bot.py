#!/usr/bin/env python3
"""
Trend Bot — ON-DEMAND (triggered by Posting Bot after each video upload).
Finds next best topic immediately, saves to trend_state.json.
Called by Posting Bot after each successful upload (instant cycle).
No cron — triggered by Posting Bot's success path.
"""
import json, os, random, datetime, urllib.request, urllib.parse

STATE_FILE = 'trend_state.json'
TOKEN = os.environ.get('TELEGRAM_TOKEN', '')
CHAT_ID = os.environ.get('CHAT_ID', '')
YT_CHANNEL_ID = os.environ.get('YOUR_YT_CHANNEL_ID', 'UCx_eggTH3zOcuLDr2iYayoA')

TRENDS = [
    ("Momo Heist", "cat steals momos, owner chase", "मोमोज़ मेरे हैं!"),
    ("Maggi Steal", "cat grabs Maggi noodles mid-cook", "रुक! वापस कर!"),
    ("Portal Kitchen", "fridge portal to Momo/Candy world", "फ्रिज में पोर्टल खुला!"),
    ("Chor-Police Chase", "officer cat catches dog stealing", "चोर पुलिस दौड़!"),
    ("Pani Puri Challenge", "eating challenge dramatic finish", "पानी पूरी चैलेंज!"),
    ("Pizza Heist", "cat steals cheesy pizza", "चीज़ी पिज़्ज़ा चोरी!"),
    ("Future Cat 2050", "cat from 2050 visits and leaves", "2050 से बिल्ली!"),
    ("Magic Food Alive", "food comes alive, chaos chase", "खाना जिंदा हो गया!"),
    ("Singing Object", "toothpaste sings Bollywood song", "टूथपेस्ट गा रहा!"),
    ("Party Demand", "cat demands party every praise", "पार्टी चाहिए!"),
    ("Sleepy Lesson", "genius cat falls asleep mid-lesson", "पढ़ाई में सो गया!"),
    ("Bike/Mud Race", "race ends in mud splash", "कीचड़ में रेस!"),
    ("Singing Food", "food starts singing", "खाना गाने लगा!"),
    ("Detective Parrot", "parrot solves missing-food mystery", "तोता जासूस!"),
    ("Baby Cat Chaos", "tiny cat causes big chaos", "नन्ही बिल्ली!"),
]

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
        'client_id': os.environ.get('YT_CLIENT_ID', ''),
        'client_secret': os.environ.get('YT_CLIENT_SECRET', ''),
        'refresh_token': os.environ.get('YT_REFRESH_TOKEN', ''),
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
    blob = ' '.join(titles).lower()
    hits = {}
    for name, _, _ in TRENDS:
        key = name.split()[0].lower()
        if key in blob:
            hits[name] = blob.count(key)
    return hits

def load_state():
    try:
        return json.load(open('trend_state.json'))
    except Exception:
        return {'history': []}

def save_state(st):
    json.dump(st, open('trend_state.json', 'w'), indent=2)

def main():
    print('=== Trend Bot (on-demand) starting ===')
    access = yt_token()
    
    # Outside-in: niche search + popular chart
    niche_titles = []
    for q in ["funny cartoon cat short", "cartoon shorts viral", "funny animation short"]:
        try:
            niche_titles += [t for t, _ in yt_search(access, q, 7, 15)]
        except Exception:
            pass
    pop = yt_popular(access, 15)
    pop_titles = [t for t, _ in pop]
    mine = own_titles(access)

    hits = keyword_hits(niche_titles + pop_titles)
    st = load_state()
    used = {h['trend'] for h in st.get('history', [])[-6:]}
    
    ranked = sorted(hits.items(), key=lambda x: -x[1])
    winner_name = next((n for n, _ in ranked if n not in used), None)
    if not winner_name:
        fresh = [n for n, _, _ in TRENDS if n not in used]
        winner_name = random.choice(fresh or [t[0] for t in TRENDS])
    
    winner = next(t for t in TRENDS if t[0] == winner_name)
    rest = [t for t in TRENDS if t[0] != winner_name]
    backups = random.sample(rest, min(2, len(rest)))
    
    today = datetime.datetime.now().strftime('%Y-%m-%d')
    st.setdefault('history', []).append({'date': today, 'trend': winner[0], 'keyword': winner[0].split()[0].lower()})
    st['history'] = st['history'][-30:]
    save_state(st)
    
    ev = [t for t in (niche_titles + pop_titles) if winner_name.split()[0].lower() in t.lower()][:2]
    msg = (f"[Trend Bot] 🔥 Next Topic (on-demand)\n"
           f"Winner: {winner[0]}\n"
           f"Angle: {winner[1]}\n"
           f"Hook: {winner[2]}\n"
           f"Evidence: {hits.get(winner[0], 1)}x niche hits"
           + (f" e.g. '{ev[0][:60]}'" if ev else "") + "\n"
           f"Backup 1: {backups[0][0] if backups else '-'}\n"
           f"Backup 2: {backups[1][0] if len(backups) > 1 else '-'}")
    print(tg_send(msg), winner[0])

if __name__ == '__main__':
    main()