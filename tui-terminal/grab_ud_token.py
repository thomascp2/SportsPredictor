"""
grab_ud_token.py — Auto-capture Underdog Fantasy bearer token via Selenium.

Usage:
    python grab_ud_token.py

What it does:
1. Opens Chrome on underdogfantasy.com
2. You log in normally (takes as long as you need)
3. Script watches for API calls and grabs the Authorization header
4. Writes UNDERDOG_AUTH_TOKEN=Bearer eyJ... to .env automatically
"""

import time
import json
import os
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

ENV_PATH = Path(__file__).parent / ".env"

def read_env():
    """Read current .env as dict."""
    env = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env

def write_env(env: dict):
    """Write dict back to .env."""
    lines = [f"{k}={v}" for k, v in env.items()]
    ENV_PATH.write_text("\n".join(lines) + "\n")

def main():
    print("=" * 60)
    print("Underdog Fantasy Token Grabber")
    print("=" * 60)
    print()
    print("Opening Chrome... log in to Underdog Fantasy when the browser opens.")
    print("The script will automatically grab your token once you're in.")
    print("(You can close this terminal after it says 'Token saved!')")
    print()

    options = Options()
    options.add_argument("--start-maximized")

    driver = webdriver.Chrome(options=options)
    driver.get("https://underdogfantasy.com")

    token = None
    print("Log in to Underdog Fantasy in the browser window.")
    print("Script will find your token automatically once you're logged in.")
    print()

    deadline = time.time() + 300  # 5 min timeout
    while time.time() < deadline:
        time.sleep(2)

        try:
            # Dump ALL of localStorage and look for anything JWT-shaped
            storage = driver.execute_script("""
                let items = {};
                for (let i = 0; i < localStorage.length; i++) {
                    let k = localStorage.key(i);
                    items[k] = localStorage.getItem(k);
                }
                return items;
            """)

            for key, value in (storage or {}).items():
                if not value:
                    continue
                # Direct JWT string
                if value.startswith("eyJ"):
                    token = "Bearer " + value
                    print(f"\nFound JWT in localStorage['{key}']")
                    break
                # JSON blob containing a token field
                if value.startswith("{"):
                    try:
                        obj = json.loads(value)
                        for field in ("access_token", "token", "accessToken", "id_token", "bearer"):
                            if field in obj and str(obj[field]).startswith("eyJ"):
                                token = "Bearer " + obj[field]
                                print(f"\nFound JWT in localStorage['{key}']['{field}']")
                                break
                    except Exception:
                        pass
                if token:
                    break

            # Also check sessionStorage
            if not token:
                sstorage = driver.execute_script("""
                    let items = {};
                    for (let i = 0; i < sessionStorage.length; i++) {
                        let k = sessionStorage.key(i);
                        items[k] = sessionStorage.getItem(k);
                    }
                    return items;
                """)
                for key, value in (sstorage or {}).items():
                    if not value:
                        continue
                    if value.startswith("eyJ"):
                        token = "Bearer " + value
                        print(f"\nFound JWT in sessionStorage['{key}']")
                        break
                    if value.startswith("{"):
                        try:
                            obj = json.loads(value)
                            for field in ("access_token", "token", "accessToken", "id_token", "bearer"):
                                if field in obj and str(obj[field]).startswith("eyJ"):
                                    token = "Bearer " + obj[field]
                                    print(f"\nFound JWT in sessionStorage['{key}']['{field}']")
                                    break
                        except Exception:
                            pass
                    if token:
                        break

            # Also check cookies
            if not token:
                for cookie in driver.get_cookies():
                    v = cookie.get("value", "")
                    if v.startswith("eyJ"):
                        token = "Bearer " + v
                        print(f"\nFound JWT in cookie['{cookie['name']}']")
                        break

        except Exception as e:
            pass

        if token:
            break

        print(".", end="", flush=True)

    driver.quit()
    print()

    if not token:
        print()
        print("ERROR: Timed out after 5 minutes without seeing a UD API call.")
        print("Make sure you navigated to the lobby or tapped a player prop after logging in.")
        return

    # Write to .env
    env = read_env()
    env["UNDERDOG_AUTH_TOKEN"] = token
    write_env(env)

    print()
    print("=" * 60)
    print("Token saved!")
    print(f"  File: {ENV_PATH}")
    print(f"  Value: {token[:30]}...{token[-10:]}")
    print()
    print("The Rust ingester will pick it up on next launch.")
    print("Run ./launch.sh to start the full TUI stack.")
    print("=" * 60)

if __name__ == "__main__":
    main()
