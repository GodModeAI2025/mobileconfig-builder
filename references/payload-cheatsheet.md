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
- `forceITunesStorePasswordEntry`
- … (>200 Keys; per `inspect_payload.py` schauen)

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

## Profile-Removal-Password — `com.apple.profileRemovalPassword`

- `RemovalPassword` (string) — verhindert dass User Profil ohne Passwort entfernt

## Dock — `com.apple.dock`

macOS Dock-Konfiguration: Position, Größe, Auto-Hide, persistente Apps.

## Login-Items — `com.apple.loginitems.managed`

macOS Login-Items per MDM steuern.

## Energy Saver — `com.apple.MCX(EnergySaver).yaml` (Filename)

`payloadtype: com.apple.MCX` mit speziellen Sub-Keys. Vorsicht: mehrere YAML-Files teilen sich diesen `payloadtype`!

---

**Hinweis zu `com.apple.MCX`:** Apple hat im Schema-Repo mehrere YAML-Dateien, die alle `payloadtype: com.apple.MCX` haben (Accounts, EnergySaver, FileVault2, Mobility, TimeServer, WiFi). Das ist der Legacy-MCX-Mechanismus. Beim Build mit unterschiedlichen Sub-Schemas kann das zu Validierungs-Konflikten führen. In der Praxis besser die spezifischen modernen `com.apple.<feature>.managed` Payloads verwenden.
