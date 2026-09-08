#!/usr/bin/env python3
"""
Posting Bot — Bot API version (20MB limit, works reliably).
Downloads video → upscales → uploads to YT private → replies "✅ Done"
"""
import json, os, re, sys, subprocess, time, urllib.request, urllib.parse, mimetypes
import requests
from pathlib import Path

# ─── Config ───
BOT_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
YT_CLIENT_ID = os.environ.get("YT_CLIENT_ID")
YT_CLIENT_SECRET = os.environ.get("YT_CLIENT_SECRET")
YT_REFRESH_TOKEN = os.environ.get("YT_REFRESH_TOKEN")
STATE_FILE = "state.json"

API = "https://api.telegram.org/bot"
GH_TOKEN = os.environ.get("GITHUB_TOKEN")

def log(*a): print(time.strftime("[%H:%M:%S]"), *a, flush=True)

def gh_headers():
    return {"Authorization": f"token {GH_TOKEN}", "Accept": "application/vnd.github+json"}

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"offset": 0, "processed": []}

def save_state(st):
    with open(STATE_FILE, "w") as f:
        json.dump(st, f)

def commit_state():
    if not GH_TOKEN:
        return
    subprocess.run(["git", "config", "user.name", "github-actions"], capture_output=True)
    subprocess.run(["git", "config", "user.email", "github-actions@github.com"], capture_output=True)
    subprocess.run(["git", "add", STATE_FILE], capture_output=True)
    subprocess.run(["git", "commit", "-m", f"chore: update state {time.strftime('%Y-%m-%d %H:%M:%S')}"], capture_output=True)
    p = subprocess.run(["git", "push", f"https://x-access-token:{GH_TOKEN}@github.com/sameer-sys/video-autopost.git", "main"], capture_output=True)
    if p.returncode == 0:
        log("state.json pushed")

def tg_get_updates(offset, timeout=30):
    url = f"{API}{BOT_TOKEN}/getUpdates?offset={offset}&timeout={timeout}&allowed_updates=message"
    with urllib.request.urlopen(url, timeout=timeout+10) as r:
        return json.load(r)

def tg_send_message(chat_id, text):
    url = f"{API}{BOT_TOKEN}/sendMessage"
    data = json.dumps({"chat_id": chat_id, "text": text}).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=10)

def tg_get_file(file_id):
    url = f"{API}{BOT_TOKEN}/getFile?file_id={file_id}"
    with urllib.request.urlopen(url, timeout=10) as r:
        return json.load(r)

def download_via_bot_api(file_id, dest_path):
    """Bot API download (20MB limit)."""
    info = tg_get_file(file_id)
    if not info.get("ok"):
        raise Exception(f"getFile failed: {info}")
    url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{info['result']['file_path']}"
    urllib.request.urlretrieve(url, dest_path)

def upscale(inp, out):
    """Force 1080x1920."""
    cmd = ["ffmpeg","-y","-i",inp,"-vf","scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2","-c:v","libx264","-preset","fast","-crf","23","-c:a","aac","-b:a","128k",out]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        raise Exception(f"ffmpeg failed: {r.stderr}")

def yt_access_token():
    """Refresh the YouTube OAuth access token. Raises with Google's actual
    error body on failure (e.g. invalid_grant / invalid_client) instead of
    the opaque "HTTP Error 400: Bad Request" urllib used to give."""
    resp = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": YT_CLIENT_ID,
            "client_secret": YT_CLIENT_SECRET,
            "refresh_token": YT_REFRESH_TOKEN,
            "grant_type": "refresh_token",
        },
        timeout=30,
    )
    if resp.status_code != 200:
        raise Exception(f"YouTube token refresh failed: HTTP {resp.status_code} - {resp.text}")
    return resp.json()["access_token"]

def yt_upload_private(token, video_path, title, desc, tags):
    """Upload to YT as PRIVATE using resumable upload (fixes HTTP 400)."""
    if not os.path.isfile(video_path):
        raise FileNotFoundError(f"Video file not found: {video_path}")
    
    file_size = os.path.getsize(video_path)
    mime_type, _ = mimetypes.guess_type(video_path)
    mime_type = mime_type or "video/mp4"
    
    metadata = {
        "snippet": {
            "title": (title or "")[:100],
            "description": (desc or "")[:5000],
            "tags": tags or [],
            "categoryId": "22",
        },
        "status": {
            "privacyStatus": "private",
            "selfDeclaredMadeForKids": False,
        },
    }
    
    # Step 1: Initiate resumable upload
    init_headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Type": mime_type,
        "X-Upload-Content-Length": str(file_size),
    }
    params = {"uploadType": "resumable", "part": "snippet,status"}
    
    init_resp = requests.post(
        "https://www.googleapis.com/upload/youtube/v3/videos",
        params=params,
        headers=init_headers,
        data=json.dumps(metadata),
        timeout=30,
    )
    if init_resp.status_code != 200:
        raise RuntimeError(f"Failed to initiate resumable upload: HTTP {init_resp.status_code} - {init_resp.text}")
    
    upload_url = init_resp.headers.get("Location")
    if not upload_url:
        raise RuntimeError(f"No upload URL returned by YouTube. Response headers: {dict(init_resp.headers)}")
    
    # Step 2: PUT video bytes to session URL
    upload_headers = {
        "Content-Type": mime_type,
        "Content-Length": str(file_size),
    }
    
    max_retries = 3
    last_error = None
    for attempt in range(1, max_retries + 1):
        with open(video_path, "rb") as f:
            upload_resp = requests.put(
                upload_url,
                headers=upload_headers,
                data=f,
                timeout=(30, 600),
            )
        if upload_resp.status_code in (200, 201):
            video_id = upload_resp.json().get("id")
            if not video_id:
                raise RuntimeError(f"Upload succeeded but no video ID in response: {upload_resp.text}")
            return video_id
        last_error = f"HTTP {upload_resp.status_code} - {upload_resp.text}"
        if upload_resp.status_code >= 500 and attempt < max_retries:
            time.sleep(2 ** attempt)
            continue
        break
    
    raise RuntimeError(f"Video upload failed: {last_error}")

def process_video(chat_id, file_id, caption):
    log(f"Processing video {file_id}")
    raw = f"raw_{file_id}.mp4"
    up = f"up_{file_id}.mp4"
    
    # Download via Bot API (20MB limit)
    file_info = tg_get_file(file_id)
    if not file_info.get("ok"):
        raise Exception(f"getFile failed: {file_info}")
    file_size = file_info["result"].get("file_size", 0)
    if file_size > 20 * 1024 * 1024:
        raise Exception(f"File {file_size/1024/1024:.1f}MB > 20MB Bot API limit. Compress video.")
    
    download_via_bot_api(file_id, raw)
    log(f"Downloaded: {file_size} bytes")
    
    # Upscale
    upscale(raw, up)
    log("Upscaled to 1080x1920")
    
    # Upload to YT private
    token = yt_access_token()
    title = caption[:100] if caption else f"ToonPop Short {time.strftime('%m/%d')}"
    desc = f"{caption}\n\n#Shorts #ToonPopWorld" if caption else "#Shorts #ToonPopWorld"
    tags = ["Shorts", "ToonPop", "Cartoon", "Hindi", "Funny"]
    
    result = yt_upload_private(token, up, title, desc, tags)
    video_id = result.get("id")
    log(f"Uploaded to YT PRIVATE: {video_id}")
    
    # Cleanup
    for f in [raw, up]:
        try: os.remove(f)
        except: pass
    
    return video_id

def main():
    if not BOT_TOKEN:
        log("TELEGRAM_TOKEN missing")
        sys.exit(1)
    if not CHAT_ID:
        log("CHAT_ID missing")
        sys.exit(1)
    
    # Startup diagnostic: verify YouTube OAuth works before waiting on Telegram,
    # and report the result straight to Telegram so we don't need a test video
    # or GitHub Actions log access to see what's wrong.
    try:
        _tok = yt_access_token()
        log(f"YouTube token refresh OK at startup (len={len(_tok)})")
        tg_send_message(CHAT_ID, "\u2705 Startup check: YouTube auth OK, bot is ready.")
    except Exception as e:
        log(f"YouTube token refresh FAILED at startup: {e}")
        tg_send_message(CHAT_ID, f"\u26a0\ufe0f Startup check: YouTube auth FAILED - {e}")

    state = load_state()
    offset = state.get("offset", 0)
    processed = set(state.get("processed", []))
    
    log(f"Bot started. Offset: {offset}")
    
    while True:
        try:
            updates = tg_get_updates(offset)
            if not updates.get("ok"):
                log(f"getUpdates failed: {updates}")
                time.sleep(5)
                continue
            
            for upd in updates.get("result", []):
                offset = upd["update_id"] + 1
                msg = upd.get("message")
                if not msg or "video" not in msg:
                    continue
                
                chat_id = msg["chat"]["id"]
                file_id = msg["video"]["file_id"]
                caption = msg.get("caption", "")
                
                if file_id in processed:
                    continue
                
                try:
                    vid = process_video(chat_id, file_id, caption)
                    tg_send_message(chat_id, f"✅ Done! YouTube PRIVATE: {vid}\nWill go public at 09:00 IST")
                    processed.add(file_id)
                    if len(processed) > 1000:
                        processed = set(list(processed)[-500:])
                    state["offset"] = offset
                    state["processed"] = list(processed)
                    save_state(state)
                    commit_state()
                except Exception as e:
                    log(f"Error: {e}")
                    tg_send_message(chat_id, f"❌ Failed: {e}")
            
            if not updates["result"]:
                time.sleep(2)
        
        except KeyboardInterrupt:
            break
        except Exception as e:
            log(f"Loop error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()