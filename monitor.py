import smtplib
import os
import sys
from email.mime.text import MIMEText
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# ── Konfiguration ──────────────────────────────────────────────
TARGET_DATE_DISPLAY = "1. April 2026"
TARGET_DATE_PICK    = "April 1, 2026"   # Englisches Format fuer den Kalender
TARGET_MONTH_YEAR   = "April 2026"
TARGET_DAY          = "1"
TARGET_TIME_SLOT    = "8:00"            # Suche nach diesem Slot
ADULTS              = 2
CHILDREN            = 3
ALERT_EMAIL         = "havas.michael@gmail.com"
BOOKING_URL         = "https://hhticket.gr/tap_b2c_new/english/tap.exe?PM=P1P&place=000000002"
# ──────────────────────────────────────────────────────────────


def log(msg: str):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def check_availability() -> dict:
    log("Starte Browser (Playwright) ...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        page = context.new_page()

        try:
            log(f"Oeffne Buchungsseite: {BOOKING_URL}")
            page.goto(BOOKING_URL, timeout=30000, wait_until="networkidle")
            log("Seite geladen.")

            # Schritt 1: "Buy your ticket" Button klicken
            log("Klicke 'Buy your ticket' ...")
            page.click("text=Buy your ticket", timeout=10000)
            page.wait_for_timeout(2000)

            # Schritt 2: Datum auswaehlen — durch den Kalender navigieren
            log("Navigiere zum Datum 1. April 2026 ...")

            # Warte auf Kalender
            page.wait_for_selector(".calendar, [class*='calendar'], [class*='date']", timeout=10000)

            # Navigiere zum richtigen Monat (April 2026)
            for _ in range(24):  # max 24 Monate weiterklicken
                try:
                    header_text = page.locator("[class*='month'], [class*='calendar-header']").first.inner_text(timeout=3000)
                    log(f"Aktueller Monat: {header_text}")
                    if "April" in header_text and "2026" in header_text:
                        break
                    # Naechsten Monat
                    next_btn = page.locator("[class*='next'], button[aria-label*='next'], button[aria-label*='Next']").first
                    next_btn.click()
                    page.wait_for_timeout(500)
                except Exception as e:
                    log(f"Kalender-Navigation: {e}")
                    break

            # Tag 1 klicken
            log("Klicke auf Tag 1 ...")
            day_btns = page.locator(f"[class*='day']:not([class*='disabled']):not([class*='other']), td:not([class*='disabled'])")
            for btn in day_btns.all():
                txt = btn.inner_text().strip()
                if txt == TARGET_DAY or txt == f"0{TARGET_DAY}":
                    btn.click()
                    log("Tag 1 geklickt.")
                    break
            page.wait_for_timeout(2000)

            # Schritt 3: Zeitslots lesen
            log("Lese verfuegbare Zeitslots ...")
            page.wait_for_selector("[class*='time'], [class*='slot']", timeout=10000)
            slot_elements = page.locator("[class*='time-slot'], [class*='slot'], li").all()

            slots_info = []
            target_available = False
            target_sold_out  = False

            for el in slot_elements:
                try:
                    text    = el.inner_text().strip()
                    classes = el.get_attribute("class") or ""
                    if TARGET_TIME_SLOT in text or "8:00" in text:
                        is_disabled = ("disabled" in classes or "sold" in classes.lower()
                                       or "unavailable" in classes.lower())
                        log(f"  Slot gefunden: '{text}' | Klassen: '{classes}' | Disabled: {is_disabled}")
                        if is_disabled:
                            target_sold_out  = True
                        else:
                            target_available = True
                        slots_info.append(f"{text} ({'ausgebucht' if is_disabled else 'verfuegbar'})")
                    elif any(t in text for t in ["8:", "10:", "12:", "14:"]):
                        is_disabled = "disabled" in classes or "sold" in classes.lower()
                        slots_info.append(f"{text} ({'ausgebucht' if is_disabled else 'verfuegbar'})")
                except Exception:
                    pass

            page.screenshot(path="/tmp/akropolis_screenshot.png")
            log("Screenshot gespeichert: /tmp/akropolis_screenshot.png")

            if target_available:
                return {
                    "available": True,
                    "reason": f"Slot 8:00 Uhr am 1. April 2026 ist buchbar! Alle Slots: {', '.join(slots_info[:4])}",
                    "url": BOOKING_URL
                }
            elif target_sold_out:
                return {
                    "available": False,
                    "reason": f"Slot 8:00 Uhr ist ausgebucht. Gefundene Slots: {', '.join(slots_info[:4])}",
                    "url": BOOKING_URL
                }
            elif slots_info:
                return {
                    "available": False,
                    "reason": f"8:00-Slot nicht eindeutig erkannt. Gefundene Slots: {', '.join(slots_info[:4])}",
                    "url": BOOKING_URL
                }
            else:
                # Seiten-Inhalt fuer Debugging
                page_text = page.inner_text("body")[:500]
                log(f"Kein Slot gefunden. Seiteninhalt: {page_text}")
                return {
                    "available": False,
                    "reason": "Datum noch nicht buchbar oder Seite hat sich geaendert.",
                    "url": BOOKING_URL
                }

        except PlaywrightTimeout as e:
            log(f"Timeout: {e}")
            try:
                page.screenshot(path="/tmp/akropolis_error.png")
            except Exception:
                pass
            return {
                "available": False,
                "reason": f"Timeout beim Laden der Seite: {str(e)[:100]}",
                "url": BOOKING_URL
            }
        except Exception as e:
            log(f"Fehler: {e}")
            import traceback; traceback.print_exc()
            try:
                page.screenshot(path="/tmp/akropolis_error.png")
            except Exception:
                pass
            return {
                "available": False,
                "reason": f"Fehler: {str(e)[:150]}",
                "url": BOOKING_URL
            }
        finally:
            browser.close()


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
    log("=== Akropolis Ticket Monitor (Playwright) ===")

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
        log("Pruefen: App-Passwort korrekt? 2FA aktiv? GMAIL_SENDER richtig?")
        sys.exit(1)
    except Exception as e:
        log(f"E-Mail-Fehler: {e}")
        sys.exit(1)

    log("=== Lauf abgeschlossen ===")


if __name__ == "__main__":
    main()
