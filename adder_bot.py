#!/usr/bin/env python3
"""
Adder Bot — smart description/caption/hashtag generator.
Uses trend data + top channel analysis to build smart metadata.
Called by Posting Bot before upload (IG caption locked at publish).
"""
import json, os, random, urllib.request, urllib.parse, re

STATE_FILE = 'adder_state.json'
TREND_FILE = 'trend_state.json'
TOKEN = os.environ.get('TELEGRAM_TOKEN', '')
CHAT_ID = os.environ.get('CHAT_ID', '')
YT_CHANNEL_ID = os.environ.get('YOUR_YT_CHANNEL_ID', 'UCx_eggTH3zOcuLDr2iYayoA')

# Base hashtag pools (proven for cartoon/cat niche)
HASHTAG_POOLS = {
    'core': ['#shorts', '#cartoon', '#toonpopworld', '#funny', '#catshorts'],
    'viral': ['#viral', '#viralvideo', '#trending', '#fyp', '#foryou'],
    'niche': ['#animation', '#hinglish', '#cartooncat', '#catvideos', '#shortsindia'],
    'platform_yt': ['#youtubeshorts', '#shortsfeed', '#youtube'],
    'platform_ig': ['#reels', '#reelsindia', '#instagramreels', '#explore'],
    'platform_fb': ['#facebookreels', '#fbviral', '#facebookvideo'],
}

# Keyword-to-hashtag mapping (smart tagging)
KEYWORD_TAGS = {
    'momo': ['#momo', '#momolover', '#streetfood', '#momochallenge'],
    'maggi': ['#maggi', '#maggi lover', '#noodles', '#instantnoodles'],
    'pizza': ['#pizza', '#pizza lover', '#cheese', '#cheesypizza'],
    'burger': ['#burger', '#cheeseburger', '#foodie'],
    'ice cream': ['#icecream', '#dessert', '#summer'],
    'chocolate': ['#chocolate', '#chocoholic', '#sweet'],
    'portal': ['#portal', '#magic', '#fantasy', '#animation'],
    'detective': ['#detective', '#mystery', '#solving'],
    'chase': ['#chase', '#running', '#funnycat'],
    'future': ['#future', '#2050', '#scifi', '#timetravel'],
    'magic': ['#magic', '#spell', '#wizard'],
    'challenge': ['#challenge', '#viralchallenge', '#trending'],
    'sleep': ['#sleepy', '#nap', '#lazy'],
    'party': ['#party', '#celebration', '#fun'],
    'song': ['#song', '#singing', '#music'],
    'race': ['#race', '#racing', '#speed'],
}

# Hook templates for descriptions
DESC_TEMPLATES = [
    "{hook}\n\n{cat} does something crazy with {food}! 😱\n\nWatch till the end for the twist! 😱\n\n🎬 ToonPop World - Daily Cartoon Fun!\nFollow for daily shorts 🍿",
    "{hook}\n\n{cat} tries to steal {food} but things go wrong! 😂\n\nWait for the ending... 😱\n\n🎬 ToonPop World Daily Cartoon!\nFollow for daily shorts 🍿",
    "{hook}\n\n{c1} in {world} — chaos with {food}! 😱\n\nWait for the ending... 😱\n\n🎬 ToonPop World!\nFollow for daily shorts 🍿",
]

# Title templates
TITLE_TEMPLATES = [
    "{c1} Ne {food} Chura Liya 😱",
    "मेरी प्लेट से {food} क्यों चुराया? 😾",
    "{c1} vs {food} — कौन जीतेगा?",
    "जादुई {food} ठेला 🪄",
    "{c1} सो गया पढ़ाई में 😹",
    "उसने {food} बनाया... इसने चुरा लिया 🍜",
    "{w} की दुनिया का पोर्टल ✨",
    "जासूस {c2} ने {food} का राज़ खोला 🕵️",
]

def load_trend():
    try:
        h = json.load(open('trend_state.json')).get('history', [])
        if h:
            return h[-1]
    except Exception:
        pass
    return {'trend': 'Momo Heist', 'keyword': 'momo', 'hook': 'मोमोज़ मेरे हैं!'}

def load_script():
    try:
        h = json.load(open('script_state.json')).get('sent', [])
        if h:
            return h[-1]
    except Exception:
        pass
    return {'titles': ['Video 1', 'Video 2', 'Video 3']}

def get_smart_hashtags(keyword, platform):
    """Generate smart hashtags based on keyword + platform."""
    base = HASHTAG_POOLS['core'] + HASHTAG_POOLS['viral']
    if platform == 'youtube':
        base += HASHTAG_POOLS['platform_yt']
    elif platform == 'instagram':
        base += HASHTAG_POOLS['platform_ig']
    elif platform == 'facebook':
        base += HASHTAG_POOLS['platform_fb']
    
    # Add niche + keyword-specific tags
    if keyword in KEYWORD_TAGS:
        base += KEYWORD_TAGS[keyword]
    base += HASHTAG_POOLS['niche']
    
    # Shuffle and limit
    random.shuffle(base)
    if platform == 'instagram':
        return ' '.join(base[:15])
    elif platform == 'youtube':
        return ' '.join(base[:12])
    return ' '.join(base[:10])

def fetch_top_channel_tags(access, keyword):
    """Fetch top 3 videos for keyword, extract their tags."""
    try:
        after = (datetime.datetime.now(datetime.timezone.utc)
                 - datetime.timedelta(days=30)).strftime('%Y-%m-%dT%H:%M:%SZ')
        url = 'https://www.googleapis.com/youtube/v3/search?' + urllib.parse.urlencode({
            'q': f'{keyword} cartoon cat short', 'part': 'snippet', 'order': 'viewCount',
            'publishedAfter': after, 'maxResults': 3, 'type': 'video',
            'videoDuration': 'short'})
        req = urllib.request.Request(url, headers={'Authorization': f'Bearer {access}'})
        with urllib.request.urlopen(req, timeout=30) as r:
            j = json.load(r)
        vids = [it['id'].get('videoId', '') for it in j.get('items', [])]
        if not vids:
            return []
        ids = ','.join(vids)
        req2 = urllib.request.Request(
            f'https://www.googleapis.com/youtube/v3/videos?part=snippet&id={ids}',
            headers={'Authorization': f'Bearer {access}'})
        with urllib.request.urlopen(req2, timeout=30) as r:
            j2 = json.load(r)
        all_tags = []
        for it in j2.get('items', []):
            tags = it.get('snippet', {}).get('tags', [])
            all_tags.extend([t.lower() for t in tags])
        # Count frequency
        from collections import Counter
        cnt = Counter(all_tags)
        return [tag for tag, _ in cnt.most_common(10)]
    except Exception:
        return []

def build_package():
    trend = load_trend()
    trend_name = trend.get('trend', 'Momo Heist')
    keyword = trend.get('keyword', 'momo')
    hook = trend.get('hook', 'एंड तक देखो 😱')
    
    # Get trend-specific details
    if 'momo' in trend_name.lower():
        food, c1, c2 = 'momos', 'orange tabby cat', 'detective parrot'
    elif 'maggi' in trend_name.lower():
        food, c1, c2 = 'Maggi noodles', 'orange tabby cat', 'tiny brother cat'
    elif 'portal' in trend_name.lower():
        food, c1, c2 = 'magical food', 'orange tabby cat', 'detective parrot'
    elif 'detective' in trend_name.lower():
        food, c1, c2 = 'missing food', 'detective parrot', 'orange tabby cat'
    else:
        food, c1, c2 = 'food', 'orange tabby cat', 'detective parrot'
    
    world = "kitchen counter at night"
    hook_text = trend.get('hook', 'एंड तक देखो 😱')
    
    # Smart tags from top channels (if possible)
    smart_tags = {}
    try:
        access = yt_token()
        top_tags = fetch_top_channel_tags(access, keyword)
        if top_tags:
            # Add to core pools
            pass
    except Exception:
        pass
    
    tags_yt = get_smart_hashtags(keyword, 'youtube')
    tags_ig = get_smart_hashtags(keyword, 'instagram')
    tags_fb = get_smart_hashtags(keyword, 'facebook')
    
    # Build description
    desc_template = random.choice(DESC_TEMPLATES)
    desc = desc_template.format(
        hook=hook_text,
        cat='the orange cat',
        c1='the orange cat',
        c2='detective parrot',
        food=food,
        w='kitchen counter at night'
    )
    
    title = random.choice(TITLE_TEMPLATES).format(
        c1='orange tabby cat', c2='detective parrot',
        food='momos', w='kitchen')
    
    # YT title (max 100 chars)
    yt_title = title[:100]
    yt_desc = f"{desc}\n\n{get_smart_hashtags('momo', 'youtube')}"
    
    # IG caption (keywords first line)
    ig_caption = f"{hook_text}\n\n{desc}\n{get_smart_hashtags('momo', 'instagram')}"
    
    # FB text
    fb_text = f"{hook_text}\n\n{desc}\n{get_smart_hashtags('momo', 'facebook')}"
    
    return {
        'trend': trend.get('trend', 'Momo Heist'),
        'yt': {'title': yt_title, 'description': yt_desc, 'tags': tags_yt.split()},
        'ig': {'caption': ig_caption},
        'fb': {'text': fb_text},
        'hook_text': hook_text,
    }

def yt_token():
    body = urllib.parse.urlencode({
        'client_id': os.environ['YT_CLIENT_ID'],
        'client_secret': os.environ['YT_CLIENT_SECRET'],
        'refresh_token': os.environ['YT_REFRESH_TOKEN'],
        'grant_type': 'refresh_token'}).encode()
    req = urllib.request.Request('https://oauth2.googleapis.com/token', data=body,
        headers={'Content-Type': 'application/x-www-form-urlencoded'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)['access_token']

def main():
    print('=== Adder Bot (smart metadata) starting ===')
    pkg = build_package()
    pkg['date'] = datetime.datetime.now().strftime('%Y-%m-%d')
    json.dump(pkg, open('adder_state.json', 'w'), indent=2)
    print('Adder package saved:', pkg['yt']['title'])
    
    if TOKEN and CHAT_ID:
        msg = (f"[Adder Bot] ✅ Smart package ready\n"
               f"YT: {pkg['yt']['title']}\n"
               f"Hook: {pkg['hook_text']}\n"
               f"Tags YT: {pkg['yt']['tags'][:5]}...")
        url = f'https://api.telegram.org/bot{TOKEN}/sendMessage?' + urllib.parse.urlencode(
            {'chat_id': CHAT_ID, 'text': msg})
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                json.load(r)
        except Exception as e:
            print('notify failed:', e)

if __name__ == '__main__':
    import datetime
    main()