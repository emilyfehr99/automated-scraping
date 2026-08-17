import asyncio
from playwright.async_api import async_playwright
import urllib.parse
import json

async def search_image(player_name):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        query = urllib.parse.quote(f"{player_name} ice hockey action high resolution")
        url = f"https://duckduckgo.com/?q={query}&t=h_&iar=images&iax=images&ia=images"
        
        print(f"Navigating to: {url}")
        await page.goto(url)
        
        # Wait for image results to load
        try:
            await page.wait_for_selector('img.tile--img__img', timeout=10000)
            
            # Find the first image result that has a source
            img_src = await page.evaluate('''() => {
                let imgs = document.querySelectorAll('img.tile--img__img');
                for (let img of imgs) {
                    if (img.src && img.src.startsWith('http')) {
                        // In DDG, the actual full-res image URL is sometimes in the a.js-zci-link
                        let parent = img.closest('.tile--img');
                        if (parent) {
                            let a = parent.querySelector('a');
                            if (a) {
                                let urlStr = a.href;
                                // parse the 'uddg' parameter which contains the real image URL
                                let urlParams = new URLSearchParams(urlStr.split('?')[1]);
                                if (urlParams.has('uddg')) {
                                    return decodeURIComponent(urlParams.get('uddg'));
                                }
                            }
                        }
                        return img.src;
                    }
                }
                return null;
            }''')
            
            print(f"Result for {player_name}: {img_src}")
        except Exception as e:
            print(f"Failed to find image for {player_name}: {e}")
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(search_image("Ivar Stenberg"))
