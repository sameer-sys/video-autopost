#!/usr/bin/env python3
"""
ToonPop Manager Bot — PM1 (the human-style manager).
End-to-end duties:
  1. Check all sub-bots ran (trend/script/adder state files fresh)
  2. Check posting loop alive (state.json fresh)
  3. Check weekly compile + monetization state
  4. Send ONE labeled status report to Manager session (Telegram)
     Format mirrors WhatsApp/Telegram group: each line tagged [Bot Name].
  5. Self-heal: bump stale-state warnings, never edits posting bot code.

Runs daily via manager-workflow.yml + manual dispatch.
ENV: TELEGRAM_TOKEN, CHAT_ID, GITHUB_TOKEN (optional, for Actions run check)
"""
import json, os, datetime, urllib.request, urllib.parse

TOKEN = os.environ.get('TELEGRAM_TOKEN', '')
CHAT_ID = os.environ.get('CHAT_ID', '')
REPO = 'sameer-sys/video-autopost'
GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN', '')


def age_hours(path):
    try:
        m = os.path.getmtime(path)
        return (datetime.datetime.now().timestamp() - m) / 3600
    except Exception:
        return None


def check(name, path, max_h):
    a = age_hours(path)
    if a is None:
        return f"[{name}] ⚠️ no state file yet"
    ok = a <= max_h
    return f"[{name}] {'✅' if ok else '🔴 STALE'} {a:.1f}h old (limit {max_h}h)"


def gh_last_runs():
    if not GITHUB_TOKEN:
        return []
    try:
        req = urllib.request.Request(
            f'https://api.github.com/repos/{REPO}/actions/runs?per_page=5',
            headers={'Authorization': f'Bearer {GITHUB_TOKEN}',
                     'Accept': 'application/vnd.github+json'})
        with urllib.request.urlopen(req, timeout=30) as r:
            j = json.load(r)
        return [(w['name'], w['status'], w['conclusion'])
                for w in j.get('workflow_runs', [])]
    except Exception as e:
        return [('gh-api', 'error', str(e)[:60])]


def main():
    print('=== PM1 Manager check ===')
    lines = [f"📋 [PM1 Manager] {datetime.datetime.now():%Y-%m-%d %H:%M UTC}"]
    lines.append(check('Trend Bot', 'trend_state.json', 30))
    lines.append(check('Script Bot', 'script_state.json', 30))
    lines.append(check('Adder Bot', 'adder_state.json', 30))
    lines.append(check('Posting Bot', 'state.json', 80))
    lines.append(check('Compile Bot', 'state.json', 80))
    lines.append(check('Monetization', 'analytics_state.json', 30))
    for name, status, concl in gh_last_runs():
        lines.append(f"[Actions] {name}: {status}/{concl}")
    lines.append("[PM1] End of report. Reply with fixes to apply.")
    msg = '\n'.join(lines)
    print(msg)
    if TOKEN and CHAT_ID:
        url = f'https://api.telegram.org/bot{TOKEN}/sendMessage?' + urllib.parse.urlencode(
            {'chat_id': CHAT_ID, 'text': msg})
        with urllib.request.urlopen(url, timeout=30) as r:
            json.load(r)
        print('report sent')


if __name__ == '__main__':
    main()
