#!/usr/bin/env python3
"""
Posting Bot — MINIMAL WORKING VERSION
Receives video → downloads → upscales → uploads to YT (private) → replies "✅ Done"
"""
import json, os, re, sys, subprocess, time, urllib.request, urllib.parse

import fb_ig

TOKEN = os.environ.get('TELEGRAM_TOKEN', '')
CHAT_ID = os.environ.get('CHAT_ID', '')
YT_CLIENT_ID = os.environ.get('YT_CLIENT_ID', '')
YT_CLIENT_SECRET = os.environ.get('YT_CLIENT_SECRET', '')
YT_REFRESH = os.environ.get('YT_REFRESH_TOKEN', '')
FB_PAGE_TOKEN = os.environ.get('FB_PAGE_TOKEN', '')
FB_PAGE_ID = os.environ.get('FB_PAGE_ID', '')
IG_USER_ID = os.environ.get('IG_USER_ID', '')
IG_TOKEN = os.environ.get('IG_TOKEN', '')

TG_API = os.environ.get('TG_API_BASE', 'https://api.telegram.org').rstrip('/')
TG_FILE = os.environ.get('TG_FILE_BASE', TG_API).rstrip('/')

STATE_FILE = 'state.json'
VIDEOS_FILE = 'videos.json'

def log(msg):
    print(time.strftime('%H:%M:%S'), msg, flush=True)

def api(method, params=None):
    url = f'{TG_API}/bot{TOKEN}/{method}'
    req = urllib.request.Request(url + '?' + urllib.parse.urlencode(params or {}))
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', 'replace')[:200]
        raise RuntimeError(f'telegram {method}: {e.code} {body}')

def safe_send(text):
    try:
        api('sendMessage', {'chat_id': CHAT_ID, 'text': text})
    except Exception as e:
        log('sendMessage failed: ' + str(e))

def fetch(url, timeout=180):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()

def load_state():
    try:
        return json.load(open('state.json'))
    except Exception:
        return {'offset': 0, 'done': []}

def save_state(st):
    json.dump(st, open('state.json', 'w'))

def commit_state():
    gh = os.environ.get('GITHUB_TOKEN', '')
    if not gh:
        return
    subprocess.run(['git', 'config', 'user.name', 'video-autopost-bot'], capture_output=True)
    subprocess.run(['git', 'config', 'user.email', 'video-autopost-bot@users.noreply.github.com'], capture_output=True)
    subprocess.run(['git', 'add', 'state.json', 'videos.json'], capture_output=True)
    r = subprocess.run(['git', 'diff', '--cached', '--quiet'], capture_output=True)
    if r.returncode != 0:
        subprocess.run(['git', 'commit', '-m', 'state: ' + time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())], capture_output=True)
        p = subprocess.run(['git', 'push', f'https://x-access-token:{gh}@github.com/sameer-sys/video-autopost.git', 'main'],
                           capture_output=True, text=True)
        if p.returncode == 0:
            log('state pushed')
        else:
            log('state push failed: ' + p.stderr[-200:])

def record_video(uid, file_id, yt_id, fb_id=''):
    try:
        hist = json.load(open('videos.json'))
    except Exception:
        hist = []
    hist.append({'uid': uid, 'file_id': file_id, 'date': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                 'yt_id': yt_id, 'fb_id': fb_id})
    json.dump(hist[-500:], open('videos.json', 'w'))

def download_telegram_file(file_id, dest):
    j = api('getFile', {'file_id': file_id})
    path = j['result']['file_path']
    data = fetch(f'https://api.telegram.org/file/bot{TOKEN}/{path}')
    open(dest, 'wb').write(data)
    return len(data)

def yt_access_token():
    body = urllib.parse.urlencode({
        'client_id': os.environ['YT_CLIENT_ID'],
        'client_secret': os.environ['YT_CLIENT_SECRET'],
        'refresh_token': os.environ['YT_REFRESH_TOKEN'],
        'grant_type': 'refresh_token'}).encode()
    req = urllib.request.Request('https://oauth2.googleapis.com/token', data=body,
                                 headers={'Content-Type': 'application/x-www-form-urlencoded'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)['access_token']

def yt_upload(video_path):
    access = yt_access_token()
    size = os.path.getsize(video_path)
    meta = json.dumps({
        'snippet': {'title': 'ToonPop Short', 'description': 'ToonPop World', 'tags': ['shorts', 'cartoon'], 'categoryId': '24'},
        'status': {'privacyStatus': 'private', 'selfDeclaredMadeForKids': False}}).encode()
    req = urllib.request.Request(
        'https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status',
        data=meta, method='POST',
        headers={'Authorization': 'Bearer ' + yt_access_token(), 'Content-Type': 'application/json',
                 'X-Upload-Content-Length': str(os.path.getsize(video_path)), 'X-Upload-Content-Type': 'video/mp4'})
    with urllib.request.urlopen(req, timeout=60) as r:
        loc = r.headers['Location']
    data = open(video_path, 'rb').read()
    for attempt in range(4):
        try:
            req = urllib.request.Request(loc, data=data, method='PUT',
                                         headers={'Content-Type': 'video/mp4'})
            with urllib.request.urlopen(req, timeout=600) as r:
                return json.load(r)['id']
        except Exception as e:
            time.sleep(5 * (attempt + 1))
    raise RuntimeError('upload failed')

def download_telegram_file(file_id, dest):
    j = api('getFile', {'file_id': file_id})
    path = j['result']['file_path']
    data = fetch(f'https://api.telegram.org/file/bot{TOKEN}/{path}')
    open(dest, 'wb').write(data)
    return len(data)

def upscale(src, dst):
    subprocess.run(['ffmpeg', '-y', '-i', src,
                    '-vf', 'scale=1080:1920:flags=lanczos,setsar=1,fps=30',
                    '-c:v', 'libx264', '-preset', 'medium', '-crf', '23',
                    '-c:a', 'aac', '-b:a', '192k', dst, '-loglevel', 'error'],
                   check=True, timeout=600)

def load_state():
    try:
        return json.load(open('state.json'))
    except Exception:
        return {'offset': 0, 'done': []}

def save_state(st):
    json.dump(st, open('state.json', 'w'))

def commit_state():
    gh = os.environ.get('GITHUB_TOKEN', '')
    if not gh:
        return
    subprocess.run(['git', 'config', 'user.name', 'video-autopost-bot'], capture_output=True)
    subprocess.run(['git', 'config', 'user.email', 'video-autopost-bot@users.noreply.github.com'], capture_output=True)
    subprocess.run(['git', 'add', 'state.json', 'videos.json'], capture_output=True)
    r = subprocess.run(['git', 'diff', '--cached', '--quiet'], capture_output=True)
    if r.returncode != 0:
        subprocess.run(['git', 'commit', '-m', 'state: ' + time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())], capture_output=True)
        p = subprocess.run(['git', 'push', f'https://x-access-token:{gh}@github.com/sameer-sys/video-autopost.git', 'main'],
                           capture_output=True, text=True)

def api(method, params=None):
    url = f'https://api.telegram.org/bot{TOKEN}/{method}'
    req = urllib.request.Request(url + '?' + urllib.parse.urlencode(params or {}))
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', 'replace')[:200]
        raise RuntimeError(f'telegram {method}: {e.code} {body}')

def safe_send(text):
    try:
        api('sendMessage', {'chat_id': CHAT_ID, 'text': text})
    except Exception as e:
        print('sendMessage failed:', e)

def log(msg):
    print(time.strftime('%H:%M:%S'), msg, flush=True)

def process_update(u):
    st = load_state()
    uid = u['update_id']
    m = u.get('message') or u.get('channel_post') or {}
    st['offset'] = uid + 1
    txt = (m.get('text') or '').strip()
    if txt and not txt.startswith('/'):
        log('text message: ' + txt[:50])
        save_state(st)
        return
    vid = m.get('video')
    doc = m.get('document')
    if doc and str(doc.get('mime_type', '')).startswith('video/'):
        vid = doc
    if vid and uid not in st['done']:
        try:
            src = f"in_{uid}.mp4"
            hd = f"hd_{uid}.mp4"
            size = download_telegram_file(vid['file_id'], src)
            log('downloaded ' + str(size))
            dur = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                                  '-of', 'default=noprint_wrappers=1:nokey=1', src],
                               capture_output=True, text=True)
            try:
                seconds = float(dur.stdout.strip())
            except:
                seconds = 0
            if seconds > 45:
                safe_send('Video too long (' + str(int(seconds)) + 's). Max 45 seconds.')
                st['done'].append(uid)
                save_state(st)
                return
            upscale(src, hd)
            log('upscaled ok')
            vid_id = yt_upload(hd)
            st['last_video_id'] = vid_id
            st['done'].append(uid)
            save_state(st)
            record_video(uid, vid['file_id'], vid_id)
            commit_state()
            safe_send('✅ Done')
            log('replied to video', uid)
        except Exception as e:
            log('ERROR:', e)
            st['done'].append(uid)
            save_state(st)
            try:
                safe_send('Processing failed: ' + str(e)[:100])
            except:
                pass
        finally:
            for f in (src, 'hd_' + str(uid) + '.mp4'):
                if os.path.exists(f):
                    os.remove(f)
        save_state(st)

def upscale(src, dst):
    subprocess.run(['ffmpeg', '-y', '-i', src,
                    '-vf', 'scale=1080:1920:flags=lanczos,setsar=1,fps=30',
                    '-c:v', 'libx264', '-preset', 'medium', '-crf', '23',
                    '-c:a', 'aac', '-b:a', '192k', dst, '-loglevel', 'error'],
                   check=True, timeout=600)

def yt_access_token():
    body = urllib.parse.urlencode({
        'client_id': os.environ['YT_CLIENT_ID'],
        'client_secret': os.environ['YT_CLIENT_SECRET'],
        'refresh_token': os.environ['YT_REFRESH_TOKEN'],
        'grant_type': 'refresh_token'}).encode()
    req = urllib.request.Request('https://oauth2.googleapis.com/token', data=body,
                                 headers={'Content-Type': 'application/x-www-form-urlencoded'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)['access_token']

def yt_upload(video_path):
    access = yt_access_token()
    size = os.path.getsize(video_path)
    meta = json.dumps({
        'snippet': {'title': 'ToonPop Short', 'description': 'ToonPop World', 'tags': ['shorts', 'cartoon'], 'categoryId': '24'},
        'status': {'privacyStatus': 'private', 'selfDeclaredMadeForKids': False}}).encode()
    req = urllib.request.Request(
        'https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status',
        data=meta, method='POST',
        headers={'Authorization': 'Bearer ' + yt_access_token(), 'Content-Type': 'application/json',
                 'X-Upload-Content-Length': str(os.path.getsize(video_path)), 'X-Upload-Content-Type': 'video/mp4'})
    with urllib.request.urlopen(req, timeout=60) as r:
        loc = r.headers['Location']
    data = open(video_path, 'rb').read()
    for attempt in range(4):
        try:
            req = urllib.request.Request(loc, data=data, method='PUT',
                                         headers={'Content-Type': 'video/mp4'})
            with urllib.request.urlopen(req, timeout=600) as r:
                return json.load(r)['id']
        except Exception as e:
            time.sleep(5 * (attempt + 1))
    raise RuntimeError('upload failed')

def api(method, params=None):
    url = f'https://api.telegram.org/bot{TOKEN}/{method}'
    req = urllib.request.Request(url + '?' + urllib.parse.urlencode(params or {}))
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', 'replace')[:200]
        raise RuntimeError(f'telegram {method}: {e.code} {body}')

def safe_send(text):
    try:
        api('sendMessage', {'chat_id': CHAT_ID, 'text': text})
    except Exception as e:
        print('sendMessage failed:', e)

def load_state():
    try:
        return json.load(open('state.json'))
    except Exception:
        return {'offset': 0, 'done': []}

def save_state(st):
    json.dump(st, open('state.json', 'w'))

def log(msg):
    print(time.strftime('%H:%M:%S'), msg, flush=True)

def process_update(u):
    st = load_state()
    uid = u['update_id']
    m = u.get('message') or u.get('channel_post') or {}
    st['offset'] = uid + 1
    vid = m.get('video')
    doc = m.get('document')
    if doc and str(doc.get('mime_type', '')).startswith('video/'):
        vid = doc
    if vid and uid not in st['done']:
        try:
            src = f"in_{uid}.mp4"
            hd = f"hd_{uid}.mp4"
            size = download_telegram_file(vid['file_id'], src)
            log('downloaded ' + str(size))
            dur = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                                  '-of', 'default=noprint_wrappers=1:nokey=1', src],
                               capture_output=True, text=True)
            try:
                seconds = float(dur.stdout.strip())
            except:
                seconds = 0
            if seconds > 45:
                api('sendMessage', {'chat_id': CHAT_ID, 'text': 'Video too long. Max 45 seconds.'})
                return
            upscale(src, f"hd_{u['update_id']}.mp4")
            log('upscaled ok')
            vid_id = yt_upload(f"hd_{u['update_id']}.mp4")
            api('sendMessage', {'chat_id': CHAT_ID, 'text': '✅ Done'})
        except Exception as e:
            print('ERROR:', e)
        finally:
            for f in (f"in_{u['update_id']}.mp4", f"hd_{u['update_id']}.mp4"):
                if os.path.exists(f):
                    os.remove(f)

def upscale(src, dst):
    subprocess.run(['ffmpeg', '-y', '-i', src,
                    '-vf', 'scale=1080:1920:flags=lanczos,setsar=1,fps=30',
                    '-c:v', 'libx264', '-preset', 'medium', '-crf', '23',
                    '-c:a', 'aac', '-b:a', '192k', dst, '-loglevel', 'error'],
                   check=True, timeout=600)

def yt_access_token():
    body = urllib.parse.urlencode({
        'client_id': os.environ['YT_CLIENT_ID'],
        'client_secret': os.environ['YT_CLIENT_SECRET'],
        'refresh_token': os.environ['YT_REFRESH_TOKEN'],
        'grant_type': 'refresh_token'}).encode()
    req = urllib.request.Request('https://oauth2.googleapis.com/token', data=body,
                                 headers={'Content-Type': 'application/x-www-form-urlencoded'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)['access_token']

def yt_upload(video_path):
    access = yt_access_token()
    size = os.path.getsize(video_path)
    meta = json.dumps({
        'snippet': {'title': 'ToonPop Short', 'description': 'ToonPop World', 'tags': ['shorts', 'cartoon'], 'categoryId': '24'},
        'status': {'privacyStatus': 'private', 'selfDeclaredMadeForKids': False}}).encode()
    req = urllib.request.Request(
        'https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status',
        data=meta, method='POST',
        headers={'Authorization': 'Bearer ' + access, 'Content-Type': 'application/json',
                 'X-Upload-Content-Length': str(os.path.getsize(video_path)), 'X-Upload-Content-Type': 'video/mp4'})
    with urllib.request.urlopen(req, timeout=60) as r:
        loc = r.headers['Location']
    data = open(video_path, 'rb').read()
    for attempt in range(4):
        try:
            req = urllib.request.Request(loc, data=data, method='PUT',
                                         headers={'Content-Type': 'video/mp4'})
            with urllib.request.urlopen(req, timeout=600) as r:
                return json.load(r)['id']
        except Exception as e:
            time.sleep(5 * (attempt + 1))
    raise RuntimeError('upload failed')

def download_telegram_file(file_id, dest):
    j = api('getFile', {'file_id': file_id})
    path = j['result']['file_path']
    data = fetch(f'https://api.telegram.org/file/bot{TOKEN}/{path}')
    open(dest, 'wb').write(data)
    return len(data)

def api(method, params=None):
    url = f'https://api.telegram.org/bot{TOKEN}/{method}'
    req = urllib.request.Request(url + '?' + urllib.parse.urlencode(params or {}))
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', 'replace')[:200]
        raise RuntimeError(f'telegram {method}: {e.code} {body}')

def fetch(url, timeout=180):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()

def load_state():
    try:
        return json.load(open('state.json'))
    except Exception:
        return {'offset': 0, 'done': []}

def save_state(st):
    json.dump(st, open('state.json', 'w'))

def main():
    if not all([TOKEN, CHAT_ID, YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH]):
        print('MISSING_ENV'); sys.exit(0)
    log('loop started')
    last_beat = time.time()
    while True:
        try:
            st = load_state()
            j = api('getUpdates', {'offset': st['offset'], 'timeout': 25,
                                  'allowed_updates': '["message", "channel_post"]'})
            for u in j.get('result', []):
                process_update(u)
        except Exception as e:
            print('loop error:', e)
            time.sleep(10)

if __name__ == '__main__':
    main()