# Signing `.mobileconfig` files

Apple-Geräte akzeptieren auch unsignierte Profile, zeigen sie aber als „Nicht signiert / Nicht überprüft" an. In produktiven Umgebungen (MDM, Mass-Deployment) gehören Profile signiert.

## Mit welchem Zertifikat signieren?

Drei sinnvolle Optionen:

1. **Eigene interne CA** — am häufigsten in Unternehmen. Die CA ist auf den Zielgeräten als vertrauenswürdig hinterlegt (z.B. via MDM-Push eines Root-Zertifikats). Vorteil: voll kontrolliert. Nachteil: Geräte ohne CA-Vertrauen lehnen das Profil ab.

2. **Public-Trust-Zertifikat (z.B. DigiCert, Sectigo)** — eines, dem die Apple-Geräte ab Werk vertrauen. Funktioniert ohne CA-Push. Code-Signing- oder S/MIME-EKU empfohlen.

3. **Apple Developer Enterprise Cert** — wenn vorhanden. Funktioniert auch.

**Was nicht funktioniert:** Self-Signed-Cert ohne Trust-Etablierung. Das Profil installiert sich, zeigt aber „Nicht signiert / Nicht überprüft" wie das unsignierte.

## Format

`build_mobileconfig.py` nutzt `openssl smime -sign`. Das erzeugt CMS / PKCS#7 Signed Data im DER-Format mit eingebettetem Original-XML. Apple's Spezifikation ist genau das.

Pflicht:
- Cert + Private Key im PEM-Format
- `openssl` im PATH (auf macOS, Linux ohnehin da; auf Windows: über WSL oder OpenSSL-Binaries)

Empfohlen:
- CA-Chain als drittes File mit allen Intermediate-Certs (sonst kann das Gerät die Trust-Chain ggf. nicht aufbauen)

## Beispiel-Aufruf

```bash
python3 scripts/build_mobileconfig.py spec.json \
  -o profil.mobileconfig --offline \
  --sign-cert /path/to/signer-cert.pem \
  --sign-key  /path/to/signer-key.pem \
  --sign-ca   /path/to/ca-chain.pem
```

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

## Fehlerdiagnose

| Symptom | Ursache |
|---|---|
| Profil installiert sich, zeigt aber „Nicht überprüft" | CA nicht im Trust-Store |
| `openssl smime` schlägt fehl mit „unable to load signing key" | Key braucht Passphrase oder ist falsches Format |
| Gerät meldet „Profile installation failed: signature invalid" | falsche EKU / Key-Usage am Cert; oder Cert abgelaufen |
| MDM-Push-Profil wird nicht akzeptiert | viele MDMs erwarten zusätzlich Encryption-Layer (separates Thema) |
