#!/usr/bin/env python3
"""
Smart Manager Bot — monitors all bots, finds new platform tricks, 
auto-updates bots, reports to Manager session.
Runs every 6h + 12h audit.
"""
import json, os, subprocess, time, datetime, urllib.request, urllib.parse

TOKEN = os.environ.get('TELEGRAM_TOKEN', '')
CHAT_ID = os.environ.get('CHAT_ID', '')
GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN', '')

STATE_FILES = {
    'trend': 'trend_state.json',
    'script': 'script_state.json',
    'editor': 'editor_state.json',
    'adder': 'adder_state.json',
    'posting': 'state.json',
    'monetization': 'analytics_state.json',
    'flip': 'yt_flip_state.json',
}

def log(msg):
    print(time.strftime('%H:%M:%S'), msg, flush=True)

def tg_send(text):
    if not (TOKEN and CHAT_ID):
        return False
    url = f'https://api.telegram.org/bot{TOKEN}/sendMessage?' + urllib.parse.urlencode(
        {'chat_id': CHAT_ID, 'text': text})
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            json.load(r)
        return True
    except Exception as e:
        log(f'tg_send failed: {e}')
        return False

def check_file_age(path, max_hours):
    try:
        mtime = os.path.getmtime(path)
        age_h = (time.time() - mtime) / 3600
        return age_h <= max_hours, round(age_h, 1)
    except Exception:
        return False, None

def check_all_bots():
    """Check all bot state files for freshness."""
    results = {}
    max_ages = {
        'trend': 30,
        'script': 30,
        'editor': 30,
        'adder': 30,
        'posting': 80,
        'monetization': 30,
        'flip': 30,
    }
    for name, path in STATE_FILES.items():
        fresh, age = check_file_age(path, max_ages.get(name, 30))
        results[name] = {
            'fresh': fresh,
            'age_h': age,
            'limit': max_ages.get(name, 30),
            'exists': os.path.exists(path)
        }
    return results

def check_actions_runs():
    """Check GitHub Actions runs status."""
    if not GITHUB_TOKEN:
        return []
    try:
        req = urllib.request.Request(
            'https://api.github.com/repos/sameer-sys/video-autopost/actions/runs?per_page=10',
            headers={'Authorization': f'Bearer {GITHUB_TOKEN}',
                     'Accept': 'application/vnd.github+json'})
        with urllib.request.urlopen(req, timeout=30) as r:
            j = json.load(r)
        runs = []
        for w in j.get('workflow_runs', []):
            runs.append({
                'name': w['name'],
                'status': w['status'],
                'conclusion': w['conclusion'],
                'created_at': w['created_at'],
                'head_sha': w['head_sha'][:7]
            })
        return runs
    except Exception as e:
        log(f'check_actions_runs failed: {e}')
        return []

def search_new_tricks():
    """Search for new platform tricks (placeholder for future web search)."""
    # TODO: Integrate web search for new platform tricks
    # For now, return known tricks
    return {
        'youtube': [
            'Upload private at night → public 09:00 IST',
            'First 3 seconds: hook text overlay',
            'Loop ending (last frame = first frame)',
            'Shorts thumbnail: pick 30% frame',
        ],
        'instagram': [
            'Trending audio at vol=1%',
            'Caption: keywords first line',
            '5-8 hashtags max',
            'Cover: pick bright frame',
        ],
        'facebook': [
            'Cross-post same day as YT/IG',
            'Share-style text',
            '3-5 hashtags',
        ]
    }

def check_monetization_gaps():
    """Check monetization progress from analytics."""
    try:
        if os.path.exists('analytics_state.json'):
            data = json.load(open('analytics_state.json'))
            checks = data.get('checks', [])
            if checks:
                latest = checks[-1]
                yt = latest.get('your_channels', {}).get('youtube', {})
                subs = yt.get('subscribers', 0)
                views = yt.get('total_views', 0)
                return {
                    'subs': subs,
                    'views': views,
                    'subs_needed': max(0, 1000 - subs),
                    'views_needed': max(0, 10_000_000 - views)
                }
    except Exception:
        pass
    return {}

def check_new_platform_tricks():
    """Check for new platform tricks (placeholder for web search)."""
    # TODO: Integrate web search for new tricks
    # For now, return current known tricks
    return {
        'new_tricks': [],
        'last_checked': datetime.datetime.now().isoformat()
    }

def search_web_for_tricks(platform):
    """Search web for new platform tricks (placeholder)."""
    # TODO: Integrate with web search API
    # For now, return static known tricks
    tricks = {
        'youtube': [
            'Loop ending (last frame = first frame) increases retention',
            'Hook in first 0.5 seconds critical',
            'Shorts thumbnail: pick frame at 30%',
        ],
        'instagram': [
            'Trending audio at volume 1% for algorithm boost',
            'Keywords in first line of caption',
            '5-8 hashtags optimal',
        ],
        'facebook': [
            'Cross-post same day as YT/IG',
            'Share-style caption text',
            '3-5 hashtags',
        ]
    }
    return tricks.get(platform, [])

def apply_new_trick_to_bot(trick, platform):
    """Apply new trick to relevant bot (placeholder for auto-update)."""
    # TODO: Implement auto-update of bot code
    # For now, log and report
    log(f"New trick found for {platform}: {trick}")
    return False

def main():
    log('=== Smart Manager Bot starting ===')
    
    # 1. Check all bot states
    bot_status = check_all_bots()
    
    # 2. Check GitHub Actions
    runs = check_actions_runs()
    
    # 3. Check monetization
    monetization = check_monetization_gaps()
    
    # 4. Search for new platform tricks
    new_tricks = search_web_for_tricks('youtube')
    new_tricks += search_web_for_tricks('instagram')
    new_tricks += search_web_for_tricks('facebook')
    
    # 5. Check for new platform tricks
    new_tricks_found = check_new_platform_tricks()
    
    # 5. Monetization check
    monetization = check_monetization_gaps()
    
    # Build report
    lines = [f"🤖 [Smart Manager] {datetime.datetime.now():%Y-%m-%d %H:%M UTC}"]
    lines.append("")
    lines.append("📊 **Bot Health:**")
    for name, status in bot_status.items():
        icon = "✅" if status['fresh'] else "🔴"
        age_str = f"{status['age_h']}h" if status['age_h'] else "N/A"
        lines.append(f"  {icon} {name.title()}: {age_str} (limit {status['limit']}h)")
    
    lines.append("")
    lines.append("🚀 **GitHub Actions:**")
    for r in runs[:5]:
        icon = "✅" if r['conclusion'] == 'success' else "⚠️" if r['conclusion'] == 'failure' else "🔄"
        lines.append(f"  {icon} {r['name']}: {r['status']}/{r['conclusion']} ({r['head_sha']})")
    
    if monetization:
        lines.append("")
        lines.append("💰 **Monetization:**")
        lines.append(f"  Subs: {monetization.get('subs', 0)} (need {monetization.get('subs_needed', 0)} more)")
        lines.append(f"  Views: {monetization.get('views', 0)} (need {monetization.get('views_needed', 0)} more)")
    
    lines.append("")
    lines.append("🔍 **New Tricks Check:**")
    for platform in ['youtube', 'instagram', 'facebook']:
        tricks = search_web_for_tricks(platform)
        if tricks:
            lines.append(f"  {platform.title()}: {len(tricks)} known tricks")
    
    lines.append("")
    lines.append("[Smart Manager] End of report. Reply with fixes to apply.")
    
    msg = '\n'.join(lines)
    log(msg)
    tg_send(msg)
    print('Done.')

if __name__ == '__main__':
    import datetime
    main()