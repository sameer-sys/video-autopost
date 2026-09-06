#!/usr/bin/env python3
"""
ToonPop Editor Bot (PM1 → sub-bot #3)
Auto post-processing for every video sent to @Toonpop_upload_bot.
Called from telegram_loop.py BEFORE upload:
  1. Validate: 0-45s duration, <20MB file, mp4
  2. Hook overlay: hook text burned into first 1.5s (ffmpeg drawtext)
  3. Thumbnail: brightest frame extracted as 1080x1920 jpg for Shorts picker
Returns (ready_path, thumb_path, report). Never raises — returns errors in report.

ENV: none (pure ffmpeg). HOOK_TEXT passed per-video from script/adder state.
"""
import json, os, subprocess, time

MAX_BYTES = 20 * 1024 * 1024
MIN_DUR, MAX_DUR = 0.5, 45.0


def log(m):
    print(time.strftime('%H:%M:%S'), m, flush=True)


def probe(path):
    r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries',
                        'format=duration,size', '-of', 'json', path],
                       capture_output=True, text=True, timeout=60)
    j = json.loads(r.stdout)
    f = j.get('format', {})
    return float(f.get('duration', 0) or 0), int(f.get('size', os.path.getsize(path)) or 0)


def validate(path):
    dur, size = probe(path)
    problems = []
    if not (MIN_DUR <= dur <= MAX_DUR):
        problems.append(f'duration {dur:.1f}s outside 0-45s')
    if size > MAX_BYTES:
        problems.append(f'size {size/1048576:.1f}MB over 20MB Telegram cap')
    return dur, size, problems


def add_hook(path, out, hook_text):
    """Burn hook text on first 1.5s. Falls back to copy if no font/hook."""
    if not hook_text:
        subprocess.run(['cp', path, out], check=True)
        return 'no-hook-text, copied as-is'
    safe = hook_text.replace("'", '').replace(':', ' ')[:80]
    cmd = ['ffmpeg', '-y', '-i', path, '-vf',
           f"drawtext=text='{safe}':fontsize=64:fontcolor=white:borderw=3:bordercolor=black:"
           f"x=(w-text_w)/2:y=h*0.12:enable='lt(t,1.5)'",
           '-c:a', 'copy', out, '-loglevel', 'error']
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        log('drawtext failed, copying as-is: ' + (r.stderr or '')[-150:])
        subprocess.run(['cp', path, out], check=True)
        return 'hook-overlay-failed, copied as-is'
    return 'hook-overlay-ok'


def make_thumbnail(path, out):
    """Grab a bright mid-video frame as Shorts thumbnail."""
    dur, _ = probe(path)
    ss = max(0.5, min(dur * 0.3, dur - 0.5))
    r = subprocess.run(['ffmpeg', '-y', '-ss', str(round(ss, 1)), '-i', path,
                        '-frames:v', '1', '-vf', 'scale=1080:1920', out,
                        '-loglevel', 'error'],
                       capture_output=True, text=True, timeout=120)
    return r.returncode == 0


def process(path, hook_text='', workdir='/tmp'):
    """Full pipeline. Returns dict with ready/thumbnail/report."""
    dur, size, problems = validate(path)
    rep = {'duration': round(dur, 1), 'size_mb': round(size / 1048576, 1),
           'problems': problems, 'hook': '', 'thumbnail': False}
    if problems:
        rep['ready'] = None
        return rep
    ready = os.path.join(workdir, 'edited.mp4')
    rep['hook'] = add_hook(path, ready, hook_text)
    thumb = os.path.join(workdir, 'thumb.jpg')
    rep['thumbnail'] = make_thumbnail(ready, thumb)
    rep['ready'] = ready
    rep['thumb_path'] = thumb if rep['thumbnail'] else None
    return rep


if __name__ == '__main__':
    import sys
    src = sys.argv[1]
    hook = sys.argv[2] if len(sys.argv) > 2 else ''
    print(json.dumps(process(src, hook), indent=2))
