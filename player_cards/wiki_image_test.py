import httpx
import sys
import urllib.parse
import json
import logging

logging.basicConfig(level=logging.INFO)

HEADERS = {
    "User-Agent": "Antigravity/1.0 (https://github.com/Google/Antigravity; emilyfehr8@example.com) httpx/0.24"
}

def get_wiki_image(player_name):
    query = urllib.parse.quote(player_name + " ice hockey")
    url = f"https://en.wikipedia.org/w/api.php?action=query&generator=search&gsrsearch={query}&gsrlimit=1&prop=pageimages&piprop=original&format=json"
    try:
        r = httpx.get(url, headers=HEADERS, timeout=10.0, follow_redirects=True)
        data = r.json()
        pages = data.get("query", {}).get("pages", {})
        if not pages:
            return None
        page = list(pages.values())[0]
        # check if page title matches player name roughly
        title = page.get("title", "")
        if player_name.lower() not in title.lower():
            # Not the right player
            return None
        return page.get("original", {}).get("source")
    except Exception as e:
        print(f"Error for {player_name}: {e}")
        return None

if __name__ == "__main__":
    from player_cards.draft_source import fetch_draft_picks
    picks = fetch_draft_picks(2026)
    r1 = sorted([p for p in picks if p.get("round") == 1], key=lambda p: p.get("overallPick", 99))
    
    overrides = {}
    for pick in r1:
        first = pick.get("firstName", {}).get("default", "")
        last = pick.get("lastName", {}).get("default", "")
        fullname = f"{first} {last}".strip()
        img = get_wiki_image(fullname)
        if img:
            overrides[fullname.lower()] = img
            print(f"Found for {fullname}: {img}")
        else:
            print(f"NOT found for {fullname}")
    
    print("\n\nPROSPECT_HEADSHOT_OVERRIDES = {")
    for name, img in overrides.items():
        print(f'    "{name}": "{img}",')
    print("}")
