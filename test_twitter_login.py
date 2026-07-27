import asyncio
from playwright.async_api import async_playwright
import os
import pyotp

async def login_with_ui():
    os.makedirs("./browser_profiles/twitter", exist_ok=True)
    async with async_playwright() as p:
        print("Launching browser...")
        context = await p.chromium.launch_persistent_context(
            user_data_dir="./browser_profiles/twitter",
            headless=True,
            viewport={"width": 1280, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = await context.new_page()
        
        print("Navigating to x.com/login...")
        await page.goto("https://x.com/login")
        await page.wait_for_timeout(3000)
        
        # Check if already logged in
        if "login" not in page.url and "i/flow/login" not in page.url:
            print(f"Already logged in! Current URL: {page.url}")
            await context.close()
            return
            
        print("Entering username...")
        await page.wait_for_selector('input[autocomplete="username"]')
        await page.fill('input[autocomplete="username"]', 'SATO31130317')
        await page.keyboard.press('Enter')
        
        await page.wait_for_timeout(2000)
        
        print("Entering password...")
        # Sometimes Twitter asks for email or phone number instead of password first
        try:
            password_input = await page.wait_for_selector('input[name="password"]', timeout=3000)
        except Exception:
            # Maybe it asked for email or phone number?
            print("Password field not found, maybe asked for email to verify?")
            try:
                email_input = await page.wait_for_selector('input[data-testid="ocfEnterTextTextInput"]', timeout=3000)
                await email_input.fill('alide1997@gmx.com')
                await page.keyboard.press('Enter')
                await page.wait_for_timeout(2000)
                password_input = await page.wait_for_selector('input[name="password"]', timeout=3000)
            except Exception as e:
                print(f"Failed to find login fields: {e}")
                await page.screenshot(path="login_error.png")
                await context.close()
                return

        await page.fill('input[name="password"]', 'pmuFNqkQka')
        await page.keyboard.press('Enter')
        
        await page.wait_for_timeout(3000)
        
        # Check for 2FA
        print("Checking if 2FA is requested...")
        try:
            totp_input = await page.wait_for_selector('input[data-testid="ocfEnterTextTextInput"]', timeout=4000)
            if totp_input:
                print("Generating 2FA code...")
                totp = pyotp.TOTP('5H4K3QLJBC23KZBP')
                code = totp.now()
                print(f"Entering 2FA code: {code}")
                await totp_input.fill(code)
                await page.keyboard.press('Enter')
                await page.wait_for_timeout(3000)
        except Exception:
            print("No 2FA requested.")
            
        print(f"Final URL: {page.url}")
        await page.screenshot(path="login_final.png")
        if "login" not in page.url and "i/flow/login" not in page.url:
            print("Successfully logged in via UI!")
        else:
            print("Login failed, still on login page.")
            
        await context.close()

if __name__ == "__main__":
    asyncio.run(login_with_ui())
