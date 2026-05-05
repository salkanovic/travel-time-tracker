#!/usr/bin/env python3
"""
Scraper za Google Maps - vrijeme putovanja.
Pokreće headless Chrome, otvara Google Maps directions stranicu,
čeka da se renderira i izvlači podatke.
Zapisuje rezultat u travel_log.txt.
"""

import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ─── KONFIGURACIJA ────────────────────────────────────────────────────────────

# URL se čita iz environment varijable (postavlja se kao GitHub Secret)
MAPS_URL = os.environ.get("MAPS_URL", "")

if not MAPS_URL:
    print("[GREŠKA] MAPS_URL environment varijabla nije postavljena!", file=sys.stderr)
    print("Postavi je kao GitHub Secret (Settings → Secrets → Actions).", file=sys.stderr)
    sys.exit(1)

LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "travel_log.txt")

# Zagreb timezone (UTC+1 zima, UTC+2 ljeto)
HR_TZ = timezone(timedelta(hours=2))  # CEST (ljeto)


# ─── FUNKCIJE ─────────────────────────────────────────────────────────────────

def create_driver():
    """Kreira headless Chrome driver za GitHub Actions."""
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--lang=hr")
    options.add_argument(
        "--user-agent=Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    )

    # Pokušaj pronaći Chrome/Chromium
    for path in [
        "/usr/bin/google-chrome-stable",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium-browser",
        "/usr/bin/chromium",
    ]:
        if os.path.exists(path):
            options.binary_location = path
            break

    try:
        from webdriver_manager.chrome import ChromeDriverManager
        service = Service(ChromeDriverManager().install())
    except Exception:
        service = Service()

    return webdriver.Chrome(service=service, options=options)


def accept_cookies(driver):
    """Prihvati Google cookies dijalog."""
    try:
        btn = WebDriverWait(driver, 8).until(
            EC.element_to_be_clickable((
                By.XPATH,
                "//button[contains(., 'Accept all') or contains(., 'Prihvati sve') "
                "or contains(., 'Prihvaćam') or contains(., 'I agree')]"
            ))
        )
        btn.click()
        time.sleep(2)
    except Exception:
        pass


def get_travel_data(driver):
    """Otvori Google Maps i izvuci vrijeme putovanja."""

    print(f"Otvaranje URL-a...")
    driver.get(MAPS_URL)
    time.sleep(5)

    accept_cookies(driver)

    # Čekaj da se učita panel s rutama
    time.sleep(5)

    # ─── Izvuci TRAJANJE ──────────────────────────────────────────────────

    duration = None

    # Metoda 1: Traži element s klasom koja sadrži vrijeme
    selectors = [
        "div.Fk3sm.fontHeadlineSmall",
        "div.Fk3sm",
        "div.XdKEzd div[class*='fontHeadline']",
        "div.MespJc div[class*='fontHeadline']",
    ]

    for sel in selectors:
        try:
            el = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, sel))
            )
            text = el.text.strip()
            if re.search(r'\d+\s*(min|h|sat)', text, re.IGNORECASE):
                duration = text
                print(f"  Trajanje pronađeno (CSS): {duration}")
                break
        except Exception:
            continue

    # Metoda 2: XPath za tekst koji sadrži "min"
    if not duration:
        try:
            elements = driver.find_elements(
                By.XPATH,
                "//*[contains(@class,'fontHeadline')][contains(text(),'min')]"
            )
            for el in elements:
                text = el.text.strip()
                if re.match(r'^\d+\s*(h\s*\d+\s*)?min$', text):
                    duration = text
                    print(f"  Trajanje pronađeno (XPath): {duration}")
                    break
        except Exception:
            pass

    # Metoda 3: Brute force - svi elementi s "min"
    if not duration:
        try:
            elements = driver.find_elements(By.XPATH, "//*[contains(text(),'min')]")
            for el in elements:
                text = el.text.strip()
                if re.match(r'^\d{1,3}\s*min$', text):
                    duration = text
                    print(f"  Trajanje pronađeno (brute): {duration}")
                    break
        except Exception:
            pass

    # Metoda 4: Iz page source (APP_INITIALIZATION_STATE)
    if not duration:
        try:
            source = driver.page_source
            matches = re.findall(r'"(\d{1,3}\s*min)"', source)
            for m in matches:
                mins = int(re.search(r'\d+', m).group())
                if 5 <= mins <= 180:
                    duration = m
                    print(f"  Trajanje pronađeno (source): {duration}")
                    break
        except Exception:
            pass

    # ─── Izvuci UDALJENOST ────────────────────────────────────────────────

    distance = None
    try:
        dist_els = driver.find_elements(By.CSS_SELECTOR, "div.ivN21e.tUEI8e")
        for el in dist_els:
            text = el.text.strip()
            if 'km' in text:
                distance = text
                break
    except Exception:
        pass

    if not distance:
        try:
            elements = driver.find_elements(By.XPATH, "//*[contains(text(),'km')]")
            for el in elements:
                text = el.text.strip()
                if re.match(r'^[\d,\.]+\s*km$', text):
                    distance = text
                    break
        except Exception:
            pass

    # ─── Izvuci NAZIV RUTE ────────────────────────────────────────────────

    route = None
    try:
        route_el = driver.find_element(By.CSS_SELECTOR, "h1.VuCHmb")
        route = route_el.text.strip()
    except Exception:
        pass

    # ─── Screenshot za debug ──────────────────────────────────────────────
    if not duration:
        debug_path = os.path.join(os.path.dirname(LOG_FILE), "debug_screenshot.png")
        driver.save_screenshot(debug_path)
        print(f"  DEBUG: Screenshot spremljen u {debug_path}")

        # Spremi page source
        source_path = os.path.join(os.path.dirname(LOG_FILE), "debug_source.html")
        with open(source_path, "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        print(f"  DEBUG: Page source spremljen u {source_path}")

    return duration, distance, route


def log_result(duration, distance, route):
    """Zapiši u log datoteku."""
    now = datetime.now(HR_TZ).strftime("%d.%m.%Y %H:%M:%S")
    is_new = not os.path.exists(LOG_FILE)

    with open(LOG_FILE, "a", encoding="utf-8") as f:
        if is_new:
            f.write("Datum i vrijeme        | Trajanje | Udaljenost | Ruta\n")
            f.write("-" * 75 + "\n")

        if duration:
            f.write(f"{now} | {duration:>8s} | {(distance or '-'):>10s} | {route or '-'}\n")
        else:
            f.write(f"{now} | GREŠKA   | -          | nije pronađeno\n")


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    now_hr = datetime.now(HR_TZ).strftime("%d.%m.%Y %H:%M:%S")
    print(f"[{now_hr}] Pokrećem scraper...")

    driver = None
    try:
        driver = create_driver()
        duration, distance, route = get_travel_data(driver)

        log_result(duration, distance, route)

        if duration:
            print(f"[OK] {now_hr} - {duration} ({distance}, {route})")
        else:
            print("[GREŠKA] Nije pronađeno vrijeme putovanja.", file=sys.stderr)
            sys.exit(1)

    except Exception as e:
        print(f"[GREŠKA] {e}", file=sys.stderr)
        log_result(None, None, None)
        sys.exit(1)

    finally:
        if driver:
            driver.quit()


if __name__ == "__main__":
    main()
