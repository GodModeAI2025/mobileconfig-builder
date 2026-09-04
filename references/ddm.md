# Declarative Device Management (DDM)

Was dieses Werkzeug baut, sind Configuration Profiles: eine XML-Plist, die ein
MDM auf ein Gerät schiebt oder die jemand von Hand installiert. DDM ist der
neuere Weg. Apple liefert neue Funktionen zuerst dorthin, und mittelfristig
entscheidet das über die Relevanz eines Werkzeugs, das nur Profile kann.

Dieses Dokument beschreibt keinen vorhandenen Code. Es beschreibt, was ein
DDM-Export leisten müsste, was daran geht und was nicht. Stand der Prüfung:
4. September 2026, Branch `release` von `apple/device-management`.

## Was DDM anders macht

Ein Profil ist ein Dokument, das ein Gerät installiert und wieder entfernt.
Eine Declaration ist ein Zustand, den das Gerät hält: der Server sagt, was
gelten soll, das Gerät meldet zurück, ob es das umsetzen konnte, und wendet
Änderungen selbst an, ohne dass der Server erneut anstößt.

Praktisch heißt das:

- **Format.** JSON statt XML-Plist. Jede Declaration hat `Type`, `Identifier`,
  `ServerToken` und `Payload`.
- **Kein Dateiartefakt.** Eine Declaration wird nicht heruntergeladen und
  doppelgeklickt. Sie lebt auf dem MDM-Server, der sie über den
  Declarative-Management-Endpunkt anbietet. Ohne MDM-Server gibt es nichts zu
  installieren.
- **Kein Signieren.** Die Vertrauensfrage klärt der Kanal zum MDM-Server, nicht
  eine PKCS#7-Signatur um das Dokument.
- **Aktivierungen und Status.** `com.apple.activation.simple` entscheidet,
  welche Configurations gelten. Status-Subscriptions holen zurück, was das
  Gerät daraus gemacht hat. Beides hat im Profil-Modell keine Entsprechung.

## Der fachliche Kern

Eine Spec für dieses Werkzeug beschreibt heute Absichten, keine Dateiformate:

```json
{
  "meta": {"PayloadIdentifier": "com.example.passcode"},
  "payloads": [
    {"PayloadType": "com.apple.mobiledevice.passwordpolicy",
     "forcePIN": true, "minLength": 8, "maxFailedAttempts": 6}
  ]
}
```

Dieselbe Absicht gibt es als Declaration:

```json
{
  "Type": "com.apple.configuration.passcode.settings",
  "Identifier": "com.example.passcode",
  "Payload": {"RequirePasscode": true, "MinimumLength": 8,
              "MaximumFailedAttempts": 6}
}
```

Das ist der Punkt: eine Spec, zwei Ausgabeformate. Der Validator, der die
Werte prüft, wäre derselbe, denn Apple beschreibt beide Seiten im selben
YAML-Format. `mdm/profiles/*.yaml` und
`declarative/declarations/configurations/*.yaml` haben dieselben Felder:
`payloadkeys` mit `key`, `type`, `presence`, `range`, `rangelist`, `subkeys`.
Der vorhandene Validator läuft über beide, sobald der Fetch-Pfad das zweite
Verzeichnis lädt.

## Was daran wirklich Arbeit ist

Die Abbildung ist keine Umbenennung, sondern eine Übersetzung. Am
Passcode-Beispiel, dem am besten abgedeckten Fall:

| Profil (`com.apple.mobiledevice.passwordpolicy`) | Declaration (`com.apple.configuration.passcode.settings`) |
|---|---|
| `forcePIN` | `RequirePasscode` |
| `requireAlphanumeric` | `RequireAlphanumericPasscode` |
| `allowSimple` | `RequireComplexPasscode`, **Wert invertiert** |
| `minLength` | `MinimumLength` |
| `minComplexChars` | `MinimumComplexCharacters` |
| `maxFailedAttempts` | `MaximumFailedAttempts` |
| `minutesUntilFailedLoginReset` | `FailedAttemptsResetInMinutes` |
| `maxGracePeriod` | `MaximumGracePeriodInMinutes` |
| `maxInactivity` | `MaximumInactivityInMinutes` |
| `maxPINAgeInDays` | `MaximumPasscodeAgeInDays`, **`range.min` 1 gegen 0** |
| `pinHistory` | `PasscodeReuseLimit` |
| `changeAtNextAuth` | `ChangeAtNextAuth` |
| `customRegex` | `CustomRegex` |

Elf von dreizehn Keys sind reine Umbenennungen. Einer dreht die Bedeutung um:
`allowSimple: false` heißt dasselbe wie `RequireComplexPasscode: true`. Einer
verschiebt den erlaubten Bereich: `maxPINAgeInDays` fängt bei 1 an,
`MaximumPasscodeAgeInDays` bei 0, ein Profil mit 0 ist also ungültig und die
Declaration dazu gültig. Eine Tabelle, die solche Fälle nicht kennt, erzeugt
Ausgaben, die schema-valide und fachlich falsch sind.

Und das ist der freundliche Fall. Für die meisten Payloads gibt es gar keine
Entsprechung: der `release`-Branch hat 121 PayloadTypes in `mdm/profiles/` und
36 Configuration-Declarations in
`declarative/declarations/configurations/`. Wi-Fi, VPN, Zertifikats-Payloads
und die gesamte Restrictions-Familie sind nicht dabei.

## Der ehrliche Übergang: `com.apple.configuration.legacy`

Apple hat für genau diese Lücke eine Declaration vorgesehen. Ihr einziger
Pflicht-Key ist `ProfileURL`: die Declaration verweist auf ein Profil, das
weiterhin ein Profil bleibt.

```json
{
  "Type": "com.apple.configuration.legacy",
  "Identifier": "com.example.wifi.guest",
  "Payload": {"ProfileURL": "https://mdm.example.com/profiles/guest-wifi"}
}
```

Damit lässt sich eine DDM-Ausrollung auch dann fahren, wenn es für einen
Payload keine native Declaration gibt. Ein Export, der das nutzt, wäre
brauchbar und ehrlich: nativ, wo es geht, `legacy` für den Rest, und in beiden
Fällen sichtbar, was gerade passiert.

## Was ein Export nicht darf

Vollständigkeit suggerieren. Ein Werkzeug, das aus jeder Spec eine Declaration
macht, ohne zu sagen, dass die Hälfte davon nur ein Verweis auf das alte
Profil ist, richtet mehr Schaden an als gar keines. Wer eine Declaration
ausrollt und annimmt, das Gerät melde jetzt Status zurück, während in
Wirklichkeit ein Profil per URL nachgeladen wird, plant auf einer falschen
Grundlage.

## Reihenfolge, wenn es gebaut wird

1. `fetch_schema.py` lädt zusätzlich
   `declarative/declarations/configurations/`. Eigener Cache-Ordner, eigener
   Index, dieselbe Merge-Logik.
2. `inspect_declaration.py` als Gegenstück zu `inspect_payload.py`. Ab hier
   hat das Werkzeug einen Nutzen, auch ohne Export: es beantwortet die Frage,
   ob es für einen Payload überhaupt eine Declaration gibt.
3. Eine Abbildungstabelle, von Hand gepflegt, mit Umbenennung, Inversion und
   abweichenden Bereichen je Key. Nur für Paare, die jemand geprüft hat.
4. Der Export selbst, mit `com.apple.configuration.legacy` als Rückfallebene
   und einem Bericht, welcher Payload nativ und welcher als Verweis
   herausgekommen ist.

Testbar ist lokal nur die Schema-Gültigkeit. Ob ein Gerät die Declaration
annimmt, zeigt sich erst an einem MDM-Server.

## Quellen

- `declarative/declarations/configurations/` in
  [apple/device-management](https://github.com/apple/device-management),
  Branch `release`
- `declarative/declarations/activations/`, `.../assets/`, `.../management/`
  für die Teile, die im Profil-Modell fehlen
- `declarative/status/` für die Rückmeldungen des Geräts
