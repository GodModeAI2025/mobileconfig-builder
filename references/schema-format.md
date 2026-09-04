# Apple Device Management YAML Schema — Format

Quelle: https://github.com/apple/device-management/blob/release/docs/schema.md

## Top-Level eines Schema-Files

```yaml
title: ...           # Lesbarer Titel
description: ...     # Kurzbeschreibung
payload:             # Metadaten zum Payload als Ganzes
  payloadtype: com.apple.wifi.managed
  supportedOS:
    iOS:    { introduced: '4.0', multiple: true, … }
    macOS:  { introduced: '10.7', devicechannel: true, userchannel: true, … }
    tvOS:   { introduced: '9.0', … }
    visionOS: { introduced: '1.0', … }
    watchOS:  { introduced: '3.2', … }
payloadkeys:         # Liste aller erlaubten Keys
  - key: SSID_STR
    type: <string>
    presence: required
    content: ...
  - ...
```

## supportedOS

Pro OS gibt es Flags wie:

| Feld | Bedeutung |
|---|---|
| `introduced` | OS-Version, ab der der Payload existiert |
| `deprecated` | Ab wann veraltet |
| `removed` | Ab wann entfernt |
| `multiple` | Darf mehrfach im Profil vorkommen |
| `devicechannel` / `userchannel` | Welcher MDM-Kanal |
| `supervised` | Nur supervised Devices |
| `requiresdep` | Nur DEP-enrollte Devices |
| `userapprovedmdm` | Nur user-approved MDM |
| `allowmanualinstall` | Manuell installierbar (sonst: nur per MDM) |
| `sharedipad: { mode: ... }` | Verhalten in shared-iPad-Mode (`allowed`, `required`, `forbidden`, `ignored`) |
| `userenrollment: { mode: ... }` | dito für User Enrollment |

## payloadkeys-Eintrag

```yaml
- key: SSID_STR              # Key-Name in der Plist
  title: SSID                # Lesbarer Titel
  supportedOS:               # Optional: Per-Key OS-Override
    iOS: { introduced: '7.0' }
  type: <string>             # Plist-Typ
  valuetype: hostname        # Optional: Format-Hinweis
  presence: required         # required | optional
  default: true              # Default-Wert
  rangelist: [WPA, WPA2, …]  # Erlaubte Werte
  range: { min: 1, max: 65535 }
  format: ^[A-Z]{2}$         # Regex
  combinetype: union         # Wie mehrere Configs kombiniert werden
  content: |
    Beschreibung des Keys.
  subkeys:                   # Bei type: <dictionary> oder <array>
    - key: ...
```

## Type-System

| Schema-Type | Plist-Typ |
|---|---|
| `<string>` | string |
| `<integer>` | integer |
| `<real>` | real / float |
| `<boolean>` | true / false |
| `<data>` | data (binär; in JSON als Base64) |
| `<array>` | array |
| `<dictionary>` | dict |
| `<any>` | beliebiger Typ |

**Deprecated:** `<date>`. Wird durch `<string>` mit `valuetype: timestamp` ersetzt.

## valuetype

Zusätzliche String-Format-Hinweise (nicht hart validiert vom OS):

- `domain` — exakter Domain-Match (`example.com`)
- `domain-prefix` — `*.example.com` matcht alle Sub-Domains
- `email` — RFC 5322
- `hostname` — Hostname/IPv4/IPv6
- `localtime` — `YYYY-MM-DDTHH:MM:SS`
- `timestamp` — `YYYY-MM-DDTHH:MM:SSZ` mit time-offset
- `regex` — Regulärer Ausdruck
- `url` — RFC 3986
- `uuid` — 36-Zeichen UUID

## Inheritance bei subkeys

`payload.supportedOS` wird auf ALLE keys vererbt. Pro Key kann das überschrieben werden — z.B. ein Key der erst ab iOS 17 existiert, obwohl der Payload schon seit iOS 4 da ist.

## Spezielle Keys

- `key: ANY` als Sub-Key bedeutet: an dieser Stelle dürfen beliebige weitere Keys stehen. Der Validator von `build_mobileconfig.py` erkennt das und erlaubt Unbekanntes.
- `key: PayloadContentItem` ist eine Konvention für Array-Item-Definitionen.

## Die zweite Quelle: ProfileManifests

Apples YAML beschreibt Apple-Domains. Für Drittanbieter steht dort nichts,
und `--validate-strict` weist einen Payload vom Typ `com.google.Chrome`,
`com.microsoft.office` oder `us.zoom.config` als unbekannten PayloadType
zurück. Diese Domains beschreibt
[ProfileManifests](https://github.com/ProfileManifests/ProfileManifests), die
Sammlung, aus der auch ProfileCreator und iMazing Profile Editor ihre
Payload-Beschreibungen ziehen. `--manifests` schaltet sie als zweite Quelle
frei.

**Auflösungsreihenfolge: Apple gewinnt.** ProfileManifests wird nur gefragt,
wenn Apple den PayloadType überhaupt nicht kennt. Zusammengeführt wird nichts.
Ein PayloadType, den beide beschreiben, wird ausschließlich gegen Apple
geprüft, damit nie unklar ist, welche Regel gegolten hat. Für PPPC ist der
Unterschied klein und messbar: Apples
`com.apple.TCC.configuration-profile-policy.yaml` kennt 24 Services,
ProfileManifests 25, der einzige Mehrwert ist `RemoteDesktop`. Wer den
braucht, kommt an dieser Stelle mit dem Apple-Schema nicht weiter.

**Lizenz: keine.** Das Repo hat keine LICENSE-Datei, und die GitHub-API meldet
`"license": null` (geprüft am 2026-09-04). Ohne Lizenz gibt es keine
Erlaubnis zur Weiterverbreitung. Deshalb liegt hier kein Manifest im Repo,
keines im Release-Artefakt und keines als Test-Fixture. Geladen wird zur
Laufzeit, in einen eigenen Cache unter
`~/.cache/mobileconfig-builder/profilemanifests/<ref>/`, und nur, wenn
`--manifests` gesetzt ist.

**Woher die Herkunftsangabe kommt.** Jeder Lauf, der gegen die zweite Quelle
geprüft hat, sagt das auf stderr und nennt den Stand. Die Angabe stammt aus
dem Schema selbst, das ein Feld `_origin` trägt, nicht aus dem Umkehrschluss
„Apple kennt den PayloadType nicht, also kam er von ProfileManifests". Der
Unterschied war messbar: der PayloadType wird zum Dateinamen im Cache, und
einer mit Pfadanteilen (`../../…/fremd`) hat eine beliebige `.plist` von der
Platte gelesen, die der Lauf danach als ProfileManifests-Herkunft ausgewiesen
hat. Ein PayloadType, der nicht wie eine Preference-Domain aussieht, gilt hier
jetzt als unbekannt, und die Herkunftsangabe hängt an der Quelle statt an
ihrem Fehlen. Die Angabe trägt den Lizenzhinweis, deshalb muss sie stimmen.

### Übersetzung der Felder

| ProfileManifests | Apple-Schema |
|---|---|
| `pfm_domain` | `payload.payloadtype` |
| `pfm_platforms` | `payload.supportedOS` |
| `pfm_name` | `key` |
| `pfm_type` | `type` (`string` → `<string>`, `url` → `<string>`, `alias` → `<data>`, unbekannt → `<any>`) |
| `pfm_require: always` | `presence: required` |
| `pfm_range_list` | `rangelist` |
| `pfm_range_min` / `pfm_range_max` | `range.min` / `range.max` |
| `pfm_format` | `format` |
| `pfm_subkeys` | `subkeys` |
| `pfm_title`, `pfm_description` | `title`, `content` |

Nicht übersetzt werden `pfm_conditionals`, `pfm_exclude`, `pfm_targets` und
`pfm_app_min`. Das sind Regeln für eine grafische Oberfläche: welches Feld ist
sichtbar, welches schließt welches aus, ab welcher App-Version gibt es den
Key. Apples Schema kennt dafür nichts, und ein Profil, das gegen diese Regeln
verstößt, fällt hier nicht auf.

Ein Dictionary mit beliebigen Schlüsseln beschreibt ProfileManifests über
ein Platzhalter-Paar `{{key}}` und `{{value}}`. Chrome nutzt das für
`ExtensionSettings`, wo der Schlüssel die Erweiterungs-ID ist. Eins zu eins
übersetzt stünden dort zwei Keys namens `{{key}}` und `{{value}}`, und
`--validate-strict` hätte jede echte Erweiterungs-ID als unbekannten Key
abgelehnt. Apples Schema hat für denselben Fall die Konvention `key: ANY`, und
genau die entsteht hier.

Zwei Sorten Einträge fallen raus:

- Bedienelemente von ProfileCreator, erkennbar am Präfix `PFC_` und am Feld
  `pfm_segments`. `PFC_SegmentedControl_0` steht in den Manifesten für Chrome,
  Office und Zoom als `pfm_require: always` drin, ist aber ein
  Reiter-Umschalter und kein Preference-Key. Eins zu eins übersetzt würde
  jedes Chrome-Payload einen Key verlangen, den Chrome nie gesehen hat.
- Die sieben CommonPayloadKeys (`PayloadType`, `PayloadUUID`, …). Die stehen
  in Apples `CommonPayloadKeys.yaml` und werden von dort geprüft.

### Grenzen

Die Manifeste sind von Mac-Admins gepflegt und nicht von den Herstellern.
Sie sind vollständiger als alles andere, was öffentlich verfügbar ist, aber
sie sind kein Vertrag. Ein grüner `--validate-strict`-Lauf gegen ein Manifest
sagt: die Keys und Typen passen zu dem, was die Community aufgeschrieben hat.

## Verwandte Dateien im Repo

- `mdm/profiles/` — alle Configuration-Profile-Schemas (was dieser Skill nutzt)
- `mdm/commands/` — MDM-Commands (z.B. `DeviceLock`, `EraseDevice`)
- `mdm/checkin/` — MDM-CheckIn-Requests
- `mdm/errors/` — MDM-Error-Codes
- `declarative/declarations/` — DDM (anderes Protokoll, kein .mobileconfig)
- `declarative/status/` — DDM Status-Items
- `declarative/protocol/` — DDM Protocol
- `other/` — sonstige Datenformate (z.B. `commercialnames.yaml`)
