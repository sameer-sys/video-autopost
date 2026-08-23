#!/usr/bin/env python3
"""Facebook Page Reel + Instagram Reel publishing.
Both need secrets set in GitHub: FB_PAGE_TOKEN, FB_PAGE_ID, IG_USER_ID.
If they are missing, callers skip these platforms gracefully."""
import json, os, time, urllib.request, urllib.parse

GRAPH = 'https://graph.facebook.com/v26.0'


def _post(url, params):
    req = urllib.request.Request(url, data=urllib.parse.urlencode(params).encode(),
                                 headers={'Content-Type': 'application/x-www-form-urlencoded'})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def _get(url, params):
    req = urllib.request.Request(url + '?' + urllib.parse.urlencode(params))
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def fb_reel_upload(video_path, page_token, page_id, description):
    """3-phase Facebook Reel upload. Returns permalink."""
    # phase 1: start
    r1 = _post(f'{GRAPH}/{page_id}/video_reels',
               {'upload_phase': 'start', 'access_token': page_token})
    video_id = r1['video_id']
    # phase 2: transfer binary to rupload
    data = open(video_path, 'rb').read()
    last_err = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(
                f'https://rupload.facebook.com/video-upload/v26.0/{video_id}',
                data=data, method='POST',
                headers={'Authorization': 'OAuth ' + page_token,
                         'Content-Type': 'application/octet-stream',
                         'offset': '0'})
            with urllib.request.urlopen(req, timeout=600) as r:
                json.load(r)
            break
        except Exception as e:
            last_err = e
            print('rupload attempt', attempt + 1, 'failed:', e)
            time.sleep(5 * (attempt + 1))
    else:
        raise last_err
    # phase 3: finish + publish
    _post(f'{GRAPH}/{page_id}/video_reels',
          {'upload_phase': 'finish', 'video_id': video_id,
           'video_state': 'PUBLISHED', 'description': description,
           'access_token': page_token})
    # wait until permalink exists (processing can take a minute)
    for _ in range(12):
        try:
            j = _get(f'{GRAPH}/{video_id}', {'fields': 'permalink_url',
                                             'access_token': page_token})
            if j.get('permalink_url'):
                return 'https://facebook.com' + j['permalink_url']
        except Exception:
            pass
        time.sleep(10)
    return f'https://facebook.com/reel/{video_id}'


def fb_update_description(video_id, page_token, title, description):
    """Update an already-published FB reel/video description."""
    meta = urllib.parse.urlencode({'description': (title + '\n\n' + description)[:5000],
                                   'access_token': page_token})
    req = urllib.request.Request(f'{GRAPH}/{video_id}', data=meta.encode(), method='POST')
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


IG_GRAPH = 'https://graph.instagram.com'


def _ig_post(url, params, token):
    """Instagram Login API: Bearer header auth on graph.instagram.com."""
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=data, method='POST',
                                 headers={'Authorization': f'Bearer {token}'})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def _ig_get(url, params, token):
    qs = urllib.parse.urlencode(params)
    req = urllib.request.Request(f'{url}?{qs}',
                                 headers={'Authorization': f'Bearer {token}'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def ig_reel_publish(video_path, ig_user_id, page_token, caption,
                    telegram_file_url=''):
    """Instagram Reel via Instagram API with Instagram Login (graph.instagram.com).
    Needs a PUBLIC video url Meta's servers can download.
    Primary host: catbox.moe (permanent, correct mime). Fallback: telegram cdn."""
    media_url = ''
    try:
        import subprocess
        r = subprocess.run(['curl', '-s', '-F', 'reqtype=fileupload',
                            '-F', f'fileToUpload=@{video_path}',
                            'https://catbox.moe/user/api.php'],
                           capture_output=True, text=True, timeout=300)
        out = r.stdout.strip()
        if out.startswith('https://files.catbox.moe/'):
            media_url = out
    except Exception as e:
        print('catbox failed:', e)
    if not media_url and telegram_file_url:
        media_url = telegram_file_url
    if not media_url:
        raise RuntimeError('no public video url available for instagram')
    r1 = _ig_post(f'{IG_GRAPH}/me/media',
                  {'media_type': 'REELS', 'video_url': media_url,
                   'caption': caption[:2200], 'share_to_feed': 'true'},
                  page_token)
    cid = r1['id']
    # poll container status until processed
    for _ in range(30):
        st = _ig_get(f'{IG_GRAPH}/{cid}', {'fields': 'status_code'},
                     page_token)
        code = st.get('status_code')
        if code == 'FINISHED':
            break
        if code == 'ERROR':
            raise RuntimeError('instagram container error: ' +
                               json.dumps(st))
        time.sleep(10)
    else:
        raise RuntimeError('instagram processing timeout')
    r2 = _ig_post(f'{IG_GRAPH}/me/media_publish',
                  {'creation_id': cid}, page_token)
    mid = r2['id']
    for _ in range(6):
        try:
            p = _ig_get(f'{IG_GRAPH}/{mid}', {'fields': 'permalink'},
                        page_token)
            return p['permalink']
        except Exception:
            time.sleep(5)
    return f'https://instagram.com/reel/{mid}'
