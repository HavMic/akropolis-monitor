import smtplib
import os
import sys
import re
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# ── Konfiguration ──────────────────────────────────────────────
TARGET_DATE_DISPLAY = "1. April 2026"
ADULTS              = 2
CHILDREN            = 3
ALERT_EMAIL         = "havas.michael@gmail.com"
BOOKING_URL         = "https://hhticket.gr/tap_b2c_new/english/tap.exe?PM=P1P&place=000000002"
NOT_AVAILABLE_TEXT  = "not available for this specific selection"
DEBUG               = True   # Sendet HTML-Auszug in die E-Mail
# ──────────────────────────────────────────────────────────────


def log(msg: str):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def click_day_1(page) -> bool:
    """Klickt exakt auf Tag 1 im Kalender via JavaScript."""
    result = page.evaluate("""
        () => {
            const cells = document.querySelectorAll('td, [class*="day"], [class*="calendar"] span, button');
            for (const cell of cells) {
                const txt = (cell.textContent || '').trim();
                const cls = (cell.className || '').toLowerCase();
                if (txt === '1' && !cls.includes('disabled') && !cls.includes('prev')
                    && !cls.includes('other') && !cls.includes('grayed')) {
                    cell.click();
                    return cell.tagName + '|' + cell.className;
                }
            }
            return null;
        }
    """)
    if result:
        log(f"Tag 1 per JS geklickt: {result}")
        return True
    # Fallback: aria-label
    for label in ["April 1", "1 April", "April 1, 2026"]:
        try:
            el = page.locator(f"[aria-label*='{label}']").first
            if el.is_visible(timeout=1000):
                el.click()
                log(f"Tag 1 per aria-label '{label}' geklickt.")
                return True
        except Exception:
            pass
    return False


def get_page_debug_info(page) -> dict:
    """Sammelt alle nützlichen Debug-Infos von der Seite."""
    info = {}
    try:
        html = page.content()
        info["html_length"] = len(html)
        info["html_lower"]  = html.lower()
        info["html_raw"]    = html

        # Alle Textstücke rund um "available"
        matches = re.findall(r'.{0,150}available.{0,150}', html, re.IGNORECASE)
        info["available_contexts"] = matches

        # Alle sichtbaren Texte
        info["body_text"] = page.inner_text("body", timeout=5000)

    except Exception as e:
        info["error"] = str(e)
    return info


def is_not_available(debug: dict) -> tuple:
    """
    Prüft auf JEDE erdenkliche Weise ob 'not available' vorkommt.
    Gibt (True/False, Grund) zurück.
    """
    html_lower = debug.get("html_lower", "")
    body_text  = debug.get("body_text",  "").lower()

    checks = [
        (NOT_AVAILABLE_TEXT,              html_lower, "HTML: exact phrase"),
        ("not available",                 html_lower, "HTML: not available"),
        ("not available",                 body_text,  "body_text: not available"),
        ("service is not available",      html_lower, "HTML: service not available"),
        ("ticketing service is not",      html_lower, "HTML: ticketing service"),
        ("specific selection",            html_lower, "HTML: specific selection"),
        ("ενημέρωση",                     html_lower, "HTML: greek popup title"),  # griechisch für "Benachrichtigung"
        ("enimerósi",                     html_lower, "HTML: greek romanized"),
    ]

    for phrase, source, label in checks:
        if phrase in source:
            log(f"NOT_AVAILABLE erkannt via [{label}]: '{phrase}'")
            return True, label

    log("KEINE 'not available' Phrase gefunden.")
    log(f"  body_text Auszug: {body_text[:300]}")
    for ctx in debug.get("available_contexts", [])[:5]:
        log(f"  HTML-Kontext: {ctx[:200]}")

    return False, ""


def check_availability() -> dict:
    log("Starte Browser ...")
    debug_html = ""

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        try:
            # 1. Seite laden
            log(f"Oeffne: {BOOKING_URL}")
            page.goto(BOOKING_URL, timeout=30000, wait_until="networkidle")

            # 2. "Buy your ticket"
            log("Klicke 'Buy your ticket' ...")
            page.click("text=Buy your ticket", timeout=10000)
            page.wait_for_timeout(2000)

            # 3. Zu April 2026 navigieren
            log("Navigiere zu April 2026 ...")
            for _ in range(24):
                try:
                    if page.locator("text=April 2026").is_visible(timeout=1500):
                        log("April 2026 sichtbar.")
                        break
                except Exception:
                    pass
                for btn_sel in ["button.next", ".next-month", "[aria-label*='next' i]",
                                "button:has-text('›')", "button:has-text('>')"]:
                    try:
                        page.locator(btn_sel).first.click(timeout=1500)
                        page.wait_for_timeout(600)
                        break
                    except Exception:
                        pass

            # 4. Tag 1 klicken
            log("Klicke Tag 1 ...")
            clicked = click_day_1(page)
            if not clicked:
                log("WARNUNG: Tag 1 konnte nicht geklickt werden!")

            # 5. Warten — Popup braucht Zeit
            log("Warte 6 Sekunden ...")
            page.wait_for_timeout(6000)

            # 6. Debug-Info sammeln
            log("Sammle Debug-Infos von der Seite ...")
            debug = get_page_debug_info(page)
            debug_html = debug.get("html_raw", "")[:8000]

            log(f"HTML-Laenge: {debug.get('html_length', 0)} Zeichen")
            log(f"Body-Text (erste 500 Zeichen): {debug.get('body_text','')[:500]}")

            # Screenshot
            page.screenshot(path="/tmp/akropolis_screenshot.png")

            # 7. Prüfung
            not_avail, reason = is_not_available(debug)

            if not_avail:
                browser.close()
                return {
                    "available": False,
                    "reason": "Datum noch nicht buchbar (Website: 'not available for this specific selection').",
                    "url": BOOKING_URL,
                    "debug_html": debug_html,
                }

            # 8. Continue & Slots
            log("Kein Fehler-Modal. Pruefe Zeitslots ...")
            try:
                page.click("text=Continue", timeout=5000)
                page.wait_for_timeout(3000)
            except Exception:
                pass

            # Nochmals nach Popup prüfen
            debug2 = get_page_debug_info(page)
            not_avail2, _ = is_not_available(debug2)
            if not_avail2:
                browser.close()
                return {
                    "available": False,
                    "reason": "Nach Continue: Datum noch nicht buchbar.",
                    "url": BOOKING_URL,
                    "debug_html": debug2.get("html_raw","")[:8000],
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

            browser.close()

            if slot_available:
                return {"available": True,  "reason": "Zeitslot 8:00 Uhr am 1. April 2026 ist BUCHBAR!", "url": BOOKING_URL}
            elif slot_found:
                return {"available": False, "reason": "Zeitslot 8:00 ausgebucht.", "url": BOOKING_URL}
            else:
                return {
                    "available": False,
                    "reason": "Datum noch nicht buchbar (keine Slots gefunden).",
                    "url": BOOKING_URL,
                    "debug_html": debug2.get("html_raw","")[:8000],
                }

        except Exception as e:
            log(f"Fehler: {e}")
            import traceback; traceback.print_exc()
            try:
                page.screenshot(path="/tmp/akropolis_error.png")
                debug_e = get_page_debug_info(page)
                debug_html = debug_e.get("html_raw","")[:8000]
            except Exception:
                pass
            browser.close()
            return {"available": False, "reason": f"Fehler: {str(e)[:200]}", "url": BOOKING_URL, "debug_html": debug_html}


def send_email(subject: str, body: str):
    sender       = os.environ["GMAIL_SENDER"]
    app_password = os.environ["GMAIL_APP_PASSWORD"].replace(" ", "")
    msg            = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"]    = sender
    msg["To"]      = ALERT_EMAIL
    log(f"Sende '{subject}' ...")
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
            f"Geprueft: {now}"
        )
    else:
        body = (
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
        # Debug-HTML anhängen damit wir sehen was die Seite wirklich zeigt
        if DEBUG and result.get("debug_html"):
            body += f"\n\n{'='*40}\nDEBUG HTML-AUSZUG (erste 3000 Zeichen):\n{'='*40}\n"
            body += result["debug_html"][:3000]
        return body


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
