import anthropic
import smtplib
import json
import os
import sys
import traceback
from email.mime.text import MIMEText
from datetime import datetime

# ── Konfiguration ──────────────────────────────────────────────
TARGET_DATE   = "1. April 2026"
TARGET_TIME   = "08:00 Uhr"
ADULTS        = 2
CHILDREN      = 3
ALERT_EMAIL   = "havas.michael@gmail.com"
BOOKING_URL   = "https://etickets.tap.gr/"
# ──────────────────────────────────────────────────────────────


def log(msg: str):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def check_availability() -> dict:
    log("Verbinde mit Anthropic API ...")
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    response = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=600,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        system=(
            "Du bist ein Ticket-Checker. Suche ob auf etickets.tap.gr "
            "Tickets buchbar sind. Antworte NUR mit JSON:\n"
            '{"available": true/false, "reason": "Begruendung", "url": "URL oder leer"}'
        ),
        messages=[{
            "role": "user",
            "content": (
                f"Sind auf etickets.tap.gr Tickets buchbar fuer:\n"
                f"- Datum: {TARGET_DATE}\n"
                f"- Zeit: {TARGET_TIME}\n"
                f"- {ADULTS} Erwachsene + {CHILDREN} Kinder\n"
                "Nur JSON zurueckgeben."
            )
        }]
    )

    raw = ""
    for block in response.content:
        log(f"Block: {block.type}")
        if block.type == "text":
            raw = block.text.strip()
            log(f"Antwort: {raw[:400]}")
            break

    if not raw:
        return {"available": False, "reason": "Leere API-Antwort.", "url": ""}

    raw = raw.replace("```json", "").replace("```", "").strip()
    s = raw.find("{")
    e = raw.rfind("}") + 1
    if s == -1 or e <= s:
        return {"available": False, "reason": f"Kein JSON: {raw[:100]}", "url": ""}

    try:
        return json.loads(raw[s:e])
    except json.JSONDecodeError as ex:
        return {"available": False, "reason": f"JSON-Fehler: {ex}", "url": ""}


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
            f"Datum:    {TARGET_DATE}\n"
            f"Uhrzeit:  {TARGET_TIME}\n"
            f"Personen: {ADULTS} Erwachsene + {CHILDREN} Kinder\n\n"
            f">>> Jetzt buchen: {url}\n\n"
            f"Info: {result.get('reason', '')}\n\n"
            f"Geprueft: {now}"
        )
    else:
        return (
            f"Akropolis Ticket Monitor - Statusbericht\n\n"
            f"Datum:    {TARGET_DATE}\n"
            f"Uhrzeit:  {TARGET_TIME}\n"
            f"Personen: {ADULTS} Erwachsene + {CHILDREN} Kinder\n\n"
            f"Status: NICHT verfuegbar\n"
            f"Grund:  {result.get('reason', 'Keine Angabe')}\n\n"
            f"Buchungsseite: {BOOKING_URL}\n"
            f"Naechste Pruefungen: 09:00 / 12:00 / 15:00 Uhr\n\n"
            f"Geprueft: {now}"
        )


def main():
    log("=== Akropolis Ticket Monitor ===")

    # Secrets pruefen
    missing = [v for v in ("ANTHROPIC_API_KEY", "GMAIL_SENDER", "GMAIL_APP_PASSWORD")
               if not os.environ.get(v)]
    if missing:
        log(f"FEHLER: Secrets fehlen: {', '.join(missing)}")
        log("Bitte in GitHub: Settings > Secrets and variables > Actions")
        sys.exit(1)

    sender = os.environ["GMAIL_SENDER"]
    pw_len = len(os.environ["GMAIL_APP_PASSWORD"].replace(" ", ""))
    log(f"Secrets vorhanden: GMAIL_SENDER={sender}, APP_PASSWORD Laenge={pw_len} Zeichen")

    # Schritt 1: Verfuegbarkeit pruefen
    api_error = None
    try:
        result = check_availability()
    except Exception as ex:
        api_error = str(ex)
        log(f"API-Fehler: {api_error}")
        traceback.print_exc()
        result = {"available": False, "reason": f"API-Fehler: {api_error[:150]}", "url": ""}

    available = result.get("available", False)
    log(f"Verfuegbar: {available} | {result.get('reason', '-')}")

    # Schritt 2: E-Mail senden
    subject = "Karten Akropolis JETZT" if available else "Keine Verfuegbarkeit"
    body    = build_body(result, available)

    try:
        send_email(subject, body)
    except smtplib.SMTPAuthenticationError as ex:
        log("=" * 50)
        log("GMAIL AUTHENTIFIZIERUNG FEHLGESCHLAGEN!")
        log(f"Fehler: {ex}")
        log("")
        log("Checkliste:")
        log(f"  1. GMAIL_SENDER = '{sender}' - ist das deine Gmail-Adresse?")
        log(f"  2. APP_PASSWORD hat {pw_len} Zeichen - sollten 16 sein")
        log("  3. Ist 2-Faktor-Authentifizierung bei Gmail aktiv?")
        log("  4. Wurde das App-Passwort unter myaccount.google.com/apppasswords erstellt?")
        log("  5. NICHT dein normales Gmail-Passwort verwenden!")
        log("=" * 50)
        sys.exit(1)
    except Exception as ex:
        log(f"E-Mail-Fehler: {ex}")
        traceback.print_exc()
        sys.exit(1)

    log("=== Lauf abgeschlossen ===")


if __name__ == "__main__":
    main()
