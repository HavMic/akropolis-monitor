import anthropic
import smtplib
import json
import os
import sys
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
    log("Verbinde mit Anthropic API …")
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=600,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        system=(
            "Du bist ein Ticket-Verfügbarkeits-Checker für die Akropolis in Athen. "
            "Suche auf etickets.tap.gr nach verfügbaren Tickets. "
            "Antworte AUSSCHLIESSLICH mit einem gültigen JSON-Objekt – kein Text davor oder danach, keine Markdown-Blöcke:\n"
            '{"available": true/false, "reason": "kurze Begründung auf Deutsch max 200 Zeichen", "url": "direkte Buchungs-URL oder leer"}'
        ),
        messages=[{
            "role": "user",
            "content": (
                f"Prüfe jetzt ob auf etickets.tap.gr Tickets buchbar sind für:\n"
                f"- Datum: {TARGET_DATE}\n"
                f"- Zeitfenster: {TARGET_TIME}\n"
                f"- {ADULTS} Erwachsene + {CHILDREN} Kinder\n"
                "Gib nur das JSON zurück."
            )
        }]
    )

    raw = ""
    for block in response.content:
        if block.type == "text":
            raw = block.text.strip()
            break

    log(f"API-Antwort (roh): {raw[:300]}")

    # JSON extrahieren (auch wenn Markdown-Fences vorhanden)
    raw = raw.replace("```json", "").replace("```", "").strip()
    match_start = raw.find("{")
    match_end   = raw.rfind("}") + 1
    if match_start != -1 and match_end > match_start:
        raw = raw[match_start:match_end]

    try:
        result = json.loads(raw)
    except json.JSONDecodeError as e:
        log(f"JSON-Parse-Fehler: {e} – verwende Fallback")
        result = {"available": False, "reason": "Antwort konnte nicht geparst werden.", "url": ""}

    return result


def send_email(subject: str, body: str):
    sender       = os.environ["GMAIL_SENDER"]
    app_password = os.environ["GMAIL_APP_PASSWORD"]

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"]    = sender
    msg["To"]      = ALERT_EMAIL

    log(f"Sende E-Mail '{subject}' an {ALERT_EMAIL} …")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(sender, app_password)
        smtp.send_message(msg)
    log("E-Mail erfolgreich gesendet.")


def build_body(result: dict, available: bool) -> str:
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    url = result.get("url") or BOOKING_URL

    if available:
        return (
            f"ALARM: Akropolis-Tickets sind JETZT verfügbar!\n\n"
            f"Datum:    {TARGET_DATE}\n"
            f"Uhrzeit:  {TARGET_TIME}\n"
            f"Personen: {ADULTS} Erwachsene + {CHILDREN} Kinder\n\n"
            f">>> Jetzt sofort buchen: {url}\n\n"
            f"Info: {result.get('reason', '')}\n\n"
            f"Bitte nicht zu lange warten – Tickets können schnell ausverkauft sein!\n\n"
            f"Geprüft am: {now}\n"
            f"(Automatischer Alarm vom Akropolis Ticket Monitor)"
        )
    else:
        return (
            f"Der Akropolis Ticket Monitor hat geprüft – noch keine Tickets buchbar.\n\n"
            f"Datum:    {TARGET_DATE}\n"
            f"Uhrzeit:  {TARGET_TIME}\n"
            f"Personen: {ADULTS} Erwachsene + {CHILDREN} Kinder\n\n"
            f"Grund: {result.get('reason', 'Keine Angabe')}\n\n"
            f"Buchungsseite: {BOOKING_URL}\n\n"
            f"Nächste Prüfungen: täglich 09:00, 12:00 und 15:00 Uhr.\n\n"
            f"Geprüft am: {now}\n"
            f"(Automatischer Status vom Akropolis Ticket Monitor)"
        )


def main():
    log("=== Akropolis Ticket Monitor gestartet ===")

    # Pflicht-Umgebungsvariablen prüfen
    missing = [v for v in ("ANTHROPIC_API_KEY", "GMAIL_SENDER", "GMAIL_APP_PASSWORD") if not os.environ.get(v)]
    if missing:
        log(f"FEHLER: Fehlende Umgebungsvariablen: {', '.join(missing)}")
        sys.exit(1)

    result    = check_availability()
    available = result.get("available", False)

    log(f"Verfügbar: {available} | Grund: {result.get('reason', '—')}")

    subject = "Karten Akropolis JETZT" if available else "Keine Verfügbarkeit"
    body    = build_body(result, available)
    send_email(subject, body)

    log("=== Monitor-Lauf abgeschlossen ===")


if __name__ == "__main__":
    main()
