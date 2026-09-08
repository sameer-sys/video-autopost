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
FB_PAGE_ID = os.environ.get("FB_PAGE_ID")
FB_PAGE_TOKEN = os.environ.get("FB_PAGE_TOKEN")
IG_USER_ID = os.environ.get("IG_USER_ID")
IG_TOKEN = os.environ.get("IG_TOKEN")
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

def fb_upload_video(token, video_path, caption):
    """Upload video to Facebook Page as Reel."""
    if not os.path.isfile(video_path):
        raise FileNotFoundError(f"Video file not found: {video_path}")
    
    file_size = os.path.getsize(video_path)
    
    # Step 1: Start upload session
    start_url = f"https://graph.facebook.com/v19.0/{FB_PAGE_ID}/video_reels"
    start_data = {
        "access_token": token,
        "upload_phase": "start",
        "file_size": file_size,
    }
    start_resp = requests.post(start_url, data=start_data, timeout=30)
    if start_resp.status_code != 200:
        raise RuntimeError(f"FB start upload failed: HTTP {start_resp.status_code} - {start_resp.text}")
    
    start_json = start_resp.json()
    video_id = start_json.get("video_id")
    upload_url = start_json.get("upload_url")
    
    if not video_id or not upload_url:
        raise RuntimeError(f"FB start failed: {start_resp.text}")
    
    # Step 2: Transfer video
    with open(video_path, "rb") as f:
        transfer_resp = requests.post(upload_url, data=f, headers={"Content-Type": "video/mp4"}, timeout=600)
    if transfer_resp.status_code != 200:
        raise RuntimeError(f"FB transfer failed: HTTP {transfer_resp.status_code} - {transfer_resp.text}")
    
    # Step 3: Finish with caption
    finish_url = f"https://graph.facebook.com/v19.0/{FB_PAGE_ID}/video_reels"
    finish_data = {
        "access_token": token,
        "upload_phase": "finish",
        "video_id": video_id,
        "description": caption[:1000] if caption else "ToonPop Short #Shorts",
    }
    finish_resp = requests.post(finish_url, data=finish_data, timeout=30)
    if finish_resp.status_code != 200:
        raise RuntimeError(f"FB finish failed: HTTP {finish_resp.status_code} - {finish_resp.text}")
    
    return video_id

def ig_upload_video(token, video_path, caption):
    """Upload video to Instagram as Reel using media container."""
    if not os.path.isfile(video_path):
        raise FileNotFoundError(f"Video file not found: {video_path}")
    
    # For IG Reels, we create a media container with the video URL
    # Since we don't have a public URL, we need to upload the video first
    # For simplicity, we'll use the media container approach with a temporary file URL
    # But IG requires the video to be accessible via URL
    # For now, we'll use a workaround: upload to FB first, then cross-post
    # Or use the media publish endpoint
    
    # Step 1: Create container with video
    # For IG Reels, we need to upload the video to a reachable location first
    # Since we don't have hosting, we'll use the same video file
    # The IG API requires a publicly accessible video URL
    
    # For now, we'll use the same approach as FB but with IG endpoint
    # This requires the video to be publicly accessible
    # We'll need to host the video somewhere first
    
    # For now, let's just use the media container creation with a placeholder
    # In production, you'd need to host the video file publicly
    
    raise NotImplementedError("IG upload requires public video URL - needs hosting solution")

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
    
    results = {}
    
    # Upload to Facebook
    if FB_PAGE_TOKEN and FB_PAGE_ID:
        try:
            fb_id = fb_upload_video(FB_PAGE_TOKEN, up, caption)
            results["fb"] = fb_id
            log(f"Uploaded to FB: {fb_id}")
        except Exception as e:
            log(f"FB upload failed: {e}")
            results["fb_error"] = str(e)
    
    # Upload to Instagram
    if IG_TOKEN and IG_USER_ID:
        try:
            ig_id = ig_upload_video(IG_TOKEN, up, caption)
            results["ig"] = ig_id
            log(f"Uploaded to IG: {ig_id}")
        except Exception as e:
            log(f"IG upload failed: {e}")
            results["ig_error"] = str(e)
    
    # Cleanup
    for f in [raw, up]:
        try: os.remove(f)
        except: pass
    
    return results

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
                    results = process_video(chat_id, file_id, caption)
                    msg_parts = ["✅ Done!"]
                    if results.get("fb"):
                        msg_parts.append(f"FB: {results['fb']}")
                    if results.get("ig"):
                        msg_parts.append(f"IG: {results['ig']}")
                    if results.get("fb_error"):
                        msg_parts.append(f"FB Error: {results['fb_error']}")
                    if results.get("ig_error"):
                        msg_parts.append(f"IG Error: {results['ig_error']}")
                    tg_send_message(chat_id, "\n".join(msg_parts))
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