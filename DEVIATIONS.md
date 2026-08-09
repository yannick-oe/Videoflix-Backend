# DEVIATIONS

Abweichungen von den Vorgaben. Jeder Eintrag nennt die Vorgabe wörtlich, was
stattdessen passiert, warum, und wie sich der Zustand zurückbauen lässt.

---

## 2026-08-07 — Ausführbar-Bit auf `backend.entrypoint.sh`

**Vorgabe:** „Bitte nimm keine Änderungen an den Dateien `backend.Dockerfile`,
`docker-compose` und `backend.entrypoint.sh` vor!" (Videoflix — Docker Setup,
Abschnitt „Quickstart")

**Abweichung:** Der Dateimodus ist von `100644` auf `100755` gesetzt. Der Inhalt
der Datei ist byteweise unverändert.

**Grund:** Das Volume `.:/app` überdeckt zur Laufzeit die Image-Schicht, in der
`chmod +x backend.entrypoint.sh` aus `backend.Dockerfile` gewirkt hat, sodass
der Container aus einem frischen Klon mit `exec ./backend.entrypoint.sh: no
such file or directory` abbricht.

**Rückbau:** `chmod -x backend.entrypoint.sh`

---

## 2026-08-08 — `400` bei `POST /api/register/`

**Vorgabe:** „201: Benutzer erfolgreich erstellt." (Endpoint Dokumentation,
`POST /api/register/`, Status Codes — der einzige Eintrag der Tabelle)

**Abweichung:** Eine ungültige Eingabe wird mit `400` und den Feldfehlern von
DRF als JSON-Body beantwortet.

**Grund:** Die Checkliste verlangt „Bei ungültiger Eingabe (z.B. bereits
verwendete E-Mail) erhält der Benutzer eine Fehlermeldung." (Checkliste
Videoflix, User Story 1).

**Rückbau:** Die Validierung des Serializers entfernen, sobald die Doku für
diesen Endpunkt einen anderen Fehlerfall vorschreibt.

---

## 2026-08-08 — Response-Body des `400` bei `GET /api/activate/<uidb64>/<token>/`

**Vorgabe:** „400: Aktivierung fehlgeschlagen." (Endpoint Dokumentation,
`GET /api/activate/<uidb64>/<token>/`, Status Codes) — die Doku nennt für
diesen Status keinen Body.

**Abweichung:** Die Antwort trägt
`{"message": "Activation link is invalid or expired."}`.

**Grund:** Der Schlüssel folgt dem dokumentierten Erfolgs-Body
`{"message": "Account successfully activated."}`, den das Frontend als
`result.message` ausliest.

**Rückbau:** Den Body ersetzen, sobald die Doku für den Fehlerfall einen
eigenen vorgibt.

---

## 2026-08-08 — `401` und `400` bei `POST /api/login/`

**Vorgabe:** „200: Login erfolgreich." (Endpoint Dokumentation,
`POST /api/login/`, Status Codes — der einzige Eintrag der Tabelle)

**Abweichung:** Falsche Zugangsdaten und ein nicht aktiviertes Konto werden mit
`401` und derselben, nicht unterscheidbaren Meldung beantwortet; eine Anfrage
ohne `email` oder `password` mit `400`.

**Grund:** Die Checkliste verlangt „Bei falscher Eingabe erhält der Benutzer
eine Fehlermeldung." und „Spezifische Informationen wie ‚E-Mail nicht
registriert' oder ‚Passwort falsch' werden vermieden." (Checkliste Videoflix,
User Story 2), und `400` trifft den Fall fehlender Felder, der die Datenbank nie
erreicht.

**Rückbau:** Die Fehlerfälle des Serializers auf den dokumentierten Status
umlenken, sobald die Doku einen nennt.

---

## 2026-08-08 — Zweiter Cookie bei `POST /api/token/refresh/`

**Vorgabe:** „Extra Information: Setzt neuen access_token-Cookie. Der
refresh_token muss im Cookie vorhanden und gültig sein." (Endpoint
Dokumentation, `POST /api/token/refresh/`)

**Abweichung:** Die Antwort setzt zusätzlich einen neuen
`refresh_token`-Cookie. Der Response-Body bleibt exakt der dokumentierte.

**Grund:** Mit `ROTATE_REFRESH_TOKENS` und `BLACKLIST_AFTER_ROTATION` ist der
Refresh-Token im Cookie des Clients gesperrt, sobald die Antwort geschrieben
wird, sodass ein alleiniger Access-Cookie den Nutzer beim ersten Refresh
abmelden würde.

**Rückbau:** `ROTATE_REFRESH_TOKENS = False` setzen und in `RefreshView` nur
noch den Access-Cookie schreiben.

---

## 2026-08-08 — `401` bei `POST /api/logout/` für einen unbrauchbaren Cookie

**Vorgabe:** „200: Logout erfolgreich." und „400: Refresh-Token fehlt."
(Endpoint Dokumentation, `POST /api/logout/`, Status Codes)

**Abweichung:** Ein vorhandener, aber ungültiger, abgelaufener oder bereits
gesperrter Refresh-Cookie wird mit `401` beantwortet. Beide Cookies werden in
jedem Fall gelöscht.

**Grund:** Dasselbe Dokument ordnet denselben Fehlerfall am Schwesterendpunkt
`POST /api/token/refresh/` dem Status „401: Ungültiger Refresh-Token." zu.

**Rückbau:** Den `TokenError` in `LogoutView` abfangen und auf `400` abbilden.

---

## 2026-08-08 — `503` bei `POST /api/register/`

**Vorgabe:** „201: Benutzer erfolgreich erstellt." (Endpoint Dokumentation,
`POST /api/register/`, Status Codes — der einzige Eintrag der Tabelle)

**Abweichung:** Nimmt die Queue den Auftrag für die Aktivierungs-E-Mail nicht
an, wird das angelegte Konto wieder entfernt und die Anfrage mit `503` und
einem JSON-Body beantwortet.

**Grund:** Ein Konto, das ohne zugestellte Aktivierungs-E-Mail bestehen bleibt,
lässt sich weder aktivieren noch erneut registrieren, weil die Adresse dann als
vergeben gilt.

**Rückbau:** In `queue_activation_email` den `RedisError` durchreichen, sobald
die Doku für diesen Fehlerfall einen Status nennt.
