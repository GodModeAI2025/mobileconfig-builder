# Payload Cheatsheet

Häufig genutzte `PayloadType`s im Apple-Schema und die typischen Keys, die User im Interview-Flow setzen wollen. Vollständige Liste immer per `inspect_payload.py <type>` aus dem Schema holen — das hier ist nur ein Schnellnachschlag, um schneller die richtige Frage zu stellen.

## Wi-Fi — `com.apple.wifi.managed`

Plattformen: alle.

Wichtige Keys:
- `SSID_STR` (string, required-ish — alternativ `DomainName` ab iOS 7)
- `HIDDEN_NETWORK` (bool, default false)
- `AutoJoin` (bool, default true)
- `EncryptionType` (string, oneOf: `WEP`, `WPA`, `WPA2`, `WPA3`, `Any`, `None`)
- `Password` (string, nur bei nicht-Enterprise-Verschlüsselung)
- `EAPClientConfiguration` (dict, für 802.1X / WPA-Enterprise)
- `ProxyType` (string, oneOf: `None`, `Manual`, `Auto`)

## VPN — `com.apple.vpn.managed`

- `UserDefinedName` (string)
- `VPNType` (string, oneOf: `L2TP`, `PPTP`, `IPSec`, `IKEv2`, `AlwaysOn`, `VPN`, `Plugin`)
- `VPNSubType` (string — nur bei `Plugin`/`VPN`)
- `IPv4`, `Proxies`, `IPSec`, `PPP`, `IKEv2` (dict, je nach Typ)

## E-Mail (IMAP/POP) — `com.apple.mail.managed`

- `EmailAccountDescription` (string)
- `EmailAccountName` (string)
- `EmailAccountType` (string, oneOf: `EmailTypeIMAP`, `EmailTypePOP`)
- `EmailAddress` (string, valuetype: email)
- `IncomingMailServerHostName` (string)
- `IncomingMailServerPortNumber` (integer)
- `IncomingMailServerAuthentication` (string)
- `IncomingMailServerUsername` (string)
- `OutgoingMailServerHostName`, `OutgoingMailServerPortNumber`, … (analog)

## Exchange — `com.apple.eas.account`

- `EmailAddress`, `Host`, `UserName`, `SSL`, `OAuth`, …

## Restrictions iOS/iPadOS — `com.apple.applicationaccess`

Sehr viele Booleans:
- `allowAppInstallation`
- `allowCamera`, `allowExplicitContent`, `allowInAppPurchases`
- `allowSafari`, `allowAirDrop`, `allowAssistant`
- `forcePasscodeOnDeviceLock`
- … (>200 Keys; per `inspect_payload.py` schauen)

`forceITunesStorePasswordEntry` fuehrt Apple seit iOS 17 als deprecated;
`allowInAppPurchases` deckt denselben Zweck ab. `inspect_payload.py`
markiert solche Keys mit `[deprecated: …]`.

## Restrictions macOS — `com.apple.applicationaccess.new`

Anderer Aufbau als iOS! Enthält App-Whitelisting:
- `whitelistEnabled`, `whitelist` (array of bundle IDs)
- `familyControlsEnabled`
- `pathBlackList` (array)

## Zertifikate

- `com.apple.security.root` — Trusted Root CA
- `com.apple.security.pkcs1` — DER-encoded X.509
- `com.apple.security.pkcs12` — PKCS#12 (mit Private Key, Password-protected)

Alle erwarten `PayloadContent` als `<data>` (Base64) plus ggf. `Password`.

## FileVault — `com.apple.MCX.FileVault2`

- `Enable` (string, oneOf: `On`, `Off`)
- `Defer` (bool)
- `DeferDontAskAtUserLogout`
- `DeferForceAtUserLoginMaxBypassAttempts` (integer)
- `UseRecoveryKey`, `ShowRecoveryKey` (bool)

## Software Update Policy — `com.apple.SoftwareUpdate`

- `AllowPreReleaseInstallation` (bool)
- `AutomaticallyInstallAppUpdates`
- `AutomaticallyInstallMacOSUpdates`
- `AutomaticDownload`, `AutomaticCheckEnabled`

## TCC / Privacy Preferences Policy Control — `com.apple.TCC.configuration-profile-policy`

macOS-only. Erlaubt MDM-administrierte App-Privacy-Permissions (Kamera, Mikrofon, Full Disk Access, etc.).

- `Services` (dict mit `Camera`, `Microphone`, `SystemPolicyAllFiles`, `Accessibility`, `AppleEvents`, …)
- Pro Service eine Liste von Apps mit `Identifier`, `IdentifierType`, `CodeRequirement`, `Allowed`

## Verschlüsseltes DNS — `com.apple.dnsSettings.managed`

Plattformen: iOS 14+, macOS 11+, visionOS. tvOS und watchOS führt das Schema mit `introduced: n/a`.

- `DNSSettings` (dict, required)
  - `DNSProtocol` (string, required, oneOf: `HTTPS`, `TLS`)
  - `ServerURL` (string, DoH-URI-Template nach RFC 8484, `https://`)
  - `ServerName` (string, DoT-Hostname zur Zertifikatsprüfung)
  - `ServerAddresses` (array of string, IPv4/IPv6)
  - `SupplementalMatchDomains` (array of string)
  - `AllowFailover` (bool, ab OS 26), `PayloadCertificateUUID` (string, Client-Identität)
- `OnDemandRules` (array, dieselbe Struktur wie im VPN-Payload)
- `ProhibitDisablement` (bool, nur auf betreuten Geräten)

Zwei Domain-Listen, die leicht verwechselt werden, weil beide „nur bestimmte Domains“ klingen:

| Wunsch | Mechanismus |
|---|---|
| Verschlüsselt **außer** für `corp.example.com` (Ausnahmeliste) | `OnDemandRules` mit `Action: EvaluateConnection` und `ActionParameters: [{Domains: [...], DomainAction: NeverConnect}]` |
| Verschlüsselt **nur** für `corp.example.com` (Split-DNS) | `DNSSettings.SupplementalMatchDomains: [...]` |

Beide leer heißt: jede Anfrage geht an den Resolver, und das ist meist gewollt. Ein einzelnes führendes `*` ist erlaubt, `*.example.com` und `example.com` treffen beide `mail.example.com`. Apples Hinweis im Schema: per MDM installiert gilt die Einstellung nur für verwaltete WLAN-Netze, manuell installiert auch fürs Mobilfunknetz. Beispiel: `assets/examples/encrypted_dns.json`.

## Profile-Removal-Password — `com.apple.profileRemovalPassword`

- `RemovalPassword` (string) — verhindert dass User Profil ohne Passwort entfernt

## Dock — `com.apple.dock`

macOS Dock-Konfiguration: Position, Größe, Auto-Hide, persistente Apps.

## Login-Items — `com.apple.loginitems.managed`

macOS Login-Items per MDM steuern.

## Energy Saver — `com.apple.MCX(EnergySaver).yaml` (Filename)

`payloadtype: com.apple.MCX` mit speziellen Sub-Keys. Vorsicht: mehrere YAML-Files teilen sich diesen `payloadtype`!

---

**Hinweis zu `com.apple.MCX`:** Apple hat im Schema-Repo mehrere YAML-Dateien, die alle `payloadtype: com.apple.MCX` haben (Accounts, EnergySaver, FileVault2, Mobility, TimeServer, WiFi). Das ist der Legacy-MCX-Mechanismus. `fetch_schema.load_schema_map` vereint diese Dateien zu einem Schema, `inspect_payload.py` und `build_mobileconfig.py` sehen deshalb dieselben Keys. Ein Key gilt nach der Vereinigung nur dann als `required`, wenn ihn jede beteiligte Datei verlangt, sonst würde eine Variante die andere ausschließen. Dasselbe gilt für `com.apple.extensiblesso`, das in einer generischen und einer Kerberos-Variante vorliegt. In der Praxis trotzdem besser die spezifischen modernen `com.apple.<feature>.managed` Payloads verwenden.
