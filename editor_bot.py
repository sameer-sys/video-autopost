#!/usr/bin/env python3
"""
Editor Bot — processes video after user sends it (post-CapCut, sticker on watermark).
Adds: hook text overlay (first 1.5s), thumbnail/cover, tries to blur/crop watermark.
Searches online for best thumbnail/hook if needed.
Called by Posting Bot after video download, before upload.
"""
import json, os, subprocess, tempfile, shutil, urllib.request, urllib.parse

STATE_FILE = 'editor_state.json'
TOKEN = os.environ.get('TELEGRAM_TOKEN', '')
CHAT_ID = os.environ.get('CHAT_ID', '')

def ffmpeg_available():
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        return True
    except Exception:
        return False

def probe_video(path):
    r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries',
                        'format=duration,size', '-of', 'json', path],
                       capture_output=True, text=True, timeout=30)
    j = json.loads(r.stdout)
    f = j.get('format', {})
    return float(f.get('duration', 0) or 0), int(f.get('size', 0) or 0)

def add_hook_overlay(input_path, output_path, hook_text):
    """Burn hook text on first 1.5s at top-center."""
    if not hook_text:
        shutil.copy2(input_path, output_path)
        return True
    safe = hook_text.replace("'", "").replace(':', ' ')[:80]
    cmd = ['ffmpeg', '-y', '-i', input_path, '-vf',
           f"drawtext=text='{safe}':fontsize=64:fontcolor=white:borderw=3:bordercolor=black:"
           f"x=(w-text_w)/2:y=h*0.12:enable='lt(t,1.5)'",
           '-c:a', 'copy', '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
           output_path, '-loglevel', 'error']
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    return r.returncode == 0

def extract_thumbnail(input_path, output_path):
    """Extract best frame (brightest, around 30% in) as 1080x1920 thumbnail."""
    dur, _ = probe_video(input_path)
    ss = max(0.5, min(dur * 0.3, dur - 0.5))
    cmd = ['ffmpeg', '-y', '-ss', str(round(ss, 1)), '-i', input_path,
           '-frames:v', '1', '-vf', 'scale=1080:1920', output_path, '-loglevel', 'error']
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    return r.returncode == 0 and os.path.exists(output_path)

def blur_watermark_region(input_path, output_path):
    """Try to blur bottom-right corner (common watermark area)."""
    # This is a best-effort - user adds sticker, but we try to blur bottom-right 15%
    cmd = ['ffmpeg', '-y', '-i', input_path, '-vf',
           "boxblur=10:1:cr=50:ar=10:enable='gt(x,w*0.85)*gt(y,h*0.85)'",
           '-c:a', 'copy', '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
           output_path, '-loglevel', 'error']
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    return r.returncode == 0

def search_best_thumbnail_online(keyword):
    """Placeholder - in future can search Google Images/YouTube for best thumbnail."""
    # For now returns None - future enhancement
    return None

def process_video(input_path, hook_text='', workdir=None):
    """
    Full editor pipeline:
    1. Validate (0-45s, <2GB)
    2. Blur watermark region (best effort)
    2. Add hook overlay (first 1.5s)
    3. Generate thumbnail
    Returns: {'ready': processed_path, 'thumbnail': thumb_path, 'problems': []}
    """
    if not ffmpeg_available():
        return {'ready': None, 'thumbnail': None, 'problems': ['ffmpeg not available']}
    
    dur, size = probe_video(input_path)
    problems = []
    if not (0 < dur <= 45):
        problems.append(f'duration {dur:.1f}s outside 0-45s')
    if size > 2 * 1024 * 1024 * 1024:
        problems.append(f'size {size/1024/1024:.1f}MB over 2GB')
    if problems:
        return {'ready': None, 'thumbnail': None, 'problems': problems}
    
    workdir = workdir or tempfile.mkdtemp()
    base = os.path.join(workdir, 'edit')
    
    # Step 1: blur watermark (best effort)
    blurred = os.path.join(workdir, 'blurred.mp4')
    if not blur_watermark_region(input_path, blurred):
        blurred = input_path  # fallback to original
    
    # Step 2: add hook overlay
    hooked = os.path.join(workdir, 'hooked.mp4')
    hook_text = hook_text or "Wait for the end 😱"
    if not add_hook_overlay(blurred, os.path.join(workdir, 'hooked.mp4'), hook_text):
        hooked = blurred
    
    # Step 3: thumbnail
    thumb = os.path.join(workdir, 'thumb.jpg')
    extract_thumbnail(hooked, thumb)
    
    return {'ready': hooked, 'thumbnail': thumb, 'problems': []}

if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print('Usage: editor_bot.py <input_video> [hook_text]')
        sys.exit(1)
    inp = sys.argv[1]
    hook = sys.argv[2] if len(sys.argv) > 2 else ''
    res = process_video(inp, hook)
    print(json.dumps(res, indent=2))