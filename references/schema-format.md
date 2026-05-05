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

## Verwandte Dateien im Repo

- `mdm/profiles/` — alle Configuration-Profile-Schemas (was dieser Skill nutzt)
- `mdm/commands/` — MDM-Commands (z.B. `DeviceLock`, `EraseDevice`)
- `mdm/checkin/` — MDM-CheckIn-Requests
- `mdm/errors/` — MDM-Error-Codes
- `declarative/declarations/` — DDM (anderes Protokoll, kein .mobileconfig)
- `declarative/status/` — DDM Status-Items
- `declarative/protocol/` — DDM Protocol
- `other/` — sonstige Datenformate (z.B. `commercialnames.yaml`)
