import smtplib
import os
import sys
from email.mime.text import MIMEText
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# ── Konfiguration ──────────────────────────────────────────────
TARGET_DATE_DISPLAY = "1. April 2026"
TARGET_DAY          = "1"
TARGET_TIME_SLOT    = "8:00"
ADULTS              = 2
CHILDREN            = 3
ALERT_EMAIL         = "havas.michael@gmail.com"
BOOKING_URL         = "https://hhticket.gr/tap_b2c_new/english/tap.exe?PM=P1P&place=000000002"
# ──────────────────────────────────────────────────────────────

NOT_AVAILABLE_TEXTS = [
    "not available for this specific selection",
    "service is not available",
    "not available",
    "sold out",
    "keine verfügbarkeit",
]

def log(msg: str):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def check_availability() -> dict:
    log("Starte Browser ...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )

        try:
            log(f"Oeffne: {BOOKING_URL}")
            page.goto(BOOKING_URL, timeout=30000, wait_until="networkidle")

            # Schritt 1: "Buy your ticket" klicken
            log("Klicke 'Buy your ticket' ...")
            page.click("text=Buy your ticket", timeout=10000)
            page.wait_for_timeout(2000)

            # Schritt 2: Zum richtigen Monat navigieren (April 2026)
            log("Navigiere zu April 2026 ...")
            for _ in range(24):
                try:
                    header = page.locator("text=April 2026").first
                    if header.is_visible(timeout=2000):
                        log("April 2026 gefunden.")
                        break
                except Exception:
                    pass
                try:
                    page.locator("[aria-label*='next' i], [aria-label*='Next' i], .next, button:has-text('›'), button:has-text('>')").first.click()
                    page.wait_for_timeout(600)
                except Exception as e:
                    log(f"Weiterklicken fehlgeschlagen: {e}")
                    break

            # Schritt 3: Tag 1 klicken
            log("Klicke Tag 1 ...")
            # Suche nach einem klickbaren Tag mit Text "1" der nicht disabled ist
            clicked = False
            candidates = page.locator("td, [class*='day'], button").all()
            for el in candidates:
                try:
                    txt     = el.inner_text(timeout=500).strip()
                    classes = el.get_attribute("class") or ""
                    if txt == "1" and "disabled" not in classes and "other-month" not in classes:
                        el.click()
                        log("Tag 1 geklickt.")
                        clicked = True
                        break
                except Exception:
                    pass

            if not clicked:
                # Fallback: direkt auf die "1" im Kalender klicken
                page.locator("td:has-text('1'):not([class*='disabled'])").first.click()
                log("Tag 1 per Fallback geklickt.")

            page.wait_for_timeout(2500)

            # Schritt 4: Popup prüfen — "not available" Meldung?
            log("Prüfe auf Fehler-Popup ...")
            try:
                popup_visible = page.locator("text=not available for this specific selection").is_visible(timeout=4000)
            except Exception:
                popup_visible = False

            if popup_visible:
                log("Popup erkannt: 'not available for this specific selection'")
                page.screenshot(path="/tmp/akropolis_screenshot.png")
                browser.close()
                return {
                    "available": False,
                    "reason": "Datum noch nicht freigegeben (Website: 'not available for this specific selection').",
                    "url": BOOKING_URL
                }

            # Weitere "not available"-Texte prüfen
            body_text = page.inner_text("body").lower()
            for phrase in NOT_AVAILABLE_TEXTS:
                if phrase.lower() in body_text:
                    log(f"'Not available'-Text gefunden: '{phrase}'")
                    page.screenshot(path="/tmp/akropolis_screenshot.png")
                    browser.close()
                    return {
                        "available": False,
                        "reason": f"Noch nicht buchbar (Website meldet: '{phrase}').",
                        "url": BOOKING_URL
                    }

            # Schritt 5: Continue klicken und Zeitslots prüfen
            log("Kein Fehler-Popup — klicke 'Continue' ...")
            try:
                page.click("text=Continue", timeout=5000)
                page.wait_for_timeout(2000)
            except Exception:
                log("Kein 'Continue'-Button gefunden.")

            # Nochmal auf Popup prüfen nach Continue
            try:
                popup_visible2 = page.locator("text=not available for this specific selection").is_visible(timeout=3000)
                if popup_visible2:
                    browser.close()
                    return {
                        "available": False,
                        "reason": "Nach Datumswahl: Datum noch nicht buchbar.",
                        "url": BOOKING_URL
                    }
            except Exception:
                pass

            # Schritt 6: Zeitslots lesen
            log("Lese Zeitslots ...")
            page.wait_for_timeout(2000)
            page_text_slots = page.inner_text("body")
            log(f"Seiteninhalt (Auszug): {page_text_slots[:600]}")

            # Suche explizit nach 8:00-Slot
            slot_available = False
            slot_found     = False

            slot_els = page.locator("li, [class*='slot'], [class*='time']").all()
            for el in slot_els:
                try:
                    txt     = el.inner_text(timeout=500).strip()
                    classes = el.get_attribute("class") or ""
                    if "8:00" in txt or "08:00" in txt:
                        slot_found = True
                        disabled   = any(w in classes.lower() for w in ["disabled", "sold", "unavail", "full"])
                        log(f"8:00-Slot: text='{txt}' classes='{classes}' disabled={disabled}")
                        if not disabled:
                            slot_available = True
                        break
                except Exception:
                    pass

            page.screenshot(path="/tmp/akropolis_screenshot.png")
            browser.close()

            if slot_available:
                return {
                    "available": True,
                    "reason": "Zeitslot 8:00 Uhr am 1. April 2026 ist buchbar!",
                    "url": BOOKING_URL
                }
            elif slot_found:
                return {
                    "available": False,
                    "reason": "Zeitslot 8:00 Uhr am 1. April 2026 ist ausgebucht.",
                    "url": BOOKING_URL
                }
            else:
                return {
                    "available": False,
                    "reason": "Datum noch nicht im Buchungssystem verfuegbar.",
                    "url": BOOKING_URL
                }

        except PlaywrightTimeout as e:
            log(f"Timeout: {e}")
            try:
                page.screenshot(path="/tmp/akropolis_error.png")
            except Exception:
                pass
            browser.close()
            return {"available": False, "reason": f"Timeout: {str(e)[:120]}", "url": BOOKING_URL}

        except Exception as e:
            log(f"Fehler: {e}")
            import traceback; traceback.print_exc()
            try:
                page.screenshot(path="/tmp/akropolis_error.png")
            except Exception:
                pass
            browser.close()
            return {"available": False, "reason": f"Fehler: {str(e)[:150]}", "url": BOOKING_URL}


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
            f"ALARM: Akropolis-Tickets sind JETZT verfuegbar!\n\n"
            f"Datum:    {TARGET_DATE_DISPLAY}\n"
            f"Uhrzeit:  08:00 Uhr\n"
            f"Personen: {ADULTS} Erwachsene + {CHILDREN} Kinder\n\n"
            f">>> Jetzt sofort buchen: {url}\n\n"
            f"Info: {result.get('reason', '')}\n\n"
            f"Nicht zu lange warten - Tickets werden schnell ausgebucht!\n\n"
            f"Geprueft: {now}"
        )
    else:
        return (
            f"Akropolis Ticket Monitor - Statusbericht\n\n"
            f"Datum:    {TARGET_DATE_DISPLAY}\n"
            f"Uhrzeit:  08:00 Uhr\n"
            f"Personen: {ADULTS} Erwachsene + {CHILDREN} Kinder\n\n"
            f"Status: NICHT verfuegbar\n"
            f"Grund:  {result.get('reason', 'Keine Angabe')}\n\n"
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
    log(f"Ergebnis: verfuegbar={available} | {result.get('reason', '-')}")

    subject = "Karten Akropolis JETZT" if available else "Keine Verfuegbarkeit"
    body    = build_body(result, available)

    try:
        send_email(subject, body)
    except smtplib.SMTPAuthenticationError:
        log("FEHLER: Gmail-Authentifizierung fehlgeschlagen!")
        sys.exit(1)
    except Exception as e:
        log(f"E-Mail-Fehler: {e}")
        sys.exit(1)

    log("=== Lauf abgeschlossen ===")


if __name__ == "__main__":
    main()
