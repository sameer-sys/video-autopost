#!/usr/bin/env python3
"""
Posting Bot — MAIN BOT. Receives video, processes with Editor+Adder, uploads to YT/IG/FB with platform tricks.
Platform Tricks Integrated:
- YT: Private at night → Public 09:00 IST, SEO title/tags, private upload
- IG: Trending audio (vol=1%), caption-first keywords, hashtags, cover selection
- FB: Share text, cross-post same day, native Reels
Integrates: Editor (hook/thumb/blur), Adder (metadata), triggers next batch after upload.
"""
import json, os, re, sys, subprocess, time, urllib.request, urllib.parse, html, random, datetime

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
# Local Bot API server (2GB) if set, else cloud (20MB)
TG_API = os.environ.get('TG_API_BASE', 'https://api.telegram.org').rstrip('/')
TG_FILE = os.environ.get('TG_FILE_BASE', TG_API).rstrip('/')

STATE_FILE = 'state.json'
VIDEOS_FILE = 'videos.json'
PLACEHOLDER_CAPTION = ('🎬 New ToonPop World drop! Follow for daily cartoons 🍿\n'
                       '#cartoon #animation #reels #shorts #funny #toonpopworld')

def log(msg):
    print(time.strftime('%H:%M:%S'), msg, flush=True)

def api(method, params=None, files=None):
    url = f'{TG_API}/bot{TOKEN}/{method}'
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
    data = fetch(f'{TG_FILE}/bot{TOKEN}/{path}')
    open(dest, 'wb').write(data)
    return len(data)

def gemini_package():
    if not GEMINI_KEY:
        raise RuntimeError('no GEMINI_KEY')
    prompt = """You are a YouTube Shorts/Reels caption expert for a cartoon cat channel (ToonPop World).
Return JSON only with: title (max 60 chars), description (engaging, 2-3 lines + hashtags),
captions (3 short lines for overlay), hashtags (10-12 relevant tags).
Style: Hindi/English mix, hooks, emojis, viral Shorts style."""
    import requests
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_KEY}"
    headers = {'Content-Type': 'application/json'}
    data = {"contents": [{"parts": [{"text": prompt}]}]}
    for attempt in range(3):
        try:
            r = requests.post(url, headers=headers, json=data, timeout=60)
            if r.status_code == 200:
                raw = r.json()['candidates'][0]['content']['parts'][0]['text']
                raw = re.sub(r'^```(json)?|```$', '', raw.strip(), flags=re.M).strip()
                p = json.loads(raw)
                return {
                    'title': str(p.get('title', 'New Video'))[:60],
                    'description': str(p.get('description', 'Watch till the end!')),
                    'captions': [str(c) for c in p.get('captions', [])][:3],
                    'hashtags': ['#' + str(h).lstrip('#') for h in p.get('hashtags', [])][:12],
                }
        except Exception as e:
            log(f'gemini attempt {attempt+1} failed: {e}')
            time.sleep(5 * (attempt + 1))
    raise RuntimeError('gemini failed after retries')

def fallback_package():
    return {
        'title': 'Watch This! #shorts',
        'description': 'Amazing video you need to see! Follow for more daily content.',
        'captions': ['Watch till the end!', 'You will love this!', 'Follow for more!'],
        'hashtags': ['#shorts', '#viral', '#trending', '#fyp', '#reels', '#shorts',
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

def yt_upload(video_path, pkg, privacy='private'):
    access = yt_access_token()
    size = os.path.getsize(video_path)
    meta = json.dumps({
        'snippet': {'title': pkg['title'], 'description': pkg['description'] + '\n\n' + ' '.join(pkg['hashtags']),
                    'tags': [h.lstrip('#') for h in pkg['hashtags']], 'categoryId': '24'},
        'status': {'privacyStatus': privacy, 'selfDeclaredMadeForKids': False}}).encode()
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
            with urllib.request.urlopen(req, timeout=600) as r:
                return json.load(r)['id']
        except Exception as e:
            last_err = e
            log(f'upload attempt {attempt + 1} failed: {e}')
            time.sleep(5 * (attempt + 1))
    raise last_err

def parse_caption_update(txt):
    t = re.sub(r'\*+', '', txt.strip())
    ti = re.search(r'^\s*(?:yt\s+)?title\s*[:\\-]\s*(.+)$', t, flags=re.M | re.I)
    if ti:
        title = ti.group(1).strip()
        di = re.search(r'^\s*(?:description|desc|caption)\s*[:\\-]\s*(.+)$',
                       t[ti.end():], flags=re.M | re.I | re.S)
        if di:
            desc = di.group(1).strip()
        else:
            desc = t[ti.end():].strip()
        m = re.search(r'\n\s*(?:captions?|hashtags?)\s*[:\\-]', desc, flags=re.I)
        if m:
            desc = desc[:m.start()].strip()
        return title[:100], desc
    lines = t.split('\n', 1)
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

def parse_caption_update(txt):
    t = re.sub(r'\*+', '', txt.strip())
    ti = re.search(r'^\s*(?:yt\s+)?title\s*[:\\-]\s*(.+)$', t, flags=re.M | re.I)
    if ti:
        title = ti.group(1).strip()
        di = re.search(r'^\s*(?:description|desc|caption)\s*[:\\-]\s*(.+)$',
                       t[ti.end():], flags=re.M | re.I | re.S)
        if di:
            desc = di.group(1).strip()
        else:
            desc = t[ti.end():].strip()
        m = re.search(r'\n\s*(?:captions?|hashtags?)\s*[:\\-]', desc, flags=re.I)
        if m:
            desc = desc[:m.start()].strip()
        return title[:100], desc
    lines = t.split('\n', 1)
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

def yt_set_privacy(video_id, privacy):
    access = yt_access_token()
    meta = json.dumps({'id': video_id, 'status': {'privacyStatus': privacy}}).encode()
    req = urllib.request.Request(
        'https://www.googleapis.com/upload/youtube/v3/videos?part=status',
        data=meta, method='PUT',
        headers={'Authorization': 'Bearer ' + access, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)

def parse_caption_update(txt):
    t = re.sub(r'\*+', '', txt.strip())
    ti = re.search(r'^\s*(?:yt\s+)?title\s*[:\\-]\s*(.+)$', t, flags=re.M | re.I)
    if ti:
        title = ti.group(1).strip()
        di = re.search(r'^\s*(?:description|desc|caption)\s*[:\\-]\s*(.+)$',
                       t[ti.end():], flags=re.M | re.I | re.S)
        if di:
            desc = di.group(1).strip()
        else:
            desc = t[ti.end():].strip()
        m = re.search(r'\n\s*(?:captions?|hashtags?)\s*[:\\-]', desc, flags=re.I)
        if m:
            desc = desc[:m.start()].strip()
        return title[:100], desc
    lines = t.split('\n', 1)
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

def parse_caption_update(txt):
    t = re.sub(r'\*+', '', txt.strip())
    ti = re.search(r'^\s*(?:yt\s+)?title\s*[:\\-]\s*(.+)$', t, flags=re.M | re.I)
    if ti:
        title = ti.group(1).strip()
        di = re.search(r'^\s*(?:description|desc|caption)\s*[:\\-]\s*(.+)$',
                       t[ti.end():], flags=re.M | re.I | re.S)
        if di:
            desc = di.group(1).strip()
        else:
            desc = t[ti.end():].strip()
        m = re.search(r'\n\s*(?:captions?|hashtags?)\s*[:\\-]', desc, flags=re.I)
        if m:
            desc = desc[:m.start()].strip()
        return title[:100], desc
    lines = t.split('\n', 1)
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

def yt_set_privacy(video_id, privacy):
    access = yt_access_token()
    meta = json.dumps({'id': video_id, 'status': {'privacyStatus': privacy}}).encode()
    req = urllib.request.Request(
        'https://www.googleapis.com/upload/youtube/v3/videos?part=status',
        data=meta, method='PUT',
        headers={'Authorization': 'Bearer ' + access, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)

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

def main():
    if not all([TOKEN, CHAT_ID, YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH]):
        log('MISSING_ENV'); sys.exit(0)
    log('loop started ' + time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime()))
    last_beat = time.time()
    while True:
        try:
            st = load_state()
            if time.time() - last_beat > 21600:
                st['last_beat'] = time.time()
                save_state(st)
                commit_state()
                last_beat = time.time()
            j = api('getUpdates', {'offset': st['offset'], 'timeout': 25,
                                  'allowed_updates': '["message", "channel_post"]'})
            for u in j.get('result', []):
                process_update(u)
        except Exception as e:
            log('loop error:', e)
            time.sleep(10)

def process_update(u):
    st = load_state()
    uid = u['update_id']
    m = u.get('message') or u.get('channel_post') or {}
    st['offset'] = uid + 1
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
                        fb_ig.fb_update_description(fb_vid, FB_PAGE_TOKEN, title, desc)
                        fb_note = '\n📘 Facebook description updated'
                    except Exception as e:
                        fb_note = '\n📘 FB update failed: ' + str(e)[:80]
                safe_send('✅ Captions applied!\n\n' + title +
                          '\n\nhttps://youtube.com/shorts/' + last_vid + fb_note)
                log('captions applied to', last_vid)
            except Exception as e:
                log('caption update error:', e)
                safe_send(f'❌ Caption update failed: {e}')
            commit_state()
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
            log('downloaded', size)
            dur = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                                  '-of', 'default=noprint_wrappers=1:nokey=1', src],
                               capture_output=True, text=True)
            try:
                seconds = float(dur.stdout.strip())
            except:
                seconds = 0
            if seconds > 45:
                safe_send('❌ Video too long (' + str(int(seconds)) + 's). Max 45 seconds.')
                st['done'].append(uid)
                save_state(st)
                return
            upscale(src, hd)
            log('upscaled ok')
            # EDITOR BOT: hook overlay + thumbnail + watermark blur
            try:
                import editor_bot as _ed
                hook_txt = ''
                try:
                    _ad = json.load(open('adder_state.json'))
                    hook_txt = _ad.get('hook_text', '')
                except Exception:
                    pass
                rep = _ed.process(hd, hook_txt, workdir='/tmp')
                if rep.get('problems'):
                    safe_send('❌ ' + '; '.join(rep['problems']))
                    st['done'].append(uid)
                    save_state(st)
                    return
                if rep.get('ready'):
                    hd = rep['ready']
                log('editor:', rep.get('hook'), 'thumb:', rep.get('thumbnail'))
            except Exception as e:
                log('editor skipped (non-fatal):', e)
            if GEMINI_KEY:
                try:
                    raw = gemini_package()
                    pkg = parse_package(raw)
                    log('captions ok:', pkg['title'])
                except Exception as e:
                    log('gemini failed, using fallback:', e)
                    pkg = fallback_package()
            else:
                log('gemini disabled, using default captions')
                pkg = fallback_package()
            # PM1 Adder: pre-built package wins (IG locks caption at publish)
            try:
                _ad = json.load(open('adder_state.json'))
                if _ad.get('yt', {}).get('title'):
                    pkg = {'title': _ad['yt']['title'][:60],
                           'description': _ad['yt'].get('description', pkg['description']),
                           'hashtags': [h for h in _ad.get('ig', {}).get('caption', '').split()
                                        if h.startswith('#')][:12] or pkg['hashtags'],
                           'tags': _ad['yt'].get('tags', ''),
                           'ig_caption': _ad.get('ig', {}).get('caption', ''),
                           'fb_text': _ad.get('fb', {}).get('text', '')}
                    log('adder package applied:', pkg['title'])
            except Exception as e:
                log('adder skipped (non-fatal):', e)
            # PLATFORM-SPECIFIC UPLOADS WITH TRICKS
            # YT: Private at night, public at 09:00 IST
            vid_id = yt_upload(hd, pkg, privacy='private')
            st['last_video_id'] = vid_id
            st['done'].append(uid)
            save_state(st)
            record_video(uid, vid['file_id'], vid_id)
            commit_state()
            # FB Reel (cross-post same day)
            fb_link = ''
            if FB_PAGE_TOKEN and FB_PAGE_ID:
                try:
                    fb_link = fb_ig.fb_reel_upload(hd, FB_PAGE_TOKEN, FB_PAGE_ID, PLACEHOLDER_CAPTION)
                    st['last_fb_video_id'] = re.sub(r'[^0-9]', '',
                                                    fb_link.rstrip('/').split('/')[-1]) or None
                    log('UPLOADED fb', fb_link)
                except Exception as e:
                    log('fb upload failed:', e)
            # IG Reel with trending audio (vol=1%) - needs API support
            ig_link = ''
            if IG_TOKEN and IG_USER_ID:
                try:
                    tg = api('getFile', {'file_id': vid['file_id']})
                    tg_url = ('https://api.telegram.org/file/bot' + TOKEN + '/' + tg['result']['file_path'])
                    # IG Reels: trending audio at vol=1% - handled by fb_ig
                    ig_link = fb_ig.ig_reel_publish(hd, IG_USER_ID, IG_TOKEN, PLACEHOLDER_CAPTION, telegram_file_url=tg_url)
                    log('UPLOADED ig', ig_link)
                except Exception as e:
                    log('ig upload failed:', e)
            # YT: schedule public at 09:00 IST (handled by yt_flip_bot)
            # Reply with Done + links
            links = ['🎬 https://youtube.com/shorts/' + vid_id]
            if fb_link:
                links.append('📘 ' + fb_link)
            if ig_link:
                links.append('📸 ' + ig_link)
            safe_send('✅ Done\n' + '\n'.join(links))
            log('replied to video', uid)
            # TRIGGER NEXT BATCH (Trend -> Script)
            try:
                import trend_bot as _tb
                import script_bot as _sb
                _tb.main()
                n, _ = _sb.next_batch(send=True)
                log('next batch sent:', n)
            except Exception as e:
                log('next batch failed (non-fatal):', e)
            commit_state()
        except Exception as e:
            log('ERROR on update', uid, ':', e)
            st['done'].append(uid)
            save_state(st)
            try:
                safe_send(f'❌ Processing failed: {e}')
            except Exception:
                pass
        finally:
            for f in (src, hd):
                if os.path.exists(f):
                    os.remove(f)
        save_state(st)

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

def log(msg):
    print(time.strftime('%H:%M:%S'), msg, flush=True)

if __name__ == '__main__':
    main()