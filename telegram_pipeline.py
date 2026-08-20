#!/usr/bin/env python3
"""24/7 Telegram video pipeline (runs in GitHub Actions cloud):
video from bot -> download -> upscale to 1080x1920 HD -> Gemini viral captions
-> YouTube Shorts upload -> reply with link + caption package.
State (processed update ids) is committed back to the repo so runs are idempotent."""
import json, os, re, sys, subprocess, urllib.request, urllib.parse, html

TOKEN = os.environ.get('TELEGRAM_TOKEN', '')
CHAT_ID = os.environ.get('CHAT_ID', '')
GEMINI_KEY = os.environ.get('GEMINI_KEY', '')
YT_CLIENT_ID = os.environ.get('YT_CLIENT_ID', '')
YT_CLIENT_SECRET = os.environ.get('YT_CLIENT_SECRET', '')
YT_REFRESH = os.environ.get('YT_REFRESH_TOKEN', '')
STATE_FILE = 'state.json'

def api(method, params=None, files=None):
    url = f'https://api.telegram.org/bot{TOKEN}/{method}'
    if files:
        args = ['curl', '-s']
        for k, v in (params or {}).items():
            args += ['-F', f'{k}={v}']
        for k, path in files.items():
            args += ['-F', f'{k}=@{path}']
        args.append(url)
        r = subprocess.run(args, capture_output=True, text=True)
        return json.loads(r.stdout)
    req = urllib.request.Request(url + '?' + urllib.parse.urlencode(params or {}))
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)

def fetch(url, timeout=180):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()

def load_state():
    try:
        return json.load(open(STATE_FILE))
    except Exception:
        return {'offset': 0, 'done': []}

def save_state(st):
    json.dump(st, open(STATE_FILE, 'w'))

def download_telegram_file(file_id, dest):
    j = api('getFile', {'file_id': file_id})
    path = j['result']['file_path']
    data = fetch('https://api.telegram.org/file/bot' + TOKEN + '/' + path)
    open(dest, 'wb').write(data)
    return len(data)

def upscale(src, dst):
    """474x850 -> 1080x1920 HD: lanczos + sharpen + high bitrate."""
    cmd = ['ffmpeg', '-y', '-i', src,
           '-vf', 'scale=1080:1920:flags=lanczos,unsharp=5:5:0.8:5:5:0.4',
           '-c:v', 'libx264', '-preset', 'slow', '-crf', '18', '-b:v', '10M',
           '-maxrate', '12M', '-bufsize', '20M', '-c:a', 'aac', '-b:a', '192k',
           '-r', '30', dst, '-loglevel', 'error']
    subprocess.run(cmd, check=True)

def gemini_package():
    body = {
        "contents": [{"parts": [{"text": (
            "Write a viral social media caption package for a short vertical video. "
            "Return ONLY valid JSON with keys: title (max 60 chars, hook style), "
            "description (2 sentences with emoji), captions (array of 3 short lines), "
            "hashtags (array of 12 trending tags). No markdown, no code fences."
        )}]}]
    }
    req = urllib.request.Request(
        'https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent?key=' + GEMINI_KEY,
        data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=90) as r:
        j = json.load(r)
    cands = j.get('candidates') or []
    if not cands:
        raise RuntimeError('no candidates: ' + json.dumps(j.get('promptFeedback', {})))
    return cands[0]['content']['parts'][0]['text']

def parse_package(raw):
    raw = re.sub(r'^```(json)?|```$', '', raw.strip(), flags=re.M).strip()
    p = json.loads(raw)
    return {
        'title': str(p.get('title', 'New Video'))[:60],
        'description': str(p.get('description', 'Watch till the end!')),
        'captions': [str(c) for c in p.get('captions', [])][:3],
        'hashtags': ['#' + str(h).lstrip('#') for h in p.get('hashtags', [])][:12],
    }

def format_package(p):
    lines = [f"\U0001F3AC *{p['title']}*", "", p['description'], "", "Captions:"]
    lines += [f"- {c}" for c in p['captions']]
    lines += ["", "Hashtags: " + ' '.join(p['hashtags'])]
    return '\n'.join(lines)

def yt_access_token():
    body = urllib.parse.urlencode({
        'client_id': YT_CLIENT_ID, 'client_secret': YT_CLIENT_SECRET,
        'refresh_token': YT_REFRESH, 'grant_type': 'refresh_token'}).encode()
    req = urllib.request.Request('https://oauth2.googleapis.com/token', data=body,
                                 headers={'Content-Type': 'application/x-www-form-urlencoded'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)['access_token']

def yt_upload(video_path, pkg):
    access = yt_access_token()
    size = os.path.getsize(video_path)
    meta = json.dumps({
        'snippet': {'title': pkg['title'], 'description': pkg['description'] + '\n\n' + ' '.join(pkg['hashtags']),
                    'tags': [h.lstrip('#') for h in pkg['hashtags']], 'categoryId': '24'},
        'status': {'privacyStatus': 'public', 'selfDeclaredMadeForKids': False}}).encode()
    req = urllib.request.Request(
        'https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status',
        data=meta, method='POST',
        headers={'Authorization': 'Bearer ' + access, 'Content-Type': 'application/json',
                 'X-Upload-Content-Length': str(size), 'X-Upload-Content-Type': 'video/mp4'})
    with urllib.request.urlopen(req, timeout=60) as r:
        loc = r.headers['Location']
    req = urllib.request.Request(loc, data=open(video_path, 'rb').read(), method='PUT',
                                 headers={'Content-Type': 'video/mp4'})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.load(r)['id']

def main():
    if not all([TOKEN, CHAT_ID, GEMINI_KEY, YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH]):
        print('MISSING_ENV'); sys.exit(0)
    st = load_state()
    j = api('getUpdates', {'offset': st['offset'], 'timeout': 1})
    updates = j.get('result', [])
    print('updates:', len(updates))
    for u in updates:
        uid = u['update_id']
        m = u.get('message') or u.get('channel_post') or {}
        st['offset'] = uid + 1
        vid = m.get('video')
        if vid and uid not in st['done']:
            try:
                src = f"in_{uid}.mp4"
                hd = f"hd_{uid}.mp4"
                size = download_telegram_file(vid['file_id'], src)
                print('downloaded', size)
                upscale(src, hd)
                print('upscaled ok')
                raw = gemini_package()
                pkg = parse_package(raw)
                print('captions ok:', pkg['title'])
                vid_id = yt_upload(hd, pkg)
                link = f"https://youtube.com/shorts/{vid_id}"
                print('UPLOADED', link)
                text = format_package(pkg) + f"\n\n\U0001F517 {link}"
                api('sendMessage', {'chat_id': CHAT_ID, 'text': text, 'parse_mode': 'Markdown'})
                st['done'].append(uid)
                print('replied to video', uid)
            except Exception as e:
                print('ERROR on update', uid, ':', e)
                try:
                    api('sendMessage', {'chat_id': CHAT_ID, 'text': f'\u274c Processing failed: {e}'})
                except Exception:
                    pass
            finally:
                for f in (src, hd):
                    if os.path.exists(f):
                        os.remove(f)
        save_state(st)

if __name__ == '__main__':
    main()