import asyncio
from playwright.async_api import async_playwright
import os

async def main():
    os.makedirs("./browser_profiles/twitter", exist_ok=True)
    async with async_playwright() as p:
        print("Opening browser for Twitter login...")
        
        # Opens a visible browser linked to the persistent profile folder
        context = await p.chromium.launch_persistent_context(
            user_data_dir="./browser_profiles/twitter",
            headless=False,
            viewport={"width": 1280, "height": 900},
        )
        
        page = await context.new_page()
        await page.goto("https://x.com/login")
        
        print("===============================================================")
        print("Browser is open! Please manually log in to X with the details.")
        print("Once you are logged in and see the feed, simply CLOSE THE BROWSER WINDOW.")
        print("===============================================================")
        
        # Keep the script running until the user closes the browser window themselves
        try:
            await page.wait_for_event("close", timeout=0)
        except Exception:
            pass
            
        print("Browser closed. Session successfully saved to browser_profiles/twitter!")

if __name__ == "__main__":
    asyncio.run(main())
