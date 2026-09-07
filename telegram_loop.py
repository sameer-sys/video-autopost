#!/usr/bin/env python3
"""
Posting Bot with MTProto (Telethon) for 2GB downloads.
Downloads video → upscales → uploads to YT private → replies "✅ Done"
"""
import json, os, re, sys, subprocess, time, urllib.request, urllib.parse
from pathlib import Path

# ─── Config ───
BOT_TOKEN = os.environ.get("TELEGRAM_TOKEN")
API_ID = int(os.environ.get("TELEGRAM_API_ID", "36325364"))
API_HASH = os.environ.get("TELEGRAM_API_HASH", "5f03f8bfeddec2cf2c1b30c9692b54ff")
TELETHON_SESSION = os.environ.get("TELETHON_SESSION")
YT_CLIENT_ID = os.environ.get("YT_CLIENT_ID")
YT_CLIENT_SECRET = os.environ.get("YT_CLIENT_SECRET")
YT_REFRESH_TOKEN = os.environ.get("YT_REFRESH_TOKEN")
CHANNEL_ID = "UCx_eggTH3zOcuLDr2iYayoA"
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
    p = subprocess.run(["git", "config", "user.name", "github-actions"], capture_output=True)
    p = subprocess.run(["git", "config", "user.email", "github-actions@github.com"], capture_output=True)
    p = subprocess.run(["git", "add", STATE_FILE], capture_output=True)
    p = subprocess.run(["git", "commit", "-m", f"chore: update state {time.strftime('%Y-%m-%d %H:%M:%S')}"], capture_output=True)
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

def download_via_mtproto(file_id, dest_path):
    """Download file up to 2GB using Telethon user session."""
    from telethon.sync import TelegramClient
    from telethon.sessions import StringSession
    
    client = TelegramClient(StringSession(TELETHON_SESSION), API_ID, API_HASH)
    client.connect()
    
    if not client.is_user_authorized():
        raise Exception("Telethon session not authorized")
    
    # Get file info via Bot API first
    file_info = tg_get_file(file_id)
    if not file_info.get("ok"):
        raise Exception(f"getFile failed: {file_info}")
    
    file_path = file_info["result"]["file_path"]
    file_size = file_info["result"].get("file_size", 0)
    
    log(f"Downloading via MTProto: {file_size} bytes")
    
    # Download using Telethon
    client.download_media(file_id, dest_path)
    client.disconnect()
    return True

def download_via_bot_api(file_id, dest_path):
    """Fallback: Bot API (20MB limit)."""
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
    data = urllib.parse.urlencode({"client_id": YT_CLIENT_ID, "client_secret": YT_CLIENT_SECRET, "refresh_token": YT_REFRESH_TOKEN, "grant_type": "refresh_token"}).encode()
    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req) as r:
        return json.load(r)["access_token"]

def yt_upload_private(token, video_path, title, desc, tags):
    """Upload to YT as PRIVATE."""
    # Simple resumable upload - first create metadata
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = {
        "snippet": {"title": title, "description": desc, "tags": tags, "categoryId": "22"},
        "status": {"privacyStatus": "private", "selfDeclaredMadeForKids": False}
    }
    url = "https://www.googleapis.com/upload/youtube/v3/videos?part=snippet,status&uploadType=resumable"
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    with urllib.request.urlopen(req) as r:
        location = r.headers.get("Location")
        if not location:
            raise Exception("No upload URL")
    
    # Upload video file
    with open(video_path, "rb") as f:
        data = f.read()
    headers = {"Authorization": f"Bearer {token}", "Content-Length": str(len(data))}
    req = urllib.request.Request(location, data=data, headers=headers, method="PUT")
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.load(r)

def process_video(chat_id, file_id, caption):
    log(f"Processing video {file_id}")
    raw = f"raw_{file_id}.mp4"
    up = f"up_{file_id}.mp4"
    
    # Download via MTProto (2GB) or fallback to Bot API (20MB)
    try:
        download_via_mtproto(file_id, raw)
        log("Downloaded via MTProto (2GB)")
    except Exception as e:
        log(f"MTProto failed: {e}, trying Bot API...")
        if "20" in str(e) or "too big" in str(e).lower():
            raise Exception("File >20MB: Bot API limit. MTProto should handle this.")
        download_via_bot_api(file_id, raw)
        log("Downloaded via Bot API")
    
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
    if not TELETHON_SESSION:
        log("TELETHON_SESSION missing - run create_session.py locally and add to secrets")
        sys.exit(1)
    
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