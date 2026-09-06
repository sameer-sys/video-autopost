#!/usr/bin/env python3
"""
YT Morning Public Flip Bot (PM1 → posting trick)
Finds all PRIVATE videos uploaded in the last 18 hours from this channel,
flips them to PUBLIC at 09:00 IST.
Trick: post at night (private) → morning (public) = higher initial push from YT.

ENV: YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN, TELEGRAM_TOKEN, CHAT_ID
"""
import json, os, datetime, urllib.request, urllib.parse

STATE_FILE = 'yt_flip_state.json'
TOKEN = os.environ.get('TELEGRAM_TOKEN', '')
CHAT_ID = os.environ.get('CHAT_ID', '')


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


def yt_get(path, access):
    url = 'https://www.googleapis.com/youtube/v3/' + path
    req = urllib.request.Request(url, headers={'Authorization': f'Bearer {access}'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def yt_put(access, vid_id, privacy):
    meta = json.dumps({
        'id': vid_id,
        'status': {'privacyStatus': privacy}
    }).encode()
    req = urllib.request.Request(
        'https://www.googleapis.com/upload/youtube/v3/videos?part=status',
        data=meta, method='PUT',
        headers={'Authorization': f'Bearer {access}', 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def tg_send(msg):
    if not (TOKEN and CHAT_ID):
        return
    url = f'https://api.telegram.org/bot{TOKEN}/sendMessage?' + urllib.parse.urlencode(
        {'chat_id': CHAT_ID, 'text': msg})
    with urllib.request.urlopen(url, timeout=30) as r:
        json.load(r)


def main():
    print('=== YT Flip: private -> public ===')
    access = yt_token()
    cutoff = (datetime.datetime.now(datetime.timezone.utc)
              - datetime.timedelta(hours=18)).strftime('%Y-%m-%dT%H:%M:%SZ')
    # Get channel uploads playlist
    ch = yt_get('channels?part=contentDetails&mine=true', access)
    up_id = ch['items'][0]['contentDetails']['relatedPlaylists']['uploads']
    ids, page = [], None
    while True:
        path = f'playlistItems?part=contentDetails&playlistId={up_id}&maxResults=50'
        if page:
            path += '&pageToken=' + page
        j = yt_get(path, access)
        ids += [it['contentDetails']['videoId'] for it in j.get('items', [])]
        page = j.get('nextPageToken')
        if not page:
            break
    # Filter to last 18h, private only
    chunks = [','.join(ids[i:i+50]) for i in range(0, len(ids), 50)]
    to_flip = []
    for chunk in chunks:
        j = yt_get(f'videos?part=snippet,status&id={chunk}', access)
        for it in j.get('items', []):
            pub = it['snippet']['publishedAt']
            priv = it.get('status', {}).get('privacyStatus', '')
            if priv == 'private' and pub >= cutoff:
                to_flip.append((it['id'], it['snippet']['title']))
    st = json.load(open(STATE_FILE)) if os.path.exists(STATE_FILE) else {}
    done_today = st.get('flipped_today', [])
    new_flips = [(v, t) for v, t in to_flip if v not in done_today]
    flipped = 0
    for vid, title in new_flips:
        try:
            yt_put(access, vid, 'public')
            flipped += 1
            print(f'FLIPPED: {vid} - {title}')
        except Exception as e:
            print(f'flip failed {vid}: {e}')
    st['flipped_today'] = [v for v, _ in to_flip]
    st['last_run'] = datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ')
    json.dump(st, open(STATE_FILE, 'w'), indent=2)
    if new_flips:
        titles = '\n'.join(f'  - {t[:60]}' for _, t in new_flips)
        tg_send(f'[PM1/YT Flip] 🔓 {flipped} video(s) flipped private->public\n{titles}')
    print(f'Done. {flipped} flipped.')


if __name__ == '__main__':
    main()
