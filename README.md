# mobileconfig-builder

Generate production-ready `.mobileconfig` files (Apple Configuration Profiles) for macOS, iOS, iPadOS, tvOS, watchOS, and visionOS — validated against Apple's official device-management schema.

## What it does

`.mobileconfig` files configure Apple devices: Wi-Fi, VPN, email, certificates, restrictions, FileVault, software update policies, and more. They're deployed via MDM (Jamf, Intune, Kandji, Mosyle), Apple Configurator, AirDrop, or manual install.

This tool:

1. **Fetches** the current YAML schemas from [github.com/apple/device-management](https://github.com/apple/device-management) (release branch)
2. **Validates** every payload against the official schema (required keys, types, value ranges)
3. **Builds** a correctly structured XML plist `.mobileconfig` file
4. **Signs** (optional) with PKCS#7 using your X.509 certificate for production deployment

## Quick Start

```bash
# 1. Fetch all Apple profile schemas (cached locally)
python3 scripts/fetch_schema.py

# 2. Inspect a payload type
python3 scripts/inspect_payload.py com.apple.wifi.managed --os macOS

# 3. Build a profile from a spec file
python3 scripts/build_mobileconfig.py assets/examples/wifi_guest.json -o wifi.mobileconfig --validate-strict
```

## Requirements

- Python 3.9+
- PyYAML (auto-installed on first run)
- OpenSSL (only for signing)

## Spec File Format

Create a JSON file with your profile configuration:

```json
{
  "meta": {
    "PayloadIdentifier": "com.example.wifi.guest",
    "PayloadDisplayName": "Guest Wi-Fi",
    "PayloadDescription": "Configures the guest Wi-Fi network",
    "PayloadOrganization": "Example Corp",
    "PayloadScope": "System"
  },
  "payloads": [
    {
      "PayloadType": "com.apple.wifi.managed",
      "PayloadDisplayName": "Wi-Fi: GuestNet",
      "SSID_STR": "GuestNet",
      "AutoJoin": true,
      "EncryptionType": "WPA",
      "Password": "supersecret123"
    }
  ]
}
```

## Scripts

| Script | Purpose |
|--------|---------|
| `scripts/fetch_schema.py` | Fetches and caches YAML schemas from Apple's GitHub repo. Supports `--offline`, `--from-clone`, `--list`, `--refresh`. |
| `scripts/inspect_payload.py` | Displays keys, required fields, types, and allowed values for any PayloadType. Supports OS filtering. |
| `scripts/build_mobileconfig.py` | Builds and validates the profile. Outputs unsigned or PKCS#7-signed `.mobileconfig`. |

## Features

- **Schema-validated**: Every key checked against Apple's official YAML definitions, top-level fields against `TopLevel.yaml` and each payload against its own schema
- **Deterministic UUIDs**: Same input always produces the same UUIDs (safe for re-deployment)
- **Multi-payload support**: Combine Wi-Fi + Restrictions + Certificates in one profile
- **OS-aware inspection**: Filter keys by target platform (macOS, iOS, tvOS, etc.)
- **Offline mode**: Works fully offline once schemas are cached
- **Optional signing**: PKCS#7 signing with OpenSSL for production MDM deployment

## Signing (Optional)

```bash
python3 scripts/build_mobileconfig.py spec.json \
  -o profile.mobileconfig \
  --sign-cert signer-cert.pem \
  --sign-key signer-key.pem \
  --sign-ca ca-chain.pem
```

Unsigned profiles show as "Not Verified" on Apple devices. For production/MDM use, sign with a trusted certificate.

## Installation on Devices

- **macOS**: Double-click → System Settings → Privacy & Security → Profiles → Install
- **iOS/iPadOS**: Open via AirDrop/Mail/Safari → Settings → "Profile Downloaded" → Install
- **MDM**: Import into Jamf, Kandji, Mosyle, Intune, or Apple Profile Manager

## Examples

- `assets/examples/wifi_guest.json` — Simple WPA Wi-Fi profile
- `assets/examples/classroom_ipad.json` — Wi-Fi + iPadOS Restrictions combined

## Testing

```bash
python3 evals/run_tests.py        # Run all 6 eval tests
python3 evals/run_tests.py -v     # Verbose output
python3 evals/run_tests.py --eval-id 4   # Run a single test
```

## Common PayloadTypes

| Use Case | PayloadType |
|----------|-------------|
| Wi-Fi | `com.apple.wifi.managed` |
| VPN | `com.apple.vpn.managed` |
| Mail Account | `com.apple.mail.managed` |
| Exchange | `com.apple.eas.account` |
| Restrictions (iOS) | `com.apple.applicationaccess` |
| Restrictions (macOS) | `com.apple.applicationaccess.new` |
| Certificate | `com.apple.security.pkcs1` / `.pkcs12` / `.root` |
| FileVault | `com.apple.MCX.FileVault2` |
| Software Update | `com.apple.SoftwareUpdate` |
| Privacy/TCC | `com.apple.TCC.configuration-profile-policy` |

## Note on Declarative Device Management (DDM)

Apple's newer DDM declarations use a different format (JSON, not `.mobileconfig`) and are pushed directly by the MDM server. This tool focuses on traditional Configuration Profiles. DDM support may be added in the future.

## License

Apache License 2.0, see [LICENSE](LICENSE).

The Apple profile schemas this tool validates against come from
[apple/device-management](https://github.com/apple/device-management) and are
MIT-licensed by Apple Inc. They are fetched at runtime into
`~/.cache/mobileconfig-builder/` and are not part of this repository. See
[NOTICE](NOTICE).
