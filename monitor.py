import smtplib
import os
import sys
from email.mime.text import MIMEText
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# ── Konfiguration ──────────────────────────────────────────────
TARGET_DATE_DISPLAY = "1. April 2026"
ADULTS              = 2
CHILDREN            = 3
ALERT_EMAIL         = "havas.michael@gmail.com"
BOOKING_URL         = "https://hhticket.gr/tap_b2c_new/english/tap.exe?PM=P1P&place=000000002"
NOT_AVAILABLE_TEXT  = "not available for this specific selection"
# ──────────────────────────────────────────────────────────────


def log(msg: str):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def click_day_1(page) -> bool:
    """Klickt exakt auf Tag 1 im Kalender — nicht 11, 21, 31."""
    result = page.evaluate("""
        () => {
            const cells = document.querySelectorAll('td, [class*="day"], [class*="calendar"] span');
            for (const cell of cells) {
                const txt = (cell.textContent || '').trim();
                const cls = (cell.className || '').toLowerCase();
                // Exakt "1" — keine anderen Zahlen die 1 enthalten
                if (txt === '1' && !cls.includes('disabled') && !cls.includes('prev')
                    && !cls.includes('other') && !cls.includes('grayed')) {
                    cell.click();
                    return 'geklickt: ' + cell.tagName + ' class=' + cell.className;
                }
            }
            return null;
        }
    """)
    if result:
        log(f"Tag 1 per JS geklickt: {result}")
        return True
    log("JS-Klick fehlgeschlagen — versuche Playwright-Locator ...")
    # Playwright-Fallback: aria-label mit Datum
    for label in ["April 1", "1 April", "April 1, 2026", "1. April"]:
        try:
            el = page.locator(f"[aria-label*='{label}']").first
            if el.is_visible(timeout=1000):
                el.click()
                log(f"Tag 1 per aria-label '{label}' geklickt.")
                return True
        except Exception:
            pass
    return False


def page_has_not_available(page) -> bool:
    """4 Methoden um den 'not available'-Popup zu erkennen."""
    # Methode 1: HTML-Quellcode (absolut zuverlässig)
    try:
        html = page.content()
        if NOT_AVAILABLE_TEXT in html.lower():
            log("Erkannt via HTML-Quellcode.")
            return True
    except Exception as e:
        log(f"HTML-Check Fehler: {e}")

    # Methode 2: JavaScript alle DOM-Texte
    try:
        found = page.evaluate(f"""
            () => {{
                const needle = '{NOT_AVAILABLE_TEXT}';
                return document.body.innerHTML.toLowerCase().includes(needle);
            }}
        """)
        if found:
            log("Erkannt via JS innerHTML.")
            return True
    except Exception as e:
        log(f"JS-Check Fehler: {e}")

    # Methode 3: role=dialog
    try:
        if page.locator("[role='dialog']").is_visible(timeout=1000):
            txt = page.locator("[role='dialog']").inner_text(timeout=2000).lower()
            if "not available" in txt or "unavailable" in txt:
                log(f"Erkannt via role=dialog: '{txt[:100]}'")
                return True
    except Exception:
        pass

    # Methode 4: Sichtbare Modals
    for sel in ["[class*='modal']", "[class*='popup']", "[class*='alert']", "[class*='warning']"]:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=500):
                txt = el.inner_text(timeout=1000).lower()
                if "not available" in txt or "unavailable" in txt or "service" in txt:
                    log(f"Erkannt via '{sel}': '{txt[:100]}'")
                    return True
        except Exception:
            pass

    return False


def check_availability() -> dict:
    log("Starte Browser ...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        try:
            # ── 1. Seite laden ──────────────────────────────────────
            log(f"Oeffne: {BOOKING_URL}")
            page.goto(BOOKING_URL, timeout=30000, wait_until="networkidle")

            # ── 2. "Buy your ticket" klicken ───────────────────────
            log("Klicke 'Buy your ticket' ...")
            page.click("text=Buy your ticket", timeout=10000)
            page.wait_for_timeout(2000)

            # ── 3. Zu April 2026 navigieren ────────────────────────
            log("Navigiere zu April 2026 ...")
            for _ in range(24):
                try:
                    if page.locator("text=April 2026").is_visible(timeout=1500):
                        log("April 2026 sichtbar.")
                        break
                except Exception:
                    pass
                for btn_sel in [
                    "button.next", ".next-month",
                    "[aria-label*='next' i]", "[aria-label*='Next' i]",
                    "button:has-text('›')", "button:has-text('>')",
                ]:
                    try:
                        page.locator(btn_sel).first.click(timeout=1500)
                        page.wait_for_timeout(600)
                        break
                    except Exception:
                        pass

            # ── 4. Tag 1 klicken ────────────────────────────────────
            log("Klicke Tag 1 (exakt) ...")
            clicked = click_day_1(page)
            if not clicked:
                log("WARNUNG: Tag 1 konnte nicht geklickt werden!")

            # ── 5. Warten & Popup prüfen ────────────────────────────
            log("Warte 5 Sekunden auf Popup ...")
            page.wait_for_timeout(5000)

            page.screenshot(path="/tmp/akropolis_after_click.png")
            log("Screenshot gespeichert.")

            if page_has_not_available(page):
                browser.close()
                return {
                    "available": False,
                    "reason": "Datum noch nicht freigegeben (Website: 'not available for this specific selection').",
                    "url": BOOKING_URL,
                }

            log("Kein Fehler-Modal erkannt.")

            # ── 6. Continue & Zeitslots prüfen ──────────────────────
            try:
                page.click("text=Continue", timeout=5000)
                page.wait_for_timeout(3000)
            except Exception:
                log("Kein 'Continue'-Button.")

            # Nochmals pruefen
            if page_has_not_available(page):
                browser.close()
                return {
                    "available": False,
                    "reason": "Nach Continue: Datum noch nicht buchbar.",
                    "url": BOOKING_URL,
                }

            # Zeitslots lesen
            slot_available = False
            slot_found     = False
            for el in page.locator("li, [class*='slot'], [class*='time']").all():
                try:
                    txt = el.inner_text(timeout=500).strip()
                    cls = (el.get_attribute("class") or "").lower()
                    if "8:00" in txt or "08:00" in txt:
                        slot_found = True
                        disabled   = any(w in cls for w in ["disabled","sold","unavail","full"])
                        log(f"8:00-Slot: '{txt}' disabled={disabled}")
                        if not disabled:
                            slot_available = True
                        break
                except Exception:
                    pass

            page.screenshot(path="/tmp/akropolis_slots.png")
            browser.close()

            if slot_available:
                return {"available": True,  "reason": "Zeitslot 8:00 Uhr am 1. April 2026 ist BUCHBAR!", "url": BOOKING_URL}
            elif slot_found:
                return {"available": False, "reason": "Zeitslot 8:00 Uhr ist ausgebucht.",               "url": BOOKING_URL}
            else:
                return {"available": False, "reason": "Datum noch nicht im Buchungssystem verfuegbar.",   "url": BOOKING_URL}

        except Exception as e:
            log(f"Fehler: {e}")
            import traceback; traceback.print_exc()
            try: page.screenshot(path="/tmp/akropolis_error.png")
            except Exception: pass
            browser.close()
            return {"available": False, "reason": f"Fehler: {str(e)[:200]}", "url": BOOKING_URL}


def send_email(subject: str, body: str):
    sender       = os.environ["GMAIL_SENDER"]
    app_password = os.environ["GMAIL_APP_PASSWORD"].replace(" ", "")
    msg            = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"]    = sender
    msg["To"]      = ALERT_EMAIL
    log(f"Sende '{subject}' an {ALERT_EMAIL} ...")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(sender, app_password)
        smtp.send_message(msg)
    log("E-Mail gesendet.")


def build_body(result: dict, available: bool) -> str:
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    url = result.get("url") or BOOKING_URL
    if available:
        return (
            f"ALARM: Akropolis-Tickets JETZT verfuegbar!\n\n"
            f"Datum:    {TARGET_DATE_DISPLAY}\n"
            f"Uhrzeit:  08:00 Uhr\n"
            f"Personen: {ADULTS} Erwachsene + {CHILDREN} Kinder\n\n"
            f">>> Jetzt sofort buchen: {url}\n\n"
            f"Info: {result.get('reason','')}\n\n"
            f"Nicht zu lange warten!\n\nGeprueft: {now}"
        )
    else:
        return (
            f"Akropolis Ticket Monitor - Statusbericht\n\n"
            f"Datum:    {TARGET_DATE_DISPLAY}\n"
            f"Uhrzeit:  08:00 Uhr\n"
            f"Personen: {ADULTS} Erwachsene + {CHILDREN} Kinder\n\n"
            f"Status: NICHT verfuegbar\n"
            f"Grund:  {result.get('reason','Keine Angabe')}\n\n"
            f"Buchungsseite: {BOOKING_URL}\n"
            f"Naechste Pruefungen: 09:00 / 12:00 / 15:00 Uhr\n\n"
            f"Geprueft: {now}"
        )


def main():
    log("=== Akropolis Ticket Monitor ===")
    missing = [v for v in ("GMAIL_SENDER", "GMAIL_APP_PASSWORD") if not os.environ.get(v)]
    if missing:
        log(f"FEHLER: Secrets fehlen: {', '.join(missing)}")
        sys.exit(1)

    result    = check_availability()
    available = result.get("available", False)
    log(f"Endergebnis: verfuegbar={available} | {result.get('reason','-')}")

    subject = "Karten Akropolis JETZT" if available else "Keine Verfuegbarkeit"
    try:
        send_email(subject, build_body(result, available))
    except smtplib.SMTPAuthenticationError:
        log("FEHLER: Gmail-Login fehlgeschlagen!")
        sys.exit(1)
    except Exception as e:
        log(f"E-Mail-Fehler: {e}"); sys.exit(1)

    log("=== Lauf abgeschlossen ===")


if __name__ == "__main__":
    main()
