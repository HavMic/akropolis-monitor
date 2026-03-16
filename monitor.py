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
# ──────────────────────────────────────────────────────────────

def log(msg: str):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def has_error_popup(page) -> bool:
    """Prüft ob ein Fehler-Popup sichtbar ist."""
    try:
        # Direkt via innerText des gesamten gerenderten DOMs
        visible_text = page.evaluate("() => document.body.innerText").lower()
        if "not available for this specific selection" in visible_text:
            log("Popup erkannt via document.body.innerText")
            return True
        if "specific selection" in visible_text:
            log("Popup erkannt via 'specific selection'")
            return True
    except Exception as e:
        log(f"innerText-Check Fehler: {e}")
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
                        log("April 2026 gefunden.")
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

            # ── 4. Tag 1 klicken via JavaScript ────────────────────
            log("Klicke Tag 1 ...")
            clicked = page.evaluate("""
                () => {
                    const cells = document.querySelectorAll('td, [class*="day"], button');
                    for (const cell of cells) {
                        const txt = (cell.textContent || '').trim();
                        const cls = (cell.className || '').toLowerCase();
                        if (txt === '1'
                            && !cls.includes('disabled')
                            && !cls.includes('prev')
                            && !cls.includes('other')
                            && !cls.includes('grayed')) {
                            cell.click();
                            return true;
                        }
                    }
                    return false;
                }
            """)
            log(f"Tag 1 geklickt: {clicked}")

            # ── 5. Warten und Popup prüfen ──────────────────────────
            log("Warte 6 Sekunden auf Seitenantwort ...")
            page.wait_for_timeout(6000)

            page.screenshot(path="/tmp/step1_after_day_click.png")

            if has_error_popup(page):
                browser.close()
                return {
                    "available": False,
                    "reason": "Datum noch nicht buchbar (Website: 'not available for this specific selection').",
                    "url": BOOKING_URL,
                }

            # ── 6. Zeitslot 8:00 klicken ───────────────────────────
            # Wir klicken AKTIV den 8:00-Slot an — nur wenn er wirklich
            # auswählbar ist kann man darauf klicken
            log("Versuche Zeitslot 8:00 zu klicken ...")
            slot_clicked = page.evaluate("""
                () => {
                    const items = document.querySelectorAll('li, [class*="slot"], [class*="time"]');
                    for (const el of items) {
                        const txt = (el.textContent || '').trim();
                        const cls = (el.className || '').toLowerCase();
                        if ((txt.includes('8:00') || txt.includes('08:00'))
                            && !cls.includes('disabled')
                            && !cls.includes('sold')
                            && !cls.includes('full')) {
                            el.click();
                            return 'geklickt: ' + txt;
                        }
                    }
                    return null;
                }
            """)
            log(f"Slot-Klick Ergebnis: {slot_clicked}")

            page.wait_for_timeout(3000)

            # Popup nach Slot-Klick prüfen
            if has_error_popup(page):
                browser.close()
                return {
                    "available": False,
                    "reason": "Datum noch nicht buchbar (nach Slot-Auswahl).",
                    "url": BOOKING_URL,
                }

            # ── 7. Continue klicken ─────────────────────────────────
            log("Klicke Continue ...")
            try:
                page.click("text=Continue", timeout=5000)
                page.wait_for_timeout(4000)
            except Exception:
                log("Kein Continue-Button gefunden.")

            page.screenshot(path="/tmp/step2_after_continue.png")

            # Popup nach Continue prüfen
            if has_error_popup(page):
                browser.close()
                return {
                    "available": False,
                    "reason": "Datum noch nicht buchbar (nach Continue).",
                    "url": BOOKING_URL,
                }

            # ── 8. Prüfe ob wir die Ticket-MENGENAUSWAHL erreicht haben ──
            # Das ist der EINZIGE verlässliche Beweis für echte Verfügbarkeit:
            # Auf der Mengenauswahlseite gibt es ein "Add to Basket" oder
            # Zahlen-Eingabefelder für Tickets.
            log("Prüfe ob Mengenauswahl erreichbar ist ...")

            visible_text = page.evaluate("() => document.body.innerText").lower()
            log(f"Seitentext nach Continue (300 Zeichen): {visible_text[:300]}")

            page.screenshot(path="/tmp/step3_ticket_select.png")

            # Prüfe auf Mengenauswahl-Elemente
            reached_quantity = page.evaluate("""
                () => {
                    const text = document.body.innerText.toLowerCase();
                    // "Add to Basket" oder "Choose your tickets" = Mengenauswahl erreicht
                    return text.includes('add to basket')
                        || text.includes('choose your tickets')
                        || text.includes('single ticket')
                        || document.querySelector('input[type="number"]') !== null
                        || document.querySelector('[class*="quantity"]') !== null
                        || document.querySelector('[class*="ticket-count"]') !== null;
                }
            """)

            if has_error_popup(page):
                browser.close()
                return {
                    "available": False,
                    "reason": "Datum noch nicht buchbar.",
                    "url": BOOKING_URL,
                }

            browser.close()

            if reached_quantity:
                return {
                    "available": True,
                    "reason": "Buchungsflow erfolgreich durchlaufen — Ticketauswahl erreichbar!",
                    "url": BOOKING_URL,
                }
            else:
                return {
                    "available": False,
                    "reason": "Datum noch nicht buchbar (Mengenauswahl nicht erreichbar).",
                    "url": BOOKING_URL,
                }

        except Exception as e:
            log(f"Fehler: {e}")
            import traceback; traceback.print_exc()
            try: page.screenshot(path="/tmp/akropolis_error.png")
            except Exception: pass
            try: browser.close()
            except Exception: pass
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
