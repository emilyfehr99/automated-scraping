import httpx
import re
from bs4 import BeautifulSoup
import urllib.parse

def scrape_bing_image(player_name):
    query = urllib.parse.quote(f"{player_name} ice hockey action")
    url = f"https://www.bing.com/images/search?q={query}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    r = httpx.get(url, headers=headers)
    soup = BeautifulSoup(r.text, 'html.parser')
    
    # Bing stores image data in the 'm' attribute of 'a' tags with class 'iusc'
    a_tags = soup.find_all('a', class_='iusc')
    for a in a_tags:
        m = a.get('m')
        if m:
            import json
            try:
                data = json.loads(m)
                murl = data.get('murl')
                if murl and murl.endswith(('.jpg', '.png', '.jpeg')):
                    return murl
            except:
                pass
    return None

print("Ivar Stenberg:", scrape_bing_image("Ivar Stenberg"))
print("Michael Misa:", scrape_bing_image("Michael Misa"))
