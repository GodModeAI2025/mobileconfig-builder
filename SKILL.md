---
name: mobileconfig-builder
description: "Erstellt produktionsreife .mobileconfig-Dateien (Apple Configuration Profiles) für macOS, iOS, iPadOS, tvOS, watchOS und visionOS. Holt die YAML-Schemas aus github.com/apple/device-management (Branch `release`) in einen lokalen Cache und validiert jeden Payload gegen diesen Cache-Stand, der liegen bleibt, bis `fetch_schema.py --refresh` ihn neu holt. Führt bei Bedarf einen Interview-Flow (Plattform → PayloadType → Pflichtfelder) und erzeugt eine korrekt strukturierte, optional PKCS#7-signierte .mobileconfig zum Direkt-Aufspielen via MDM, Profile Manager, AirDrop oder USB. Verwende diesen Skill, sobald Apple-Geräte konfiguriert werden sollen — auch ohne das Wort 'mobileconfig'. Trigger sind etwa 'Configuration Profile', 'MDM-Profil', 'WLAN/VPN/Mail-Profil für Mac/iPad', 'Restrictions', 'Apple Intelligence deaktivieren', 'FileVault per Profil', 'Software-Update-Policy', 'TCC/Privacy Permissions', 'Profil signieren', 'PayloadType com.apple.*', 'managed preferences', 'auf Gerät spielen'. Auch bei einzelner Einstellung, die per Profil erzwungen werden soll."
---

# mobileconfig-builder

Generiert valide `.mobileconfig`-Dateien gegen das Apple Device Management Schema.

## Was dieser Skill macht

`.mobileconfig`-Dateien sind Apple Configuration Profiles: signierte oder unsignierte XML-Property-Lists, die ein iPhone, iPad, Mac, Apple TV oder eine Apple Watch konfigurieren — von WLAN über VPN, E-Mail, Zertifikaten, Restrictions bis zu Software-Update-Policies. Sie werden über MDM, Apple Configurator, AirDrop, USB oder per Doppelklick auf das Gerät gespielt.

Die offiziell maßgebliche Quelle für die Struktur dieser Profile ist **[github.com/apple/device-management](https://github.com/apple/device-management)** (default-Branch: `release`). Dort liegen für jeden Profile-Type eine YAML-Schema-Datei mit allen Keys, Required-Markern, Typen, Wertebereichen und OS-Support-Matrix. Dieser Skill arbeitet gegen dieses Schema, statt sich auf trainierte Erinnerung an die Apple-Doku zu verlassen. Er liest es aus einem lokalen Cache unter `~/.cache/mobileconfig-builder/<branch>/`. Eine einmal geladene Datei bleibt dort liegen, ohne Ablauf und ohne ETag-Vergleich, bis `fetch_schema.py --refresh` sie neu holt, und der Workflow unten läuft mit `--offline` bewusst nur gegen den Cache. Der Stand ist also so aktuell wie der letzte Fetch.

**Branch-Strategie:** Apple veröffentlicht neben `release` einen Seed-Branch für die kommende OS-Generation, derzeit `seed_OS_27_0`. Welche Branches gerade existieren, zeigt `git ls-remote --heads https://github.com/apple/device-management.git`. Default ist `release`; den Seed-Stand holen die Skripte mit `--branch seed_OS_27_0` in ein eigenes Cache-Verzeichnis. Frag den User nur dann nach dem Branch, wenn er von Beta- oder Seed-Versionen spricht.

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
| Zertifikat | `com.apple.security.pkcs1` / `.pkcs12` / `.root` (Bytes über `__base64__` oder `__file__`, siehe Spezialfälle) |
| FileVault | `com.apple.MCX.FileVault2` |
| Software-Update | `com.apple.SoftwareUpdate` |
| Profile Removal Password | `com.apple.profileRemovalPassword` |
| Privacy Preferences (TCC) | `com.apple.TCC.configuration-profile-policy` |
| Software-Update Enforcement | `com.apple.SoftwareUpdate` |

Bei mehreren Use-Cases: ein einziges Profil mit mehreren Payloads bauen — das ist Apple-Standard.

**Drittanbieter-Domains.** Apples Schema beschreibt nur Apple-Domains. Chrome
(`com.google.Chrome`), Office (`com.microsoft.office`), Zoom
(`us.zoom.config`) und der Rest stehen dort nicht und werden unter
`--validate-strict` als unbekannter PayloadType abgelehnt. Für die gibt es
`--manifests`, das ProfileManifests als zweite Quelle zuschaltet:

```bash
python3 scripts/inspect_payload.py com.google.Chrome --manifests
python3 scripts/build_mobileconfig.py spec.json -o profil.mobileconfig \
  --validate-strict --manifests
```

Apple gewinnt: gefragt wird die zweite Quelle nur, wenn Apple den PayloadType
gar nicht kennt. Sag dem User, wenn ein Payload aus ProfileManifests geprüft
wurde. Die Sammlung ist von Mac-Admins gepflegt und nicht von den
Herstellern, hat keine Lizenzangabe und wird deshalb nur zur Laufzeit geladen,
nichts davon liegt im Skill. `--manifests` braucht Netz beim ersten Aufruf je
Domain, danach reicht der Cache. Details in `references/schema-format.md`.

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

Speichere als `<projektname>.json`. Braucht ein Payload ein `<data>`-Feld, etwa bei Zertifikaten, kommen die Bytes über `{"__base64__": "..."}` oder `{"__file__": "ca.der"}` hinein (siehe Spezialfälle).

### Schritt 6 — Build & Validierung

```bash
python3 scripts/build_mobileconfig.py spec.json -o profil.mobileconfig --offline --validate-strict
```

Strikt geprüft wird nicht nur jede Payload gegen ihr eigenes Schema, sondern auch der `meta`-Block gegen `TopLevel.yaml`: ein dort erfundener Key lässt den Build mit Exit-Code 2 abbrechen, bevor eine Datei entsteht.

Bei Validierungsfehlern korrigiere die Spec mit dem User. Nicht-strikt (`ohne --validate-strict`) lässt unbekannte Keys durch — manchmal nötig, wenn Apple einen Key dokumentiert, der noch nicht im Schema ist; aber das ist die Ausnahme.

### Schritt 7 — Signieren

**Regel: unsigniert nur im Labor.** Ein unsigniertes Profil ist zum Ausprobieren auf eigenen Testgeräten da, sonst nirgends. Alles, was auf ein fremdes Gerät, in eine Flotte oder auf einen MDM-Server geht, wird signiert. Ohne Signatur zeigt das Gerät beim Installieren „nicht verifiziert", niemand kann prüfen, wer das Profil gebaut hat, und wer die Datei vor der Installation in die Hände bekommt, kann sie ändern. Viele MDM-Server nehmen unsignierte Profile ohnehin nicht an.

Wenn der User kein Zertifikat hat und trotzdem ausrollen will: nicht stillschweigend unsigniert liefern, sondern die Regel nennen und auf `references/signing.md` verweisen. Signieren ersetzt den Installationsdialog nicht; das Gerät fragt weiter nach und zeigt das Profil nur dann als verifiziert, wenn es der signierenden CA vertraut.

Es gibt zwei Wege. Frag zuerst, wo der Schlüssel liegt.

**Weg 1, Schlüssel liegt im macOS-Schlüsselbund.** Der Regelfall in
Unternehmen: das Signaturzertifikat kommt per SCEP oder ADCS und ist nicht
exportierbar. Dann signiert `security cms`, der Schlüssel bleibt im
Schlüsselbund.

```bash
# Kandidaten zeigen lassen und den User auswählen lassen
security find-identity -v -p smime
security find-identity -v -p basic

python3 scripts/build_mobileconfig.py spec.json \
  -o profil.mobileconfig --offline \
  --sign-identity "Profil-Signer 2026"
```

Nimm `-p smime` oder `-p basic`, nicht `-p codesigning`. Ein Profil-Signer
trägt die EKU `emailProtection` oder gar keine einschränkende EKU und taucht
unter der Code-Signing-Policy nicht auf. Wer dort nachsieht, hält ein
vorhandenes Zertifikat für nicht vorhanden.

Stehen in der Liste zwei Zertifikate mit demselben Namen, lehnt das Werkzeug
ab, und der SHA-1 hilft dort nicht weiter. `security cms -N` wählt allein
über den Namen und nimmt keinen Fingerabdruck entgegen, also ließe sich
hinterher nicht sagen, welches unterschrieben hat. Schlag dann den PEM-Weg
vor oder das Aufräumen des Schlüsselbunds, nicht den Fingerabdruck.

**Weg 2, Schlüssel liegt als PEM-Datei vor.**

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
- Passende EKU am Zertifikat, `emailProtection` oder keine einschränkende, idealerweise von einer auf dem Zielgerät vertrauten CA

**Wichtig:** Niemals private Keys über den Chat einsammeln. User soll Pfade
auf seinem System angeben, oder besser den Namen einer Identität im
Schlüsselbund. Liegt der Schlüssel im Schlüsselbund, schlag `--sign-identity`
vor statt `--sign-cert`: dann muss ihn niemand zum Signieren exportieren.
Beim ersten Aufruf fragt macOS in einem Dialog nach der Erlaubnis; über SSH
gibt es diesen Dialog nicht und der Aufruf bleibt hängen.

### Schritt 8 — Liefern + Hinweise zur Installation

Datei dem User geben (`present_files`) und kurz erklären:

- **macOS:** Doppelklick → Systemeinstellungen → Datenschutz & Sicherheit → Profile → Installieren
- **iOS / iPadOS:** Per AirDrop/Mail/Safari öffnen → Einstellungen → „Profil geladen" → Installieren
- **MDM-Distribution:** Profil in Jamf, Kandji, Mosyle, Intune, Profile Manager etc. importieren
- **Bei MDM-Push:** muss meist signiert sein, je nach MDM-Server

**Geheimnisse:** Die erzeugte Datei enthält jedes Passwort und jedes Shared Secret im Klartext, das Plist ist unverschlüsselt. Genauso die Spec-Datei, aus der sie gebaut wurde. Beide gehören nicht in ein Git-Repo, nicht in einen Chat-Verlauf und nicht in einen geteilten Ordner. Sag dem User beim Ausliefern, wo die Datei liegt und dass er sie nach dem Import ins MDM löschen oder dorthin legen soll, wo seine übrigen Zugangsdaten liegen. Wenn eine Spec versehentlich in einem Git-Repo landet: der Secret-Scan `tools/scan_secrets.py` findet sie, er liegt aber nur im Clone von mobileconfig-builder und nicht in diesem installierten Skill.

## Spezialfälle

### Ein vorhandenes Profil prüfen

Bringt der User eine fertige `.mobileconfig` mit, etwa aus Jamf, Intune oder dem Profile Manager, dann geht sie nicht durch den Interview-Flow, sondern direkt in den Validator:

```bash
python3 scripts/validate_mobileconfig.py profil.mobileconfig --offline
```

Erkannt werden XML-Plists, Binär-Plists und signierte PKCS#7-Container; die signierte Form packt `openssl smime -verify -noverify` vorher aus. Zwei Stufen, eine Regel: **Fehler** heisst, das Schema wird verletzt (Pflichtkey fehlt, Typ passt nicht, Wert ausserhalb von `rangelist` oder `range`), Exit-Code 2. **Warnung** heisst, Apples Schema sagt dazu nichts (unbekannter Key, PayloadType ohne Schema, `format`-Regex, doppelte `PayloadUUID`), Exit-Code 1. `--strict` macht aus jeder Warnung einen Fehler.

Wichtig beim Berichten: eine Warnung ist kein Befund gegen das Profil, sondern eine Stelle, an der dieses Werkzeug nichts sagen kann. Fremde Profile tragen regelmässig Keys, die Apple nie beschrieben hat. Nenne dem User beide Stufen getrennt und behaupte nicht, ein Profil mit Warnungen sei kaputt.

Was der Validator nicht leistet: er prüft nicht, ob das Zielsystem die Keys unterstützt (`supportedOS` bleibt unbeachtet), er sagt nicht, wer signiert hat (die Zertifikatskette wird bewusst nicht geprüft), und verschlüsselte Payloads bleiben zu.

### Daten-Felder (`<data>`)

Schema-Type `<data>` (z.B. eingebettete Zertifikate, Push-Token) erwarten Bytes. JSON kennt keinen Bytes-Typ, deshalb gibt es dafür zwei Marker, die der Builder vor der Validierung auflöst:

```json
{
  "PayloadType": "com.apple.security.root",
  "PayloadCertificateFileName": "ca.cer",
  "PayloadContent": {"__file__": "ca.der"}
}
```

`{"__base64__": "MIIDXTCC..."}` nimmt den Base64-Text direkt, Zeilenumbrüche eingeschlossen. `{"__file__": "ca.der"}` liest eine Datei; ein relativer Pfad zählt vom Verzeichnis der Spec aus, nicht vom Arbeitsverzeichnis. Beide funktionieren in beliebiger Tiefe, auch in Listen. Neben dem Marker darf kein weiterer Key stehen, er ersetzt das ganze Dictionary.

In YAML geht weiter der `!!binary`-Tag:

```yaml
payloads:
  - PayloadType: com.apple.security.pkcs12
    PayloadContent: !!binary |
      MIIDXTCC...
```

Drei Dinge zum Sagen, bevor der User sich wundert. Ein nackter Base64-String ohne Marker bleibt eine Zeichenkette und fällt weiter als `expected <data>, got str` durch. Der Marker kopiert die Bytes, wie sie dastehen: eine PEM-Datei landet als PEM im Profil, Apple will an einem Zertifikats-Payload aber DER, also vorher `openssl x509 -in ca.pem -outform der -out ca.der`. Und geprüft wird nur, dass der Wert dekodierbar beziehungsweise die Datei lesbar ist, nicht ob dahinter wirklich ein Zertifikat steckt.

`__file__` nimmt jeden Pfad, den der aufrufende Prozess lesen darf: `~` wird aufgelöst, ein absoluter Pfad bleibt stehen, eine Größengrenze gibt es nicht, und die gelesenen Bytes stehen danach im Klartext im Profil. Eine Spec ist damit so vertrauenswürdig wie ihre Quelle. Eine fremde Spec vor dem Build auf `__file__`-Einträge durchsehen, sonst zieht sie mit `{"__file__": "~/.ssh/id_rsa"}` genau das ins Profil, was dort nicht hingehört.

### Mehrfach-Payloads

Top-Level `PayloadContent` ist ein Array. Beliebig viele Payloads sind erlaubt, solange jeder seinen eigenen `PayloadIdentifier` und `PayloadUUID` hat (macht der Builder automatisch). Beispiele in `assets/examples/`.

### Declarative Device Management (DDM)

Apple's neuere DDM-Deklarationen liegen unter `declarative/declarations/` im Repo, **nicht** unter `mdm/profiles/`. Sie gehen nicht als `.mobileconfig`, sondern werden vom MDM-Server direkt als JSON-Deklarationen ans Gerät geschickt. Dieser Skill baut Profile und nichts sonst.

Wenn der User danach fragt, sag ihm das, aber sag ihm auch, was der
Unterschied praktisch bedeutet, statt nur abzugrenzen:

- Apple beschreibt Profile und Declarations im **selben YAML-Format**, mit
  denselben Feldern. Eine Spec beschreibt eine Absicht, kein Dateiformat, und
  könnte beide Formate speisen. Der Validator hier würde unverändert laufen.
- Für die meisten Payloads gibt es aber **keine Declaration**: der
  `release`-Branch hat 121 PayloadTypes und 36 Configuration-Declarations. Wi-Fi,
  VPN, Zertifikate und Restrictions sind nicht dabei.
- Wo es beide gibt, ist die Abbildung eine Übersetzung und keine
  Umbenennung. Beim Passcode heißt `allowSimple: false` in DDM
  `RequireComplexPasscode: true`, also mit umgedrehtem Wert.
- `com.apple.configuration.legacy` nimmt eine `ProfileURL` entgegen, ein
  Profil bleibt darin ein Profil. Das ist der Weg, ein Profil in einer
  DDM-Ausrollung zu benutzen, ohne so zu tun, als wäre es eine Declaration.

Details in `references/ddm.md`. Behaupte nicht, der Skill könne DDM, und
schreib keine Declaration von Hand zusammen, die nicht gegen ein Schema
geprüft ist.

## Skript-Referenz

| Skript | Zweck |
|---|---|
| `scripts/fetch_schema.py` | Lädt/cached YAML-Schemas vom GitHub-Repo. Unterstützt `--offline`, `--from-clone`, `--list`. |
| `scripts/inspect_payload.py` | Zeigt Keys/Pflichtfelder/Typen eines PayloadTypes. Unterstützt OS-Filter, Required-Only und mit `--manifests` auch Drittanbieter-Domains. |
| `scripts/build_mobileconfig.py` | Baut & validiert das Profil. Erzeugt unsignierte oder PKCS#7-signierte `.mobileconfig`. |
| `scripts/validate_mobileconfig.py` | Prüft eine fertige `.mobileconfig`, egal woher sie kommt. Liest XML-Plists, Binär-Plists und signierte PKCS#7-Container. |
| `evals/run_tests.py` | Regressions-Test-Suite mit 10 realistischen Test-Cases (siehe unten). |

## Beispiele

`assets/examples/wifi_guest.json` — einfaches WPA-WLAN

`assets/examples/classroom_ipad.json` — WLAN + iPadOS-Restrictions kombiniert

## Tests / Evals

Der Skill bringt eine eigene Test-Suite mit, die nach jeder Änderung zeigen soll, ob die vier Skripte (fetch/inspect/build/validate) noch das tun, was die SKILL.md verspricht. Format der Test-Cases folgt dem Schema von Anthropic's `skill-creator` (`evals/evals.json`).

```bash
python3 evals/run_tests.py        # alle 10 Evals
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
| 8 | `profilemanifests-normalisierung` | Übersetzung eines ProfileManifests in Apples Schema-Form: Domain, Plattform, Typen, Pflichtangabe, Wertelisten, Bereiche, Regex, Verschachtelung. Bedienelemente von ProfileCreator und die CommonPayloadKeys fallen raus. Eine Spec gegen das Manifest baut strikt durch, ein erfundener Key wird abgelehnt. Das Manifest im Test ist erfunden, es liegt keines aus dem fremden Repo hier. |
| 7 | `signing-error-paths` | Fehlerpfade beider Signier-Wege, auf jeder Plattform prüfbar: unbekannte Schlüsselbund-Identität und nicht existierende PEM-Datei enden mit Exit-Code 2, mit Meldung statt Traceback und ohne Rückstände. Insbesondere bleibt keine unsignierte Zwischendatei mit dem WLAN-Passwort liegen, und beim zweiten Bau auf denselben Pfad überlebt das dort liegende gültige Profil einen gescheiterten Signier-Versuch. Die Schlüsselbund-Checks decken die Vorabprüfung ab, nicht das Aufräumen: dort wird abgebrochen, bevor eine Datei entsteht. Den Ausgabepfad prüft der PEM-Weg. Der Erfolgsfall des Schlüsselbund-Wegs ist nicht automatisiert, er braucht eine Identität im Schlüsselbund. |
| 9 | `validate-mobileconfig` | Der Validator gegen ein fertiges Profil: ein selbst gebautes läuft mit Exit 0 durch, ein erfundener Key ist eine Warnung mit Exit 1 und mit `--strict` ein Fehler mit Exit 2, ein Wert ausserhalb der `rangelist` ist auch ohne `--strict` ein Fehler, ein erfundener Top-Level-Key wird als `top-level` gemeldet und nicht als Payload-Fund, ein PayloadType ohne Schema gilt als ungeprüft statt als falsch, `--format json` liefert Stufe, Pfad und Exit-Code, und eine Datei, die kein Profil ist, endet mit einer Meldung statt mit einem Traceback. |
| 10 | `daten-marker-in-json-spec` | `{"__base64__": ...}` und `{"__file__": ...}` werden vor der Validierung zu Bytes, in beliebiger Tiefe und in Listen. Die Bytes im Profil sind Byte für Byte das Dekodierte beziehungsweise der Dateiinhalt. Kaputtes Base64, ein nicht lesbarer Pfad und ein Marker neben einem anderen Key enden mit Exit-Code 2, ohne Ausgabedatei und ohne Traceback. Ein nackter Base64-String bleibt eine Zeichenkette. |

Wenn nach einer Schema-Aktualisierung (`--refresh`) Eval 5 plötzlich weniger Einträge hat, hat Apple etwas am Repo geändert — Hinweis lesen, nicht reflexartig den Test anpassen.

**Wann erweitern:** Neuer Use-Case (z.B. VPN-Profil mit Zertifikat) → Eintrag in `evals/evals.json` und passende Test-Funktion in `evals/run_tests.py`. Test-Funktionen sind absichtlich kurz und explizit gehalten, nicht generisch — leichter zu lesen als ein Mini-Framework.

## Weiterführende Doku

- `references/schema-format.md` — Erklärung des Apple-YAML-Schema-Aufbaus
- `references/payload-cheatsheet.md` — kuratierte Liste der wichtigsten PayloadTypes mit Beispiel-Keys
- `references/signing.md` — Signieren über PEM-Dateien oder den macOS-Schlüsselbund, Zertifikatswahl, Trust-Chains, Fehlerdiagnose
- `references/data-fields.md` — `<data>`-Felder und Base64
- `references/ddm.md` — Declarative Device Management: was anders ist, was sich abbilden ließe und was nicht
