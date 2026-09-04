---
name: mobileconfig-builder
description: "Erstellt produktionsreife .mobileconfig-Dateien (Apple Configuration Profiles) für macOS, iOS, iPadOS, tvOS, watchOS und visionOS. Holt Schema/Aufbau live aus github.com/apple/device-management (release branch) und validiert jeden Payload gegen das aktuelle YAML-Schema. Führt bei Bedarf einen Interview-Flow (Plattform → PayloadType → Pflichtfelder) und erzeugt eine korrekt strukturierte, optional PKCS#7-signierte .mobileconfig zum Direkt-Aufspielen via MDM, Profile Manager, AirDrop oder USB. Verwende diesen Skill, sobald Apple-Geräte konfiguriert werden sollen — auch ohne das Wort 'mobileconfig'. Trigger sind etwa 'Configuration Profile', 'MDM-Profil', 'WLAN/VPN/Mail-Profil für Mac/iPad', 'Restrictions', 'Apple Intelligence deaktivieren', 'FileVault per Profil', 'Software-Update-Policy', 'TCC/Privacy Permissions', 'Profil signieren', 'PayloadType com.apple.*', 'managed preferences', 'auf Gerät spielen'. Auch bei einzelner Einstellung, die per Profil erzwungen werden soll."
---

# mobileconfig-builder

Generiert valide `.mobileconfig`-Dateien aus dem aktuellen Apple Device Management Schema.

## Was dieser Skill macht

`.mobileconfig`-Dateien sind Apple Configuration Profiles: signierte oder unsignierte XML-Property-Lists, die ein iPhone, iPad, Mac, Apple TV oder eine Apple Watch konfigurieren — von WLAN über VPN, E-Mail, Zertifikaten, Restrictions bis zu Software-Update-Policies. Sie werden über MDM, Apple Configurator, AirDrop, USB oder per Doppelklick auf das Gerät gespielt.

Die offiziell maßgebliche Quelle für die Struktur dieser Profile ist **[github.com/apple/device-management](https://github.com/apple/device-management)** (default-Branch: `release`). Dort liegen für jeden Profile-Type eine YAML-Schema-Datei mit allen Keys, Required-Markern, Typen, Wertebereichen und OS-Support-Matrix. Dieser Skill arbeitet direkt gegen dieses Schema, statt auf trainierte Erinnerung an die Apple-Doku zu verlassen — d.h. er kennt immer den aktuellen Stand.

**Branch-Strategie:** Apple veröffentlicht öffentlich nur den `release`-Branch. Falls künftig ein Beta-Branch erscheint, fragt Claude beim ersten Lauf nach. Ohne expliziten Wunsch wird `release` verwendet.

## Wann diesen Skill verwenden

Trigger-Phrasen (DE/EN):
- "mobileconfig erstellen / bauen / generieren"
- "Configuration Profile für …"
- "Apple-Profil / MDM-Profil"
- "WLAN-Profil für Mac/iPad", "VPN-Profil", "Mail-Konto-Profil", "Restrictions-Profil"
- "Profil signieren mit Zertifikat"
- "Profile Manager Datei", "auf Gerät aufspielen"
- "PayloadType com.apple.*"
- "managed preferences", "MDM-Payload"

## Workflow (Interview-Modus)

Claude folgt diesen Schritten der Reihe nach. Frage den User pro Schritt nur, was wirklich offen ist — überspringe Fragen, deren Antwort schon im Chat steht.

### Schritt 0 — Schema-Cache vorbereiten (einmalig)

Beim allerersten Lauf in einer Umgebung:

```bash
python3 scripts/fetch_schema.py
```

Lädt alle Profil-Schemas vom `release`-Branch nach `~/.cache/mobileconfig-builder/release/`. Wie viele PayloadTypes daraus entstehen, steht in der Kopfzeile von `python3 scripts/fetch_schema.py --list`; eine feste Zahl steht hier bewusst nicht, weil Apple das Schema laufend ändert. Einzelne Dateien, die nicht geladen werden konnten, meldet das Skript als `WARN` und überspringt sie, der Cache kann also unvollständig sein. Folgeläufe sind offline möglich (`--offline` Flag).

Bei Netzproblemen oder als Alternative: lokalen Clone benutzen:

```bash
git clone --depth 1 https://github.com/apple/device-management.git
python3 scripts/fetch_schema.py --from-clone ./device-management
```

### Schritt 1 — Use-Case verstehen

Frage den User in maximal **einer** Runde:
1. Welche Apple-Plattform(en) soll das Profil unterstützen? (macOS / iOS / iPadOS / tvOS / watchOS / visionOS)
2. Was soll das Profil tun? (WLAN, VPN, E-Mail, Restrictions, Zertifikat, Software-Update, Login-Items, FileVault, …)
3. Wird über MDM ausgerollt oder manuell installiert?
4. Soll signiert werden? (für produktiven Einsatz: ja)

Wenn der User schon detailliert beschrieben hat, was er will: nicht nochmal nachfragen — direkt zu Schritt 2.

### Schritt 2 — Passende PayloadType(s) finden

Liste anschauen:

```bash
python3 scripts/fetch_schema.py --list --offline
```

Wähle den/die passenden `PayloadType`(s). Häufige:

| Use-Case | PayloadType |
|---|---|
| Wi-Fi | `com.apple.wifi.managed` |
| VPN | `com.apple.vpn.managed` |
| Mail-Konto | `com.apple.mail.managed` |
| Exchange | `com.apple.eas.account` |
| Restrictions iOS/iPadOS | `com.apple.applicationaccess` |
| Restrictions macOS | `com.apple.applicationaccess.new` |
| Zertifikat | `com.apple.security.pkcs1` / `.pkcs12` / `.root` |
| FileVault | `com.apple.MCX.FileVault2` |
| Software-Update | `com.apple.SoftwareUpdate` |
| Profile Removal Password | `com.apple.profileRemovalPassword` |
| Privacy Preferences (TCC) | `com.apple.TCC.configuration-profile-policy` |
| Software-Update Enforcement | `com.apple.SoftwareUpdate` |

Bei mehreren Use-Cases: ein einziges Profil mit mehreren Payloads bauen — das ist Apple-Standard.

### Schritt 3 — Schema des PayloadType inspizieren

```bash
python3 scripts/inspect_payload.py com.apple.wifi.managed --os macOS --offline
```

Optionen:
- `--os <iOS|macOS|tvOS|visionOS|watchOS>` — Filter auf Keys, die auf dieser OS unterstützt werden
- `--required-only` — nur Pflichtfelder (Container für Required-Subkeys werden mit angezeigt)
- `--json` — vollständiges Schema als JSON

Der Output zeigt für jeden Key: Typ, ob required, erlaubte Werte (rangelist), Wertebereiche (range), Defaults, OS-Support, eine Kurzbeschreibung.

### Schritt 4 — Pflicht- und gewünschte Keys mit User klären

Frage den User gezielt nach den Werten — **nicht** alle möglichen Keys auflisten, sondern:

1. **Required-Keys** für die gewählten PayloadTypes auflisten und Werte einsammeln (oder vorschlagen, falls aus Kontext ableitbar).
2. **Sinnvolle optionale Keys** für den Use-Case erwähnen (z.B. bei WLAN: `AutoJoin`, `HIDDEN_NETWORK`, `ProxyType`).
3. Kurz validieren: passt der angegebene Wert zum erlaubten Range/zur rangelist?

**Was Claude AUTOMATISCH ausfüllt** (User nicht fragen):
- `PayloadType` der einzelnen Payloads (kommt aus Schritt 2)
- `PayloadVersion: 1`
- `PayloadIdentifier` der einzelnen Payloads (deterministisch aus Top-Level-Identifier abgeleitet)
- `PayloadUUID` (deterministisch aus Identifier — bleibt bei Re-Builds gleich)
- Top-Level `PayloadType: Configuration`, `PayloadVersion: 1`, `PayloadUUID`

**Was Claude vom User braucht:**
- Top-Level `PayloadIdentifier` (Reverse-DNS, z.B. `com.acme.school.classroom-ipad`)
- `PayloadDisplayName` (was im Profil-UI auf dem Gerät erscheint)
- Optional: `PayloadDescription`, `PayloadOrganization`, `PayloadScope` (`System` oder `User`)
- Alle Payload-spezifischen Required-Keys

### Schritt 5 — Spec-Datei zusammenbauen

Erzeuge eine JSON-Spec im folgenden Format:

```json
{
  "meta": {
    "PayloadIdentifier": "com.example.myprofile",
    "PayloadDisplayName": "Mein Profil",
    "PayloadDescription": "Was es macht",
    "PayloadOrganization": "Acme",
    "PayloadScope": "System"
  },
  "payloads": [
    {
      "PayloadType": "com.apple.wifi.managed",
      "PayloadDisplayName": "Office Wi-Fi",
      "SSID_STR": "MeinWLAN",
      "AutoJoin": true,
      "EncryptionType": "WPA2",
      "Password": "..."
    }
  ]
}
```

Speichere als `<projektname>.json`.

### Schritt 6 — Build & Validierung

```bash
python3 scripts/build_mobileconfig.py spec.json -o profil.mobileconfig --offline --validate-strict
```

Strikt geprüft wird nicht nur jede Payload gegen ihr eigenes Schema, sondern auch der `meta`-Block gegen `TopLevel.yaml`: ein dort erfundener Key lässt den Build mit Exit-Code 2 abbrechen, bevor eine Datei entsteht.

Bei Validierungsfehlern korrigiere die Spec mit dem User. Nicht-strikt (`ohne --validate-strict`) lässt unbekannte Keys durch — manchmal nötig, wenn Apple einen Key dokumentiert, der noch nicht im Schema ist; aber das ist die Ausnahme.

### Schritt 7 — Optional: Signieren

Apple-Geräte zeigen unsignierte Profile als „nicht signiert / nicht verifiziert" an. Für produktiven Einsatz mit X.509-Zertifikat signieren:

```bash
python3 scripts/build_mobileconfig.py spec.json \
  -o profil.mobileconfig --offline \
  --sign-cert signer-cert.pem \
  --sign-key signer-key.pem \
  --sign-ca   ca-chain.pem
```

Voraussetzungen:
- Cert und Key im PEM-Format
- `openssl` muss im PATH sein
- Das Zertifikat muss Code-Signing oder ein passendes EKU haben, idealerweise von einer auf dem Zielgerät vertrauten CA

**Wichtig:** Niemals private Keys über den Chat einsammeln. User soll Pfade auf seinem System angeben.

### Schritt 8 — Liefern + Hinweise zur Installation

Datei dem User geben (`present_files`) und kurz erklären:

- **macOS:** Doppelklick → Systemeinstellungen → Datenschutz & Sicherheit → Profile → Installieren
- **iOS / iPadOS:** Per AirDrop/Mail/Safari öffnen → Einstellungen → „Profil geladen" → Installieren
- **MDM-Distribution:** Profil in Jamf, Kandji, Mosyle, Intune, Profile Manager etc. importieren
- **Bei MDM-Push:** muss meist signiert sein, je nach MDM-Server

## Spezialfälle

### Daten-Felder (`<data>`)

Schema-Type `<data>` (z.B. eingebettete Zertifikate, Push-Token) erwarten Bytes. In der JSON-Spec als Base64-String mit Marker übergeben:

```json
{ "PayloadCertificateFileName": "ca.cer",
  "PayloadContent": {"__base64__": "MIIDXTCC..."} }
```

`build_mobileconfig.py` erkennt `__base64__`-Marker noch nicht out-of-the-box — das ist eine bewusste Ausbaustelle. Wenn ein Profil `<data>`-Felder braucht, kann Claude die Spec vor dem Build durch einen kleinen Pre-Processor jagen, der `{"__base64__": "..."}` in echte Bytes konvertiert (siehe `references/data-fields.md`).

### Mehrfach-Payloads

Top-Level `PayloadContent` ist ein Array. Beliebig viele Payloads sind erlaubt, solange jeder seinen eigenen `PayloadIdentifier` und `PayloadUUID` hat (macht der Builder automatisch). Beispiele in `assets/examples/`.

### Declarative Device Management (DDM)

Apple's neuere DDM-Deklarationen liegen unter `declarative/declarations/` im Repo, **nicht** unter `mdm/profiles/`. Sie gehen nicht als `.mobileconfig`, sondern werden vom MDM-Server direkt als JSON-Deklarationen ans Gerät geschickt. Wenn der User danach fragt, weise ihn darauf hin — das ist ein anderer Workflow, den dieser Skill (noch) nicht abdeckt.

## Skript-Referenz

| Skript | Zweck |
|---|---|
| `scripts/fetch_schema.py` | Lädt/cached YAML-Schemas vom GitHub-Repo. Unterstützt `--offline`, `--from-clone`, `--list`. |
| `scripts/inspect_payload.py` | Zeigt Keys/Pflichtfelder/Typen eines PayloadTypes. Unterstützt OS-Filter und Required-Only. |
| `scripts/build_mobileconfig.py` | Baut & validiert das Profil. Erzeugt unsignierte oder PKCS#7-signierte `.mobileconfig`. |
| `evals/run_tests.py` | Regressions-Test-Suite mit 6 realistischen Test-Cases (siehe unten). |

## Beispiele

`assets/examples/wifi_guest.json` — einfaches WPA-WLAN

`assets/examples/classroom_ipad.json` — WLAN + iPadOS-Restrictions kombiniert

## Tests / Evals

Der Skill bringt eine eigene Test-Suite mit, die nach jeder Änderung zeigen soll, ob die drei Skripte (fetch/inspect/build) noch das tun, was die SKILL.md verspricht. Format der Test-Cases folgt dem Schema von Anthropic's `skill-creator` (`evals/evals.json`).

```bash
python3 evals/run_tests.py        # alle 6 Evals
python3 evals/run_tests.py -v     # ausführlich (zeigt jeden Check)
python3 evals/run_tests.py --eval-id 4   # nur einen
```

Die Suite prüft konkret:

| # | Eval | Was getestet wird |
|---|------|---|
| 1 | `wifi-guest` | Standard-Pfad: WPA-WLAN aus Beispiel-Spec → valide Plist mit korrekten Typen, deterministischen UUIDs, allen Top-Level-Pflichtfeldern. |
| 2 | `disable-apple-intelligence` | Realer Use-Case: 6 Apple-Intelligence-Restrictions auf macOS auf `false` setzen — alle Werte echte Booleans, keine iOS-only Keys leaken in macOS-Profile. |
| 3 | `classroom-ipad-multi-payload` | Zwei Payloads (WLAN + Restrictions) in einem Profil, eindeutige UUIDs, beide Identifier reverse-DNS. |
| 4 | `invalid-input-rejected` | Negativ-Test: kaputter Input (ungültiger EncryptionType, falscher Typ für AutoJoin) MUSS in `--validate-strict` mit Exit-Code 2 abbrechen, dem dokumentierten Validierungs-Fehlschlag. Auf stderr steht ein Report unter `Validation issues:`, der EncryptionType und AutoJoin benennt, kein Traceback. **Keine** Output-Datei. |
| 5 | `list-payload-types` | `fetch_schema.py --list` listet ≥50 Payloads aus dem Cache, sortiert, Top-Hits sind enthalten. |
| 6 | `unknown-top-level-key-rejected` | Ein erfundener Key im `meta`-Block bricht strikt mit Exit-Code 2 ab, gemeldet als `top-level: unknown key '...'` und nicht als Payload-Fund, ohne Output-Datei. Ohne `--validate-strict` baut dieselbe Spec weiter durch, und `wifi_guest.json` bleibt strikt grün. |

Wenn nach einer Schema-Aktualisierung (`--refresh`) Eval 5 plötzlich weniger Einträge hat, hat Apple etwas am Repo geändert — Hinweis lesen, nicht reflexartig den Test anpassen.

**Wann erweitern:** Neuer Use-Case (z.B. VPN-Profil mit Zertifikat) → Eintrag in `evals/evals.json` und passende Test-Funktion in `evals/run_tests.py`. Test-Funktionen sind absichtlich kurz und explizit gehalten, nicht generisch — leichter zu lesen als ein Mini-Framework.

## Weiterführende Doku

- `references/schema-format.md` — Erklärung des Apple-YAML-Schema-Aufbaus
- `references/payload-cheatsheet.md` — kuratierte Liste der wichtigsten PayloadTypes mit Beispiel-Keys
- `references/signing.md` — Hinweise zu Code-Signing-Zertifikaten und Trust-Chains
