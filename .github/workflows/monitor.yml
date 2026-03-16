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
            "Du bist ein Ticket-Verfuegbarkeits-Checker fuer die Akropolis in Athen. "
            "Suche auf etickets.tap.gr nach verfuegbaren Tickets fuer das angegebene Datum. "
            "Antworte AUSSCHLIESSLICH mit einem gueltigen JSON-Objekt - kein Text davor oder danach:\n"
            '{"available": true/false, "reason": "kurze Begruendung max 200 Zeichen", "url": "Buchungs-URL oder leer"}'
        ),
        messages=[{
            "role": "user",
            "content": (
                f"Pruefe jetzt ob auf etickets.tap.gr Tickets buchbar sind fuer:\n"
                f"- Datum: {TARGET_DATE}\n"
                f"- Zeitfenster: {TARGET_TIME}\n"
                f"- {ADULTS} Erwachsene + {CHILDREN} Kinder\n"
                "Gib nur das JSON zurueck, kein anderer Text."
            )
        }]
    )

    log(f"API-Antwort: {len(response.content)} Block(s)")

    raw = ""
    for block in response.content:
        log(f"  Block-Typ: {block.type}")
        if block.type == "text":
            raw = block.text.strip()
            log(f"  Text (erste 300 Zeichen): {raw[:300]}")
            break

    if not raw:
        log("WARNUNG: Kein Text-Block in Antwort.")
        return {"available": False, "reason": "Keine Textantwort von der API.", "url": ""}

    raw_clean = raw.replace("```json", "").replace("```", "").strip()
    s = raw_clean.find("{")
    e = raw_clean.rfind("}") + 1

    if s == -1 or e <= s:
        log(f"WARNUNG: Kein JSON gefunden. Rohantwort: {raw[:200]}")
        return {"available": False, "reason": f"Kein JSON: {raw[:100]}", "url": ""}

    json_str = raw_clean[s:e]
    log(f"Extrahiertes JSON: {json_str}")

    try:
        return json.loads(json_str)
    except json.JSONDecodeError as ex:
        log(f"JSON-Fehler: {ex}")
        return {"available": False, "reason": "JSON konnte nicht geparst werden.", "url": ""}


def send_email(subject: str, body: str):
    sender       = os.environ["GMAIL_SENDER"]
    app_password = os.environ["GMAIL_APP_PASSWORD"].replace(" ", "")

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"]    = sender
    msg["To"]      = ALERT_EMAIL

    log(f"Sende E-Mail an {ALERT_EMAIL} (Betreff: {subject}) ...")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(sender, app_password)
        smtp.send_message(msg)
    log("E-Mail erfolgreich gesendet.")


def build_body(result: dict, available: bool) -> str:
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    url = result.get("url") or BOOKING_URL

    if available:
        return (
            f"ALARM: Akropolis-Tickets sind JETZT verfuegbar!\n\n"
            f"Datum:    {TARGET_DATE}\n"
            f"Uhrzeit:  {TARGET_TIME}\n"
            f"Personen: {ADULTS} Erwachsene + {CHILDREN} Kinder\n\n"
            f">>> Jetzt sofort buchen: {url}\n\n"
            f"Info: {result.get('reason', '')}\n\n"
            f"Bitte nicht zu lange warten - Tickets koennen schnell ausverkauft sein!\n\n"
            f"Geprueft am: {now}\n"
            f"(Automatischer Alarm vom Akropolis Ticket Monitor)"
        )
    else:
        return (
            f"Der Akropolis Ticket Monitor hat geprueft - noch keine Tickets buchbar.\n\n"
            f"Datum:    {TARGET_DATE}\n"
            f"Uhrzeit:  {TARGET_TIME}\n"
            f"Personen: {ADULTS} Erwachsene + {CHILDREN} Kinder\n\n"
            f"Grund: {result.get('reason', 'Keine Angabe')}\n\n"
            f"Buchungsseite: {BOOKING_URL}\n\n"
            f"Naechste Pruefungen: taeglich 09:00, 12:00 und 15:00 Uhr.\n\n"
            f"Geprueft am: {now}\n"
            f"(Automatischer Status vom Akropolis Ticket Monitor)"
        )


def main():
    log("=== Akropolis Ticket Monitor gestartet ===")

    missing = [v for v in ("ANTHROPIC_API_KEY", "GMAIL_SENDER", "GMAIL_APP_PASSWORD") if not os.environ.get(v)]
    if missing:
        log(f"FEHLER: Fehlende Secrets: {', '.join(missing)}")
        log("Bitte unter Repository > Settings > Secrets and variables > Actions pruefen.")
        sys.exit(1)

    log(f"Secrets OK | GMAIL_SENDER={os.environ['GMAIL_SENDER']}")

    try:
        result = check_availability()
    except Exception as ex:
        log(f"FEHLER bei API-Abfrage: {ex}")
        traceback.print_exc()
        result = {"available": False, "reason": f"API-Fehler: {str(ex)[:150]}", "url": ""}

    available = result.get("available", False)
    log(f"Ergebnis -> verfuegbar={available} | {result.get('reason', '-')}")

    subject = "Karten Akropolis JETZT" if available else "Keine Verfuegbarkeit"
    body    = build_body(result, available)

    try:
        send_email(subject, body)
    except smtplib.SMTPAuthenticationError:
        log("FEHLER: Gmail-Authentifizierung fehlgeschlagen!")
        log("Ursachen: falsches App-Passwort, 2FA nicht aktiv, oder kein App-Passwort fuer 'Mail'.")
        sys.exit(1)
    except Exception as ex:
        log(f"FEHLER beim E-Mail-Versand: {ex}")
        traceback.print_exc()
        sys.exit(1)

    log("=== Monitor-Lauf erfolgreich abgeschlossen ===")


if __name__ == "__main__":
    main()
