import smtplib
import os
import sys
from email.mime.text import MIMEText
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# ── Konfiguration ──────────────────────────────────────────────
TARGET_DATE_DISPLAY = "1. April 2026"
TARGET_DAY          = "1"
ADULTS              = 2
CHILDREN            = 3
ALERT_EMAIL         = "havas.michael@gmail.com"
BOOKING_URL         = "https://hhticket.gr/tap_b2c_new/english/tap.exe?PM=P1P&place=000000002"
# ──────────────────────────────────────────────────────────────

# Texte die auf der Website "nicht verfuegbar" bedeuten
NOT_AVAILABLE_PHRASES = [
    "not available for this specific selection",
    "service is not available",
    "not available",
    "sold out",
    "no tickets available",
]


def log(msg: str):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def page_contains_not_available(page) -> bool:
    """Prueft ob die Seite eine 'nicht verfuegbar' Meldung enthaelt."""
    try:
        body = page.inner_text("body", timeout=3000).lower()
        for phrase in NOT_AVAILABLE_PHRASES:
            if phrase.lower() in body:
                log(f"  -> 'Nicht verfuegbar'-Text gefunden: '{phrase}'")
                return True
    except Exception as e:
        log(f"  -> Fehler beim Lesen der Seite: {e}")
    return False


def check_availability() -> dict:
    log("Starte Browser ...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )

        try:
            # ── Schritt 1: Seite laden ──────────────────────────────
            log(f"Oeffne: {BOOKING_URL}")
            page.goto(BOOKING_URL, timeout=30000, wait_until="networkidle")
            log("Seite geladen.")

            # ── Schritt 2: "Buy your ticket" klicken ───────────────
            log("Klicke 'Buy your ticket' ...")
            page.click("text=Buy your ticket", timeout=10000)
            page.wait_for_timeout(2000)

            # ── Schritt 3: Zu April 2026 navigieren ────────────────
            log("Navigiere zu April 2026 ...")
            for attempt in range(24):
                # Pruefe ob April 2026 bereits sichtbar
                try:
                    if page.locator("text=April 2026").is_visible(timeout=1500):
                        log("April 2026 ist sichtbar.")
                        break
                except Exception:
                    pass
                # Naechsten Monat klicken
                try:
                    page.locator("button.next, .next-month, [aria-label*='next' i], [aria-label*='Next' i]").first.click(timeout=3000)
                    page.wait_for_timeout(700)
                except Exception:
                    try:
                        # Fallback: Pfeil-Button per Text
                        page.locator("button:has-text('›'), button:has-text('▶'), button:has-text('>')").first.click(timeout=2000)
                        page.wait_for_timeout(700)
                    except Exception as e:
                        log(f"Navigation Versuch {attempt}: {e}")
                        break

            # ── Schritt 4: Tag 1 klicken ───────────────────────────
            log("Klicke Tag 1 ...")
            clicked = False

            # Strategie A: td-Element mit exakt "1" das nicht disabled ist
            try:
                tds = page.locator("td").all()
                for td in tds:
                    txt = td.inner_text(timeout=500).strip()
                    cls = td.get_attribute("class") or ""
                    if txt == "1" and "disabled" not in cls and "prev" not in cls and "next" not in cls:
                        td.click(timeout=3000)
                        log(f"Tag 1 geklickt (Strategie A, class='{cls}')")
                        clicked = True
                        break
            except Exception as e:
                log(f"Strategie A fehlgeschlagen: {e}")

            # Strategie B: Alle klickbaren Tage
            if not clicked:
                try:
                    page.locator("td:not([class*='disabled']):not([class*='prev']):not([class*='next'])").filter(has_text="1").first.click(timeout=3000)
                    log("Tag 1 geklickt (Strategie B)")
                    clicked = True
                except Exception as e:
                    log(f"Strategie B fehlgeschlagen: {e}")

            if not clicked:
                log("WARNUNG: Tag 1 konnte nicht geklickt werden.")

            # ── Schritt 5: Warten und Popup pruefen ────────────────
            # Warte 4 Sekunden — der Popup braucht Zeit zum Erscheinen
            log("Warte auf Seitenantwort (4 Sekunden) ...")
            page.wait_for_timeout(4000)

            # Screenshot fuer Debugging
            page.screenshot(path="/tmp/akropolis_after_click.png")

            # Seite auf "not available" pruefen
            log("Pruefe auf 'nicht verfuegbar' Meldung ...")
            if page_contains_not_available(page):
                browser.close()
                return {
                    "available": False,
                    "reason": "Datum noch nicht freigegeben (Website: 'not available for this specific selection').",
                    "url": BOOKING_URL
                }

            log("Kein 'nicht verfuegbar'-Text gefunden.")

            # ── Schritt 6: Continue klicken und Zeitslots pruefen ──
            log("Klicke 'Continue' ...")
            try:
                page.click("text=Continue", timeout=5000)
                page.wait_for_timeout(3000)
            except Exception:
                log("Kein 'Continue'-Button gefunden.")

            # Nochmals pruefen nach Continue
            if page_contains_not_available(page):
                browser.close()
                return {
                    "available": False,
                    "reason": "Nach Datumswahl: Datum noch nicht buchbar.",
                    "url": BOOKING_URL
                }

            # Screenshot nach Continue
            page.screenshot(path="/tmp/akropolis_after_continue.png")
            page_text = page.inner_text("body")
            log(f"Seiteninhalt nach Continue (Auszug): {page_text[:500]}")

            # ── Schritt 7: 8:00-Slot suchen ────────────────────────
            log("Suche Zeitslot 8:00 ...")
            slot_found     = False
            slot_available = False

            for el in page.locator("li, [class*='slot'], [class*='time-slot']").all():
                try:
                    txt = el.inner_text(timeout=500).strip()
                    cls = el.get_attribute("class") or ""
                    if "8:00" in txt or "08:00" in txt:
                        slot_found = True
                        disabled   = any(w in cls.lower() for w in ["disabled", "sold", "unavail", "full", "closed"])
                        log(f"8:00-Slot: '{txt}' | class='{cls}' | disabled={disabled}")
                        if not disabled:
                            slot_available = True
                        break
                except Exception:
                    pass

            browser.close()

            if slot_available:
                return {
                    "available": True,
                    "reason": "Zeitslot 8:00 Uhr am 1. April 2026 ist BUCHBAR!",
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
                    "reason": "Datum noch nicht im Buchungssystem verfuegbar (keine Slots geladen).",
                    "url": BOOKING_URL
                }

        except PlaywrightTimeout as e:
            log(f"Timeout-Fehler: {e}")
            try:
                page.screenshot(path="/tmp/akropolis_error.png")
            except Exception:
                pass
            browser.close()
            return {"available": False, "reason": f"Timeout: {str(e)[:120]}", "url": BOOKING_URL}

        except Exception as e:
            log(f"Unerwarteter Fehler: {e}")
            import traceback
            traceback.print_exc()
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
    log(f"Endergebnis: verfuegbar={available} | {result.get('reason', '-')}")

    subject = "Karten Akropolis JETZT" if available else "Keine Verfuegbarkeit"
    body    = build_body(result, available)

    try:
        send_email(subject, body)
    except smtplib.SMTPAuthenticationError:
        log("FEHLER: Gmail-Login fehlgeschlagen. App-Passwort pruefen!")
        sys.exit(1)
    except Exception as e:
        log(f"E-Mail-Fehler: {e}")
        sys.exit(1)

    log("=== Lauf abgeschlossen ===")


if __name__ == "__main__":
    main()
