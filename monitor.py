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


def check_availability() -> dict:
    log("Starte Browser ...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )

        try:
            # Schritt 1: Seite laden
            log(f"Oeffne: {BOOKING_URL}")
            page.goto(BOOKING_URL, timeout=30000, wait_until="networkidle")

            # Schritt 2: "Buy your ticket" klicken
            page.click("text=Buy your ticket", timeout=10000)
            page.wait_for_timeout(2000)

            # Schritt 3: Zu April 2026 navigieren
            log("Navigiere zu April 2026 ...")
            for _ in range(24):
                try:
                    if page.locator("text=April 2026").is_visible(timeout=1500):
                        log("April 2026 gefunden.")
                        break
                except Exception:
                    pass
                try:
                    page.locator("button.next, .next-month, [aria-label*='next' i]").first.click(timeout=2000)
                    page.wait_for_timeout(600)
                except Exception:
                    try:
                        page.locator("button:has-text('›'), button:has-text('>')").first.click(timeout=2000)
                        page.wait_for_timeout(600)
                    except Exception:
                        break

            # Schritt 4: Tag 1 klicken
            log("Klicke Tag 1 ...")
            clicked = False
            for td in page.locator("td").all():
                try:
                    txt = td.inner_text(timeout=500).strip()
                    cls = td.get_attribute("class") or ""
                    if txt == "1" and "disabled" not in cls and "prev" not in cls and "next" not in cls:
                        td.click(timeout=3000)
                        log(f"Tag 1 geklickt (class='{cls}')")
                        clicked = True
                        break
                except Exception:
                    pass
            if not clicked:
                log("Fallback: Klicke erstes td mit '1'")
                page.locator("td").filter(has_text="1").first.click(timeout=5000)

            # Schritt 5: Warten — entweder Popup ODER Zeitslots erscheinen
            log("Warte auf Modal oder Zeitslots (max 8 Sekunden) ...")

            # Warte auf eines von beiden
            modal_selector = "div[role='dialog'], .modal, [class*='modal'], [class*='popup'], [class*='alert'], [class*='warning']"
            slot_selector  = "li:has-text('8:00'), li:has-text('08:00'), [class*='slot']:has-text('8:00')"

            modal_appeared = False
            slots_appeared = False

            try:
                page.wait_for_selector(
                    f"{modal_selector}, {slot_selector}",
                    timeout=8000
                )
                log("Element erschienen — pruefe was es ist ...")
            except PlaywrightTimeout:
                log("Timeout — weder Modal noch Slots erschienen.")

            # Schritt 6: Popup/Modal explizit pruefen
            # Methode A: role='dialog'
            try:
                dialog = page.locator("div[role='dialog']")
                if dialog.is_visible(timeout=2000):
                    dialog_text = dialog.inner_text(timeout=3000).strip()
                    log(f"Dialog gefunden (role=dialog): '{dialog_text[:200]}'")
                    modal_appeared = True
            except Exception:
                pass

            # Methode B: .modal oder aehnliche Klassen
            if not modal_appeared:
                for sel in [".modal", "[class*='modal']", "[class*='popup']", "[class*='Popup']", "[class*='alert']", "[class*='Alert']", "[class*='warning']", "[class*='Warning']"]:
                    try:
                        el = page.locator(sel).first
                        if el.is_visible(timeout=1000):
                            txt = el.inner_text(timeout=2000).strip()
                            log(f"Modal '{sel}' gefunden: '{txt[:200]}'")
                            if len(txt) > 5:
                                modal_appeared = True
                                break
                    except Exception:
                        pass

            # Methode C: Pruefe ob "not available" IRGENDWO auf der Seite steht
            # (auch in versteckten Elementen — evaluate direkt im DOM)
            if not modal_appeared:
                try:
                    found = page.evaluate("""
                        () => {
                            const all = document.querySelectorAll('*');
                            for (const el of all) {
                                if (el.children.length === 0) {
                                    const t = (el.textContent || '').toLowerCase();
                                    if (t.includes('not available for this specific')) {
                                        return el.textContent.trim();
                                    }
                                }
                            }
                            return null;
                        }
                    """)
                    if found:
                        log(f"JavaScript-Suche: Gefunden: '{found}'")
                        modal_appeared = True
                except Exception as e:
                    log(f"JS-Evaluate Fehler: {e}")

            # Methode D: Vollstaendiger HTML-Dump — absolut zuverlaessig
            if not modal_appeared:
                try:
                    html = page.content()
                    if "not available for this specific selection" in html.lower():
                        log("HTML-Dump: 'not available for this specific selection' gefunden!")
                        modal_appeared = True
                    else:
                        log("HTML-Dump: Kein 'not available'-Text im HTML.")
                        # Zeige relevante HTML-Teile fuer Debugging
                        import re
                        matches = re.findall(r'.{0,100}available.{0,100}', html, re.IGNORECASE)
                        for m in matches[:5]:
                            log(f"  HTML-Kontext: {m}")
                except Exception as e:
                    log(f"HTML-Dump Fehler: {e}")

            page.screenshot(path="/tmp/akropolis_screenshot.png")

            if modal_appeared:
                browser.close()
                return {
                    "available": False,
                    "reason": "Datum noch nicht buchbar (Website: 'not available for this specific selection').",
                    "url": BOOKING_URL
                }

            # Schritt 7: Keine Fehlermeldung — Zeitslots pruefen
            log("Kein Fehler-Modal. Pruefe Zeitslots ...")
            try:
                page.click("text=Continue", timeout=5000)
                page.wait_for_timeout(3000)
            except Exception:
                pass

            slot_available = False
            slot_found     = False
            for el in page.locator("li, [class*='slot'], [class*='time']").all():
                try:
                    txt = el.inner_text(timeout=500).strip()
                    cls = el.get_attribute("class") or ""
                    if "8:00" in txt or "08:00" in txt:
                        slot_found = True
                        disabled   = any(w in cls.lower() for w in ["disabled", "sold", "unavail", "full"])
                        log(f"8:00-Slot: '{txt}' | disabled={disabled}")
                        if not disabled:
                            slot_available = True
                        break
                except Exception:
                    pass

            browser.close()

            if slot_available:
                return {"available": True,  "reason": "Zeitslot 8:00 Uhr am 1. April 2026 ist BUCHBAR!", "url": BOOKING_URL}
            elif slot_found:
                return {"available": False, "reason": "Zeitslot 8:00 Uhr ausgebucht.",                   "url": BOOKING_URL}
            else:
                return {"available": False, "reason": "Datum noch nicht buchbar (keine Slots gefunden).", "url": BOOKING_URL}

        except Exception as e:
            log(f"Fehler: {e}")
            import traceback; traceback.print_exc()
            try: page.screenshot(path="/tmp/akropolis_error.png")
            except Exception: pass
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
