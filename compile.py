#!/usr/bin/env python3
"""Daily + weekly compilation pipeline.

Daily (12:00 IST): downloads today's shorts (last 24h) + top 3 most-viewed
extras from the last 7 days, joins them newest-first into one video,
posts to YouTube + Facebook Page, sends links to Telegram.

Weekly (Sunday 12:00 IST): joins ALL videos from the last 7 days into one
big video, posts to YouTube + Facebook Page, sends links to Telegram.

The user then pastes a title/description to the bot, which updates the
last uploaded video (existing caption-update feature).
"""
import json, os, re, shutil, subprocess, sys, time, datetime
import urllib.request, urllib.parse, urllib.error

import fb_ig

TOKEN = os.environ.get('TELEGRAM_TOKEN', '')
CHAT_ID = os.environ.get('CHAT_ID', '')
YT_CLIENT_ID = os.environ.get('YT_CLIENT_ID', '')
YT_CLIENT_SECRET = os.environ.get('YT_CLIENT_SECRET', '')
YT_REFRESH = os.environ.get('YT_REFRESH_TOKEN', '')
FB_PAGE_TOKEN = os.environ.get('FB_PAGE_TOKEN', '')
FB_PAGE_ID = os.environ.get('FB_PAGE_ID', '')
STATE_FILE = 'state.json'

PLACEHOLDER = ('🎬 ToonPop World Compilation! Best cartoon moments, one video.\n'
               '#toonpopworld #cartoon #animation #compilation #funny #shorts')


def log(msg):
    print(time.strftime('%H:%M:%S'), msg, flush=True)


def api(method, params=None):
    url = f'https://api.telegram.org/bot{TOKEN}/{method}'
    req = urllib.request.Request(url + '?' + urllib.parse.urlencode(params or {}))
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', 'replace')[:200]
        raise RuntimeError(f'telegram {method}: {e.code} {body}')


def safe_send(text):
    if not (TOKEN and CHAT_ID):
        log('telegram not configured, skipping send')
        return
    try:
        api('sendMessage', {'chat_id': CHAT_ID, 'text': text})
        log('telegram message sent')
    except Exception as e:
        log('sendMessage failed: ' + str(e))


def yt_access_token():
    body = urllib.parse.urlencode({
        'client_id': YT_CLIENT_ID, 'client_secret': YT_CLIENT_SECRET,
        'refresh_token': YT_REFRESH, 'grant_type': 'refresh_token'}).encode()
    req = urllib.request.Request('https://oauth2.googleapis.com/token', data=body,
                                 headers={'Content-Type': 'application/x-www-form-urlencoded'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)['access_token']


def yt_get(path, access):
    req = urllib.request.Request('https://www.googleapis.com/youtube/v3/' + path,
                                 headers={'Authorization': 'Bearer ' + access})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def list_channel_videos(access):
    """Return [{id, published_at, views, title}] newest-first, public only."""
    ch = yt_get('channels?part=contentDetails&mine=true', access)
    up = ch['items'][0]['contentDetails']['relatedPlaylists']['uploads']
    ids, page = [], None
    while True:
        path = f'playlistItems?part=contentDetails&playlistId={up}&maxResults=50'
        if page:
            path += '&pageToken=' + page
        j = yt_get(path, access)
        ids += [it['contentDetails']['videoId'] for it in j.get('items', [])]
        page = j.get('nextPageToken')
        if not page:
            break
    vids = []
    for i in range(0, len(ids), 50):
        chunk = ','.join(ids[i:i + 50])
        j = yt_get(f'videos?part=snippet,statistics,status&id={chunk}', access)
        for v in j.get('items', []):
            if v.get('status', {}).get('privacyStatus') != 'public':
                continue  # skip private/unlisted (e.g. failed uploads)
            vids.append({
                'id': v['id'],
                'published_at': v['snippet']['publishedAt'],
                'views': int(v.get('statistics', {}).get('viewCount', 0) or 0),
                'title': v['snippet']['title'],
            })
    vids.sort(key=lambda v: v['published_at'], reverse=True)
    return vids


def download(video_id, dest, cookies_file):
    url = f'https://www.youtube.com/watch?v={video_id}'
    clients = ['android', 'web_embedded', 'tv', 'mweb']
    last_err = None
    for client in clients:
        r = subprocess.run(['yt-dlp', '--cookies', cookies_file,
                            '--extractor-args', f'youtube:player_client={client}',
                            '-f', 'bv*[height<=1080]+ba/b',
                            '--merge-output-format', 'mp4',
                            '-o', dest, url], capture_output=True, text=True, timeout=600)
        if r.returncode == 0:
            return os.path.getsize(dest)
        last_err = (r.stderr or r.stdout)[-300:]
        log(f'client {client} failed for {video_id}: {last_err}')
    raise RuntimeError('yt-dlp all clients: ' + last_err)


def concat(paths, out):
    """Join videos newest-first into one 1080x1920 mp4."""
    n = len(paths)
    fc = []
    for i, p in enumerate(paths):
        fc.append(f'[{i}:v]scale=1080:1920:flags=lanczos,setsar=1,fps=30[v{i}]')
        fc.append(f'[{i}:a]aformat=sample_rates=44100:channel_layouts=stereo[a{i}]')
    fc.append(''.join(f'[v{i}][a{i}]' for i in range(n)) + f'concat=n={n}:v=1:a=1[vout][aout]')
    cmd = ['ffmpeg', '-y']
    for p in paths:
        cmd += ['-i', p]
    cmd += ['-filter_complex', ';'.join(fc),
            '-map', '[vout]', '-map', '[aout]',
            '-c:v', 'libx264', '-preset', 'medium', '-crf', '23',
            '-c:a', 'aac', '-b:a', '192k', out, '-loglevel', 'error']
    subprocess.run(cmd, check=True, timeout=1800)
    return os.path.getsize(out)


def yt_upload(video_path, access, title):
    size = os.path.getsize(video_path)
    meta = json.dumps({
        'snippet': {'title': title[:100], 'description': PLACEHOLDER,
                    'tags': ['toonpopworld', 'cartoon', 'animation', 'compilation', 'funny'],
                    'categoryId': '24'},
        'status': {'privacyStatus': 'public', 'selfDeclaredMadeForKids': False}}).encode()
    req = urllib.request.Request(
        'https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status',
        data=meta, method='POST',
        headers={'Authorization': 'Bearer ' + access, 'Content-Type': 'application/json',
                 'X-Upload-Content-Length': str(size), 'X-Upload-Content-Type': 'video/mp4'})
    with urllib.request.urlopen(req, timeout=60) as r:
        loc = r.headers['Location']
    data = open(video_path, 'rb').read()
    last_err = None
    for attempt in range(4):
        try:
            req = urllib.request.Request(loc, data=data, method='PUT',
                                         headers={'Content-Type': 'video/mp4'})
            with urllib.request.urlopen(req, timeout=900) as r:
                return json.load(r)['id']
        except Exception as e:
            last_err = e
            log(f'yt upload attempt {attempt + 1} failed: {e}')
            time.sleep(5 * (attempt + 1))
    raise last_err


def load_state():
    try:
        return json.load(open(STATE_FILE))
    except Exception:
        return {'offset': 0, 'done': []}


def save_state(st):
    json.dump(st, open(STATE_FILE, 'w'))


def commit_state():
    gh = os.environ.get('GITHUB_TOKEN', '')
    if not gh:
        return
    subprocess.run(['git', 'config', 'user.name', 'video-autopost-bot'], capture_output=True)
    subprocess.run(['git', 'config', 'user.email', 'video-autopost-bot@users.noreply.github.com'], capture_output=True)
    for attempt in range(3):
        subprocess.run(['git', 'add', STATE_FILE], capture_output=True)
        r = subprocess.run(['git', 'diff', '--cached', '--quiet'], capture_output=True)
        if r.returncode == 0:
            return
        subprocess.run(['git', 'commit', '-m', 'state: ' + time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())], capture_output=True)
        p = subprocess.run(['git', 'pull', '--rebase', 'https://x-access-token:' + gh + '@github.com/sameer-sys/video-autopost.git', 'main'],
                           capture_output=True, text=True)
        if p.returncode != 0:
            log('pull-rebase failed: ' + p.stderr[-200:])
            time.sleep(10)
            continue
        p = subprocess.run(['git', 'push', 'https://x-access-token:' + gh + '@github.com/sameer-sys/video-autopost.git', 'main'],
                           capture_output=True, text=True)
        if p.returncode == 0:
            log('state pushed')
            return
        log('state push failed: ' + p.stderr[-200:])
        time.sleep(10)


def build_and_post(videos, label):
    """Download, join, upload to YT + FB, send links. Returns (yt_id, fb_link)."""
    workdir = f'compile_{int(time.time())}'
    os.makedirs(workdir, exist_ok=True)
    # disposable copy: yt-dlp rewrites the cookies file it reads, so never
    # hand it the source file (auth cookies would be wiped for next run)
    cookies_file = os.path.join(workdir, 'cookies.txt')
    shutil.copyfile('yt_cookies.txt', cookies_file)
    paths = []
    try:
        for i, v in enumerate(videos):
            dest = os.path.join(workdir, f'{i:02d}_{v["id"]}.mp4')
            try:
                download(v['id'], dest, cookies_file)
                paths.append(dest)
                log(f'downloaded {v["id"]} ({v["views"]} views)')
            except Exception as e:
                log(f'download failed {v["id"]}: {e}')
        if len(paths) < 2:
            log('not enough videos downloaded, skipping')
            return None, None
        out = os.path.join(workdir, 'compilation.mp4')
        size = concat(paths, out)
        log(f'compiled {len(paths)} videos -> {size} bytes')
        access = yt_access_token()
        title = f'ToonPop World {label} Compilation ({len(videos)} shorts)'
        yt_id = yt_upload(out, access, title)
        log('UPLOADED yt', yt_id)
        links = ['🎬 ' + title, '▶️ https://youtube.com/watch?v=' + yt_id]
        fb_link = ''
        if FB_PAGE_TOKEN and FB_PAGE_ID:
            try:
                fb_link = fb_ig.fb_video_upload(out, FB_PAGE_TOKEN, FB_PAGE_ID, PLACEHOLDER)
                links.append('📘 ' + fb_link)
                log('UPLOADED fb', fb_link)
            except Exception as e:
                log('fb upload failed: ' + str(e))
                links.append('📘 failed: ' + str(e)[:80])
        safe_send('\n'.join(links))
        return yt_id, fb_link
    finally:
        subprocess.run(['rm', '-rf', workdir], capture_output=True)


def main():
    if not all([YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH]):
        log('MISSING_ENV'); sys.exit(0)
    now = datetime.datetime.now(datetime.timezone.utc)
    is_sunday = now.weekday() == 6
    access = yt_access_token()
    vids = list_channel_videos(access)
    log(f'channel has {len(vids)} videos')
    if not vids:
        log('no videos at all, skipping')
        return

    st = load_state()
    yt_id = fb_link = None
    label = ''

    if is_sunday:
        # weekly: all videos from the last 7 days
        cutoff = now - datetime.timedelta(days=7)
        weekly = [v for v in vids if datetime.datetime.fromisoformat(
            v['published_at'].replace('Z', '+00:00')) >= cutoff]
        if len(weekly) >= 3:
            log(f'WEEKLY: {len(weekly)} videos from last 7 days')
            yt_id, fb_link = build_and_post(weekly, 'Weekly')
            label = 'Weekly'
        else:
            log(f'weekly skipped: only {len(weekly)} videos in 7 days')

    # daily: last 24h + top 3 popular extras from last 7 days
    cutoff24 = now - datetime.timedelta(hours=24)
    cutoff7 = now - datetime.timedelta(days=7)
    todays = [v for v in vids if datetime.datetime.fromisoformat(
        v['published_at'].replace('Z', '+00:00')) >= cutoff24]
    recent7 = [v for v in vids if datetime.datetime.fromisoformat(
        v['published_at'].replace('Z', '+00:00')) >= cutoff7]
    todays_ids = {v['id'] for v in todays}
    extras = [v for v in recent7 if v['id'] not in todays_ids]
    extras.sort(key=lambda v: v['views'], reverse=True)
    extras = extras[:3]
    daily = todays + extras
    daily.sort(key=lambda v: v['published_at'], reverse=True)
    if todays:
        log(f'DAILY: {len(todays)} today + {len(extras)} popular extras = {len(daily)}')
        yt_id, fb_link = build_and_post(daily, 'Daily')
        label = 'Daily'
    else:
        log('daily skipped: no videos in last 24h')

    if yt_id:
        st['last_video_id'] = yt_id
        if fb_link:
            st['last_fb_video_id'] = re.sub(r'[^0-9]', '', fb_link.rstrip('/').split('/')[-1]) or None
        st['last_compile'] = now.isoformat()
        save_state(st)
        commit_state()
        log(f'{label} compile done: yt={yt_id} fb={fb_link}')


if __name__ == '__main__':
    main()