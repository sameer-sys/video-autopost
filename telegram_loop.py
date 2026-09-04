#!/usr/bin/env python3
"""Continuous Telegram video pipeline (runs inside ONE long GitHub Actions job).

Polls Telegram every ~30s (long-poll), processes videos the moment they arrive,
posts to YouTube + Facebook Page + Instagram, sends the links, commits state.
A job can run up to 71h on a public repo; the schedule restarts it so coverage
is continuous. State is committed after every video, so restarts resume cleanly.
"""
import json, os, re, sys, subprocess, time, urllib.request, urllib.parse, html

import fb_ig

TOKEN = os.environ.get('TELEGRAM_TOKEN', '')
CHAT_ID = os.environ.get('CHAT_ID', '')
GEMINI_KEY = os.environ.get('GEMINI_KEY', '')
YT_CLIENT_ID = os.environ.get('YT_CLIENT_ID', '')
YT_CLIENT_SECRET = os.environ.get('YT_CLIENT_SECRET', '')
YT_REFRESH = os.environ.get('YT_REFRESH_TOKEN', '')
FB_PAGE_TOKEN = os.environ.get('FB_PAGE_TOKEN', '')
FB_PAGE_ID = os.environ.get('FB_PAGE_ID', '')
IG_USER_ID = os.environ.get('IG_USER_ID', '')
IG_TOKEN = os.environ.get('IG_TOKEN', '')
STATE_FILE = 'state.json'
VIDEOS_FILE = 'videos.json'   # history of received videos for the compile pipeline
PLACEHOLDER_CAPTION = ('🎬 New ToonPop World drop! Follow for daily cartoons 🍿\n'
                       '#cartoon #animation #reels #shorts #funny #toonpopworld')

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
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', 'replace')[:200]
        raise RuntimeError(f'telegram {method}: {e.code} {body}')

def safe_send(text):
    """Never let a notification failure kill processing/state."""
    try:
        api('sendMessage', {'chat_id': CHAT_ID, 'text': text})
    except Exception as e:
        print('sendMessage failed:', e)

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

def commit_state():
    """Push state.json + videos.json back to the repo so the next run resumes exactly here."""
    gh = os.environ.get('GITHUB_TOKEN', '')
    if not gh:
        return
    subprocess.run(['git', 'config', 'user.name', 'video-autopost-bot'], capture_output=True)
    subprocess.run(['git', 'config', 'user.email', 'video-autopost-bot@users.noreply.github.com'], capture_output=True)
    subprocess.run(['git', 'add', STATE_FILE, VIDEOS_FILE], capture_output=True)
    r = subprocess.run(['git', 'diff', '--cached', '--quiet'], capture_output=True)
    if r.returncode != 0:
        subprocess.run(['git', 'commit', '-m', 'state: ' + time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())], capture_output=True)
        p = subprocess.run(['git', 'push', 'https://x-access-token:' + gh + '@github.com/sameer-sys/video-autopost.git', 'main'],
                           capture_output=True, text=True)
        print('state pushed' if p.returncode == 0 else 'state push failed: ' + p.stderr[-200:])

def record_video(uid, file_id, yt_id, fb_id=''):
    """Append a processed video to videos.json (feeds the compile pipeline)."""
    try:
        hist = json.load(open(VIDEOS_FILE))
    except Exception:
        hist = []
    hist.append({'uid': uid, 'file_id': file_id, 'date': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                 'yt_id': yt_id, 'fb_id': fb_id})
    json.dump(hist[-500:], open(VIDEOS_FILE, 'w'))   # keep last 500

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
    last_err = None
    for attempt in range(4):  # free tier is flaky: retry with backoff
        try:
            req = urllib.request.Request(
                'https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent?key=' + GEMINI_KEY,
                data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=90) as r:
                j = json.load(r)
            cands = j.get('candidates') or []
            if not cands:
                raise RuntimeError('no candidates: ' + json.dumps(j.get('promptFeedback', {})))
            return cands[0]['content']['parts'][0]['text']
        except Exception as e:
            last_err = e
            print('gemini attempt', attempt + 1, 'failed:', e)
            time.sleep(5 * (attempt + 1))
    raise last_err

def fallback_package():
    return {
        'title': 'Watch This! #shorts',
        'description': 'Amazing video you need to see! Follow for more daily content.',
        'captions': ['Watch till the end!', 'You will love this!', 'Follow for more!'],
        'hashtags': ['#shorts', '#viral', '#trending', '#fyp', '#reels', '#explore',
                     '#video', '#daily', '#amazing', '#mustwatch', '#foryou', '#new'],
    }

def parse_package(raw):
    raw = re.sub(r'^```(json)?|```$', '', raw.strip(), flags=re.M).strip()
    p = json.loads(raw)
    return {
        'title': str(p.get('title', 'New Video'))[:60],
        'description': str(p.get('description', 'Watch till the end!')),
        'captions': [str(c) for c in p.get('captions', [])][:3],
        'hashtags': ['#' + str(h).lstrip('#') for h in p.get('hashtags', [])][:12],
    }

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
    data = open(video_path, 'rb').read()
    last_err = None
    for attempt in range(4):  # resumable PUT can 503: retry
        try:
            req = urllib.request.Request(loc, data=data, method='PUT',
                                         headers={'Content-Type': 'video/mp4'})
            with urllib.request.urlopen(req, timeout=600) as r:
                return json.load(r)['id']
        except Exception as e:
            last_err = e
            print('upload attempt', attempt + 1, 'failed:', e)
            time.sleep(5 * (attempt + 1))
    raise last_err

def parse_caption_update(txt):
    """Flexible parser for pasted caption packages (from Claude or written by hand)."""
    t = re.sub(r'\*+', '', txt.strip())          # strip markdown bold/italics
    ti = re.search(r'^\s*(?:yt\s+)?title\s*[:\-]\s*(.+)$', t, flags=re.M | re.I)
    if ti:
        title = ti.group(1).strip()
        di = re.search(r'^\s*(?:description|desc|caption)\s*[:\-]\s*(.+)$',
                       t[ti.end():], flags=re.M | re.I | re.S)
        if di:
            desc = di.group(1).strip()
        else:
            desc = t[ti.end():].strip()
        m = re.search(r'\n\s*(?:captions?|hashtags?)\s*[:\-]', desc, flags=re.I)
        if m:
            desc = desc[:m.start()].strip()
        return title[:100], desc
    lines = t.split('\n', 1)                      # plain fallback
    return lines[0].strip()[:100], lines[1].strip() if len(lines) > 1 else ''

def yt_update_meta(video_id, title, description, tags):
    access = yt_access_token()
    meta = json.dumps({
        'id': video_id,
        'snippet': {'title': title[:100], 'description': description,
                    'tags': tags, 'categoryId': '24'}}).encode()
    req = urllib.request.Request(
        'https://www.googleapis.com/youtube/v3/videos?part=snippet',
        data=meta, method='PUT',
        headers={'Authorization': 'Bearer ' + access, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)['id']

def process_update(u):
    """Handle one Telegram update. Never raises out of the loop."""
    st = load_state()
    uid = u['update_id']
    m = u.get('message') or u.get('channel_post') or {}
    st['offset'] = uid + 1
    # text message = Claude-written captions for the last uploaded video
    txt = (m.get('text') or '').strip()
    if txt and not txt.startswith('/'):
        lm = re.search(r'(?:youtube\.com/(?:shorts/|watch\?v=)|youtu\.be/)([\w-]{11})', txt)
        last_vid = lm.group(1) if lm else st.get('last_video_id')
        if not last_vid:
            safe_send('Send a video first, then paste your captions to update it.')
        else:
            title, desc = parse_caption_update(txt)
            tags = [w.lstrip('#') for w in (title + ' ' + desc).split() if w.startswith('#')]
            try:
                yt_update_meta(last_vid, title, desc, tags)
                fb_note = ''
                fb_vid = st.get('last_fb_video_id')
                if FB_PAGE_TOKEN and fb_vid:
                    try:
                        fb_ig.fb_update_description(fb_vid, FB_PAGE_TOKEN,
                                                    title, desc)
                        fb_note = '\n📘 Facebook description updated'
                    except Exception as e:
                        print('fb desc update failed:', e)
                safe_send('\u2705 Captions applied!\n\n' + title +
                          '\n\nhttps://youtube.com/shorts/' + last_vid + fb_note)
                print('captions applied to', last_vid)
            except Exception as e:
                print('caption update error:', e)
                safe_send(f'\u274c Caption update failed: {e}')
            commit_state()
        save_state(st)
        return
    vid = m.get('video')
    doc = m.get('document')
    if doc and str(doc.get('mime_type', '')).startswith('video/'):
        vid = doc   # original-quality file upload (no Telegram recompression)
    if vid and uid not in st['done']:
        try:
            src = f"in_{uid}.mp4"
            hd = f"hd_{uid}.mp4"
            size = download_telegram_file(vid['file_id'], src)
            print(time.strftime('%H:%M:%S'), 'downloaded', size)
            upscale(src, hd)
            print(time.strftime('%H:%M:%S'), 'upscaled ok')
            if GEMINI_KEY:
                try:
                    raw = gemini_package()
                    pkg = parse_package(raw)
                    print('captions ok:', pkg['title'])
                except Exception as e:
                    print('gemini failed, using fallback:', e)
                    pkg = fallback_package()
            else:
                print('gemini disabled, using default captions')
                pkg = fallback_package()
            vid_id = yt_upload(hd, pkg)
            st['last_video_id'] = vid_id   # target for caption updates
            st['done'].append(uid)         # mark done NOW: later failures must never re-upload
            save_state(st)
            record_video(uid, vid['file_id'], vid_id)
            commit_state()
            links = ['🎬 https://youtube.com/shorts/' + vid_id]
            print(time.strftime('%H:%M:%S'), 'UPLOADED yt', vid_id)
            # Facebook Page Reel (skipped silently if secrets missing)
            if FB_PAGE_TOKEN and FB_PAGE_ID:
                try:
                    fb_link = fb_ig.fb_reel_upload(hd, FB_PAGE_TOKEN,
                                                   FB_PAGE_ID,
                                                   PLACEHOLDER_CAPTION)
                    st['last_fb_video_id'] = re.sub(r'[^0-9]', '',
                                                    fb_link.rstrip('/').split('/')[-1]) or None
                    links.append('📘 ' + fb_link)
                    print(time.strftime('%H:%M:%S'), 'UPLOADED fb', fb_link)
                except Exception as e:
                    print('fb upload failed:', e)
                    links.append('📘 failed: ' + str(e)[:80])
            # Instagram Reel (skipped silently if secrets missing)
            if IG_TOKEN and IG_USER_ID:
                try:
                    tg = api('getFile', {'file_id': vid['file_id']})
                    tg_url = ('https://api.telegram.org/file/bot' + TOKEN +
                              '/' + tg['result']['file_path'])
                    ig_link = fb_ig.ig_reel_publish(hd, IG_USER_ID,
                                                    IG_TOKEN,
                                                    PLACEHOLDER_CAPTION,
                                                    telegram_file_url=tg_url)
                    links.append('📸 ' + ig_link)
                    print(time.strftime('%H:%M:%S'), 'UPLOADED ig', ig_link)
                except Exception as e:
                    print('ig upload failed:', e)
                    links.append('📸 failed: ' + str(e)[:80])
            safe_send('\n'.join(links))
            print(time.strftime('%H:%M:%S'), 'replied to video', uid)
            commit_state()   # durable progress after EVERY video
        except Exception as e:
            print('ERROR on update', uid, ':', e)
            st['done'].append(uid)   # never retry a broken update forever
            save_state(st)
            try:
                safe_send(f'\u274c Processing failed: {e}')
            except Exception:
                pass
        finally:
            for f in (src, hd):
                if os.path.exists(f):
                    os.remove(f)
    save_state(st)

def main():
    if not all([TOKEN, CHAT_ID, YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH]):
        print('MISSING_ENV'); sys.exit(0)
    print('loop started', time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime()))
    last_beat = time.time()
    while True:
        try:
            st = load_state()
            # heartbeat: >=1 commit/day keeps the repo 'active' so GitHub never
            # auto-disables the schedule during long breaks from posting
            if time.time() - last_beat > 21600:
                st['last_beat'] = time.time()
                save_state(st)
                commit_state()
                last_beat = time.time()
            j = api('getUpdates', {'offset': st['offset'], 'timeout': 25, 'allowed_updates': '["message", "channel_post"]'})
            updates = j.get('result', [])
            if updates:
                print(time.strftime('%H:%M:%S'), 'updates:', len(updates))
            for u in updates:
                try:
                    process_update(u)
                except Exception as e:
                    print('update', u.get('update_id'), 'error:', e)
                    st = load_state()
                    st['done'].append(u['update_id'])
                    save_state(st)
        except Exception as e:
            print('loop error:', e)
            time.sleep(10)
        time.sleep(2)

if __name__ == '__main__':
    main()