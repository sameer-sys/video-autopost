#!/usr/bin/env python3
"""
ToonPop Trend Picker Bot (PM1 → sub-bot #1)
Runs every morning. Picks 1 trend + 2 backups from:
  1. Your last 10 video titles (what tropes already work)
  2. Template rotation (no blind repeats — tracks trend_state.json)
Sends ONE Telegram message. Script bot reads trend_state.json next.

ENV: TELEGRAM_TOKEN, CHAT_ID, YT_CLIENT_ID, YT_CLIENT_SECRET,
     YT_REFRESH_TOKEN, YOUR_YT_CHANNEL_ID
"""
import json, os, random, datetime, urllib.request, urllib.parse

STATE_FILE = 'trend_state.json'
TOKEN = os.environ.get('TELEGRAM_TOKEN', '')
CHAT_ID = os.environ.get('CHAT_ID', '')
YT_CHANNEL_ID = os.environ.get('YOUR_YT_CHANNEL_ID', 'UCx_eggTH3zOcuLDr2iYayoA')

TRENDS = [
    ("Momo Heist", "cat steals momos, owner chase", "POV: cat eyes the momos, owner turns back 😱"),
    ("Maggi Steal", "cat grabs Maggi noodles mid-cook", "She cooked Maggi... he stole it 🍜"),
    ("Portal Kitchen", "fridge portal to Momo/Candy world", "My fridge opened a portal ✨"),
    ("Chor-Police Chase", "officer cat catches dog stealing", "Officer cat on duty 👮🐱"),
    ("Detective Parrot", "parrot solves missing-food mystery", "A detective parrot solved it 🕵️"),
    ("Pani Puri Challenge", "eating challenge dramatic finish", "She won the challenge 🥠"),
    ("Future Cat 2050", "cat from 2050 visits and leaves", "A cat from 2050 visited me 🚀"),
    ("Magic Food Alive", "food comes alive, chaos chase", "This food came alive?! 😱"),
    ("Party Demand", "cat demands party every praise", "She demands a party 🎉"),
    ("Sleepy Lesson", "genius cat falls asleep mid-lesson", "Mid-lesson nap 😹"),
    ("Bike/Mud Race", "race ends in mud splash", "Race ended in mud 🚲"),
    ("Singing Object", "object sings Bollywood song, cat shocked", "It started singing?! 🎤"),
]


def tg_send(text):
    if not (TOKEN and CHAT_ID):
        print('no telegram creds'); return False
    url = f'https://api.telegram.org/bot{TOKEN}/sendMessage?' + urllib.parse.urlencode(
        {'chat_id': CHAT_ID, 'text': text})
    with urllib.request.urlopen(url, timeout=30) as r:
        json.load(r)
    return True


def fetch_titles():
    try:
        body = urllib.parse.urlencode({
            'client_id': os.environ['YT_CLIENT_ID'],
            'client_secret': os.environ['YT_CLIENT_SECRET'],
            'refresh_token': os.environ['YT_REFRESH_TOKEN'],
            'grant_type': 'refresh_token'}).encode()
        req = urllib.request.Request('https://oauth2.googleapis.com/token', data=body,
            headers={'Content-Type': 'application/x-www-form-urlencoded'})
        with urllib.request.urlopen(req, timeout=30) as r:
            access = json.load(r)['access_token']
        url = ('https://www.googleapis.com/youtube/v3/search?' + urllib.parse.urlencode({
            'channelId': YT_CHANNEL_ID, 'part': 'snippet', 'order': 'date',
            'maxResults': 10, 'type': 'video'}))
        req = urllib.request.Request(url, headers={'Authorization': f'Bearer {access}'})
        with urllib.request.urlopen(req, timeout=30) as r:
            j = json.load(r)
        return [it['snippet']['title'] for it in j.get('items', [])]
    except Exception as e:
        print('YT fetch failed:', e); return []


def load_state():
    try:
        return json.load(open(STATE_FILE))
    except Exception:
        return {'history': []}


def main():
    print('=== Trend Picker starting ===')
    titles = fetch_titles()
    st = load_state()
    used = {h['trend'] for h in st.get('history', [])[-6:]}
    pool = [t for t in TRENDS if t[0] not in used] or TRENDS
    # boost: if recent titles mention a keyword, prefer matching trend
    blob = ' '.join(titles).lower()
    boost = None
    for name, angle, hook in pool:
        key = name.split()[0].lower()
        if key in blob:
            boost = (name, angle, hook); break
    winner = boost or random.choice(pool)
    rest = [t for t in pool if t != winner]
    backups = random.sample(rest, min(2, len(rest)))
    today = datetime.datetime.now().strftime('%Y-%m-%d')
    st.setdefault('history', []).append({'date': today, 'trend': winner[0]})
    st['history'] = st['history'][-30:]
    json.dump(st, open(STATE_FILE, 'w'), indent=2)
    msg = (f"[Trend Bot] 🔥 {today}\nWinner: {winner[0]}\nAngle: {winner[1]}\n"
           f"Hook: {winner[2]}\nBackup 1: {backups[0][0] if backups else '-'}\n"
           f"Backup 2: {backups[1][0] if len(backups) > 1 else '-'}")
    ok = tg_send(msg)
    print('sent:', ok, winner[0])


if __name__ == '__main__':
    main()
