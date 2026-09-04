# Signing `.mobileconfig` files

Apple-Geräte akzeptieren auch unsignierte Profile, zeigen sie aber als „Nicht signiert / Nicht überprüft" an. In produktiven Umgebungen (MDM, Mass-Deployment) gehören Profile signiert.

## Mit welchem Zertifikat signieren?

Drei sinnvolle Optionen:

1. **Eigene interne CA** — am häufigsten in Unternehmen. Die CA ist auf den Zielgeräten als vertrauenswürdig hinterlegt (z.B. via MDM-Push eines Root-Zertifikats). Vorteil: voll kontrolliert. Nachteil: Geräte ohne CA-Vertrauen lehnen das Profil ab.

2. **Public-Trust-Zertifikat (z.B. DigiCert, Sectigo)** — eines, dem die Apple-Geräte ab Werk vertrauen. Funktioniert ohne CA-Push. Die passende Extended Key Usage ist `emailProtection` (S/MIME); ein Zertifikat ganz ohne einschränkende EKU geht ebenfalls. Ein reines Code-Signing-Cert ist die falsche Wahl, siehe den Abschnitt zum Schlüsselbund weiter unten.

3. **Apple Developer Enterprise Cert** — wenn vorhanden. Funktioniert auch.

**Was nicht funktioniert:** Self-Signed-Cert ohne Trust-Etablierung. Das Profil installiert sich, zeigt aber „Nicht signiert / Nicht überprüft" wie das unsignierte.

## Zwei Wege, dasselbe Ergebnis

| | `--sign-cert` / `--sign-key` | `--sign-identity` |
|---|---|---|
| Werkzeug | `openssl smime -sign` | `/usr/bin/security cms -S` |
| Schlüssel liegt | als PEM-Datei im Dateisystem | im Schlüsselbund, er verlässt ihn nicht |
| Plattform | überall, wo `openssl` im PATH ist | nur macOS |
| Hash | Vorgabe des Werkzeugs, bei OpenSSL 3.6 und der mit macOS gelieferten LibreSSL 3.3 jeweils SHA-256 | `SHA256`, gesetzt über `-H`, weil die Vorgabe SHA-1 wäre |

Beide erzeugen CMS / PKCS#7 Signed Data im DER-Format mit eingebettetem
Original-XML. Genau das verlangt Apples Spezifikation, und beide Ergebnisse
lassen sich mit denselben Befehlen aus dem Abschnitt Verifikation prüfen.

## Weg 1: PEM-Dateien über OpenSSL

Pflicht:
- Cert + Private Key im PEM-Format
- `openssl` im PATH (auf macOS, Linux ohnehin da; auf Windows: über WSL oder OpenSSL-Binaries)

Empfohlen:
- CA-Chain als drittes File mit allen Intermediate-Certs (sonst kann das Gerät die Trust-Chain ggf. nicht aufbauen)

```bash
python3 scripts/build_mobileconfig.py spec.json \
  -o profil.mobileconfig --offline \
  --sign-cert /path/to/signer-cert.pem \
  --sign-key  /path/to/signer-key.pem \
  --sign-ca   /path/to/ca-chain.pem
```

## Weg 2: Identität aus dem macOS-Schlüsselbund

In Unternehmen liegt der private Schlüssel meist gar nicht als Datei vor. Er
kommt über ein SCEP- oder ADCS-Profil in den Schlüsselbund und ist dort als
nicht exportierbar markiert. `openssl` kann ihn nicht lesen, `security cms`
schon.

```bash
# Kandidaten anzeigen
security find-identity -v -p smime
security find-identity -v -p basic

# Signieren, Name oder SHA-1 aus der Liste oben
python3 scripts/build_mobileconfig.py spec.json \
  -o profil.mobileconfig --offline \
  --sign-identity "Profil-Signer 2026"
```

### Warum nicht `-p codesigning`

`security find-identity` filtert nach Policy, und codesigning ist für
Konfigurationsprofile die falsche. Ein Signer-Zertifikat trägt entweder die
EKU `emailProtection` oder gar keine einschränkende EKU. Unter der
Code-Signing-Policy taucht es dann nicht auf, und wer sich darauf verlässt,
hält ein vorhandenes Zertifikat für nicht vorhanden.

Auf einem eingerichteten Firmen-Mac sehen die drei Listen so aus:

| Policy | Was auftaucht |
|---|---|
| `-p codesigning` | das Apple-Development-Zertifikat und ein selbst signiertes |
| `-p smime` | die Identität aus der internen CA |
| `-p basic` | die CA-Identitäten, nicht aber das selbst signierte |

Keine der Listen enthält die andere. `--sign-identity` fragt deshalb `smime`
und `basic` ab und zeigt die Vereinigung, wenn die angegebene Identität nicht
passt.

### Was beim ersten Aufruf passiert

Beim ersten Zugriff auf den privaten Schlüssel fragt macOS in einem Dialog
nach der Erlaubnis. Wer „Immer erlauben" wählt, trägt `security` dauerhaft in
die Zugriffsliste (ACL) des Schlüssels ein und wird nicht mehr gefragt. Über
SSH oder in einem CI-Job ohne Fenstersitzung gibt es diesen Dialog nicht, der
Aufruf bleibt dort einfach hängen oder scheitert. Für automatisierte Läufe
gehört die Zugriffsliste vorher gesetzt, etwa beim Import:

```bash
security import signer.p12 -k build.keychain-db -P "$PW" -T /usr/bin/security
security set-key-partition-list -S apple-tool:,apple: -s -k "$PW" build.keychain-db
```

`--keychain build.keychain-db` schickt Suche und Signierung dann in genau
diesen Schlüsselbund statt in die Suchliste des Benutzers.

### Was das Werkzeug prüft

`security cms -S` beendet sich mit Exit 0, auch wenn es die Identität nicht
findet: der Fehler steht nur auf stderr, und die Ausgabedatei bleibt bei null
Bytes. Auf den Exit-Code allein ist also kein Verlass. `build_mobileconfig.py`
sieht deshalb nach: die Ausgabedatei muss existieren, darf nicht leer sein,
muss mit einer ASN.1-SEQUENCE anfangen, und der Inhalt wird mit
`security cms -D` wieder ausgepackt und Byte für Byte mit dem gebauten Profil
verglichen. Passt etwas davon nicht, wird die Datei gelöscht und der Lauf
endet mit Exit 2.

Ohne `-H SHA256` signiert `security cms` mit SHA-1. Das Werkzeug setzt den
Schalter, nachgeprüft mit
`openssl cms -cmsout -print -inform der -in profil.mobileconfig`.

## Verifikation auf macOS

```bash
# Signer + Chain anzeigen:
openssl smime -verify -in profil.mobileconfig -inform der \
  -CAfile /path/to/ca-chain.pem -out /dev/null

# Plist-Inhalt rausschälen:
openssl smime -verify -in profil.mobileconfig -inform der \
  -CAfile /path/to/ca-chain.pem 2>/dev/null
```

## Was Claude NICHT tun darf

- Niemals private Keys über den Chat akzeptieren oder speichern.
- Niemals automatisch Self-Signed-Certs erzeugen und damit „signieren" — das schafft falsche Sicherheit.
- Wenn ein User im Chat einen privaten Key paste-d hat, ablehnen und den User bitten, den Key auf seinem System zu lassen und nur den **Pfad** zu nennen.
- Wo der Schlüssel im Schlüsselbund liegt, ist `--sign-identity` der bessere Vorschlag als `--sign-cert`: dann braucht niemand den Key zu exportieren, um zu signieren.

## Fehlerdiagnose

| Symptom | Ursache |
|---|---|
| Profil installiert sich, zeigt aber „Nicht überprüft" | CA nicht im Trust-Store |
| `openssl smime` schlägt fehl mit „unable to load signing key" | Key braucht Passphrase oder ist falsches Format |
| `security cms` meldet „failed to encode data: unknown error -1" | Die Identität aus `--sign-identity` gibt es unter diesem Namen nicht |
| `--sign-identity` findet nichts, `security find-identity -p codesigning` schon | Falsche Policy. Für Profile zählt `smime` oder `basic` |
| Der Aufruf hängt ohne Meldung | Der Schlüsselbund-Dialog wartet auf eine Fenstersitzung. Über SSH vorher `set-key-partition-list` setzen |
| Gerät meldet „Profile installation failed: signature invalid" | falsche EKU / Key-Usage am Cert; oder Cert abgelaufen |
| MDM-Push-Profil wird nicht akzeptiert | viele MDMs erwarten zusätzlich Encryption-Layer (separates Thema) |
