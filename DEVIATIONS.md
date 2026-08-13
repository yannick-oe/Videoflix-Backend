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

---

## 2026-08-09 — `400` bei `POST /api/password_confirm/<uidb64>/<token>/`

**Vorgabe:** „200: Passwort erfolgreich geändert." (Endpoint Dokumentation,
`POST /api/password_confirm/<uidb64>/<token>/`, Status Codes — der einzige
Eintrag der Tabelle)

**Abweichung:** Ein unbrauchbarer Link — fehlerhafte `uidb64`, `uidb64` ohne
Konto, ungültiger, bereits verbrauchter oder fremder Token — wird mit `400` und
`{"detail": "Reset link is invalid or expired."}` beantwortet. Ein abweichendes
`confirm_password`, ein von `AUTH_PASSWORD_VALIDATORS` abgelehntes
`new_password` und ein fehlendes Feld werden mit `400` und den Feldfehlern von
DRF beantwortet.

**Grund:** Ein Reset, der nicht stattgefunden hat, darf nicht wie ein
erfolgreicher aussehen; die Ursachen eines unbrauchbaren Links teilen sich eine
Meldung, damit die Antwort nicht verrät, ob zu der `uidb64` ein Konto gehört.

**Rückbau:** Die Fehlerfälle auf den dokumentierten Status umlenken, sobald die
Doku für diesen Endpunkt einen nennt.

---

## 2026-08-13 — Segment-Route zusätzlich ohne abschließenden Schrägstrich

**Vorgabe:** „`GET /api/video/<int:movie_id>/<str:resolution>/<str:segment>/`"
(Endpoint Dokumentation, Überschrift des Segment-Endpunkts)

**Abweichung:** Dieselbe View ist zusätzlich ohne abschließenden Schrägstrich
erreichbar. Die dokumentierte Route bleibt unverändert bestehen; beide Formen
liefern dieselben Bytes und denselben `Content-Type`.

**Grund:** FFmpeg schreibt blanke Dateinamen wie `000.ts` in die Playlist, die
der Player relativ zu ihr auflöst; ohne die zweite Route beantwortet
`APPEND_SLASH` jedes Segment mit einem gemessenen `301` und kostet damit einen
zusätzlichen Roundtrip pro Segment.

**Rückbau:** Die Route `video-segment-bare` aus `video_app/api/urls.py`
entfernen.

---

## 2026-08-13 — `401` an den beiden Streaming-Endpunkten

**Vorgabe:** „200: Manifest erfolgreich geliefert." und „404: Video oder
Manifest nicht gefunden." (Endpoint Dokumentation,
`GET /api/video/<int:movie_id>/<str:resolution>/index.m3u8`, Status Codes — die
einzigen Einträge der Tabelle), dazu „200: Segment erfolgreich geliefert." und
„404: Video oder Segment nicht gefunden." (ebenda, Segment-Endpunkt).

**Abweichung:** Eine Anfrage ohne gültigen `access_token`-Cookie wird an beiden
Endpunkten mit `401` und `{"detail": "Authentication credentials were not
provided."}` beantwortet.

**Grund:** Beide Abschnitte verlangen „Permissions: JWT-Authentifizierung
erforderlich", nennen für deren Fehlen aber keinen Status; dasselbe Dokument
ordnet ihn am Schwesterendpunkt `GET /api/video/` als „401: Nicht
authentifiziert." zu.

**Rückbau:** Die Fehlerfälle auf den dokumentierten Status umlenken, sobald die
Doku für diese Endpunkte einen nennt.
