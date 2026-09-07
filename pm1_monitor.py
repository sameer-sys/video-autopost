#!/usr/bin/env python3
"""PM1 Auto-monitor — runs in background, posts status every 5 minutes"""
import json, os, datetime, time

while True:
    try:
        state = json.load(open('state.json'))
        script_state = json.load(open('script_state.json'))
        videos = json.load(open('videos.json'))
        
        report = f"[PM1 Auto-Check] {datetime.datetime.now().strftime('%Y-%m-%d %H:%M UTC')}\n"
        report += f"last_compile: {state.get('last_compile', 'N/A')}\n"
        report += f"last_sent: {script_state.get('sent', [{}])[-1].get('date', 'N/A') if script_state.get('sent') else 'N/A'}\n"
        report += f"videos downloaded: {len(videos)}\n"
        report += f"adder_state: {'EXISTS' if os.path.exists('adder_state.json') else 'MISSING'}\n"
        report += f"trend_state: {'EXISTS' if os.path.exists('trend_state.json') else 'MISSING'}\n"
        
        # Print to stdout — manager chat can capture this
        print(report)
        
    except Exception as e:
        print(f"[PM1 Auto-Check ERROR] {e}")
    
    time.sleep(300)  # 5 minutes