# mobileconfig-builder

[![CI](https://github.com/GodModeAI2025/mobileconfig-builder/actions/workflows/ci.yml/badge.svg)](https://github.com/GodModeAI2025/mobileconfig-builder/actions/workflows/ci.yml)

Generate production-ready `.mobileconfig` files (Apple Configuration Profiles) for macOS, iOS, iPadOS, tvOS, watchOS, and visionOS — validated against Apple's official device-management schema.

**Who it is for:** MDM and Apple admins. If you keep a fleet running in Jamf Pro or Microsoft Intune, in Kandji, Mosyle, or Apple Profile Manager, and you need a profile whose keys are right the first time, this is aimed at you.

**Two ways to use it.** `SKILL.md` makes this repository a Claude skill: Claude reads the workflow there, asks for platform, payload type, and the required keys, and hands back a finished profile. `scripts/` makes it a command line tool for people: three Python scripts you run in a terminal or wire into your own pipeline, with no Claude involved. Both paths call the same code and share the same schema cache.

## What it does

`.mobileconfig` files configure Apple devices: Wi-Fi, VPN, email, certificates, restrictions, FileVault, software update policies, and more. They're deployed via MDM (Jamf, Intune, Kandji, Mosyle), Apple Configurator, AirDrop, or manual install.

This tool:

1. **Fetches** the current YAML schemas from [github.com/apple/device-management](https://github.com/apple/device-management) (release branch)
2. **Validates** every payload against the official schema (required keys, types, value ranges)
3. **Builds** a correctly structured XML plist `.mobileconfig` file
4. **Signs** (optional) with PKCS#7, either from PEM files through OpenSSL or from an identity in the macOS keychain, where the private key never leaves the keychain

## Getting the Tool

Two ways, no package manager involved.

**Clone the repository.** You get everything: the scripts, the skill, the
examples, plus the landing page, the CI workflows and `tools/scan_secrets.py`.

```bash
git clone https://github.com/GodModeAI2025/mobileconfig-builder.git
cd mobileconfig-builder
python3 scripts/fetch_schema.py
```

**Download the release archive.** It holds what you need to run the tool or
install the skill and nothing else: `SKILL.md`, `references/`, `scripts/`,
`assets/`, `evals/`, plus `LICENSE`, `NOTICE` and `VERSION`. The landing page
and the workflow files stay out, and so does `scripts/package_release.py`,
which builds the archive and has no job inside it.

```bash
curl -LO https://github.com/GodModeAI2025/mobileconfig-builder/releases/latest/download/mobileconfig-builder.zip
unzip mobileconfig-builder.zip -d ~/.claude/skills/
```

The archive unpacks into a single `mobileconfig-builder/` directory, so the
command above lands the skill at `~/.claude/skills/mobileconfig-builder/`,
where Claude looks for it. For command line use, unzip wherever you like and
run the scripts from that directory.

That URL always points at the newest published release, so it answers with
404 as long as this repository has no release. In that case, clone.

## Quick Start

```bash
# 1. Fetch all Apple profile schemas (cached locally)
python3 scripts/fetch_schema.py

# 2. Inspect a payload type
python3 scripts/inspect_payload.py com.apple.wifi.managed --os macOS

# 3. Build a profile from a spec file
python3 scripts/build_mobileconfig.py assets/examples/wifi_guest.json -o wifi.mobileconfig --validate-strict

# 4. Check a profile you already have, no matter where it came from
python3 scripts/validate_mobileconfig.py wifi.mobileconfig
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
| `scripts/validate_mobileconfig.py` | Checks a `.mobileconfig` that already exists, whoever built it. Reads XML plists, binary plists, and signed PKCS#7 containers. Reports findings with a path, `--format json` for machines, exit code 0/1/2. |
| `scripts/package_release.py` | Builds the release archive from the files git tracks. Takes the output path as its argument, needs no network, and produces the same bytes on every run. |
| `tools/scan_secrets.py` | Repository check, not part of the build workflow. Looks for committed profiles, key files, PEM blocks, and password values that are not documented placeholders. Runs in CI. |

## Features

- **Schema-validated**: Every key checked against Apple's official YAML definitions, top-level fields against `TopLevel.yaml` and each payload against its own schema
- **Validates profiles it did not build**: hand it a `.mobileconfig` exported from Jamf, Intune, Kandji or Profile Manager and it checks that file against the same rules, signed containers included
- **Third-party domains**: `--manifests` adds ProfileManifests as a second source, so Chrome, Office, Zoom and the rest validate too. Apple wins wherever both describe a payload type
- **Deterministic UUIDs**: Same input always produces the same UUIDs (safe for re-deployment)
- **Multi-payload support**: Combine Wi-Fi + Restrictions + Certificates in one profile. A certificate payload carries a `<data>` key, and a JSON spec reaches it through `{"__base64__": "..."}` or `{"__file__": "ca.der"}`; YAML keeps the `!!binary` tag. A bare base64 string is still a string and still fails as `expected <data>, got str`
- **OS-aware inspection**: Filter keys by target platform (macOS, iOS, tvOS, etc.)
- **Offline mode**: Works fully offline once schemas are cached
- **Optional signing**: PKCS#7 signing for production MDM deployment, either with OpenSSL from PEM files or with `security cms` from a keychain identity

## Signing

**Rule: unsigned is for the lab.** An unsigned profile is fine while you are
iterating on a spec on your own test devices. Anything that leaves that bench,
for a colleague's Mac, a fleet, or an MDM server, gets signed. Without a
signature the device shows "Not Verified" at install time, nobody can tell who
built the file, and whoever gets hold of it before installation can edit it.
Plenty of MDM servers refuse unsigned profiles outright.

There are two ways in, and they produce the same PKCS#7 DER file.

From PEM files, through OpenSSL, on any platform:

```bash
python3 scripts/build_mobileconfig.py spec.json \
  -o profile.mobileconfig \
  --sign-cert signer-cert.pem \
  --sign-key signer-key.pem \
  --sign-ca ca-chain.pem
```

From the macOS keychain, through `/usr/bin/security cms`, where the private
key stays in the keychain. This is the usual case in a company, because a
signing key that arrives by SCEP or ADCS is marked non-exportable and OpenSSL
cannot read it at all:

```bash
security find-identity -v -p smime     # list the candidates
python3 scripts/build_mobileconfig.py spec.json \
  -o profile.mobileconfig \
  --sign-identity "Profile Signer 2026"
```

Use `-p smime` or `-p basic` to find the identity, not `-p codesigning`. A
profile signer carries the `emailProtection` EKU or no restricting EKU at
all, so the code-signing policy hides it. On a managed Mac the three lists
genuinely differ and none of them contains the others.

The flag is optional, the practice is not. Signing also does not remove the
install prompt: the device still asks the user to confirm, and it only shows
the profile as verified when it already trusts the signing CA. A self-signed
certificate without established trust looks the same as no signature at all.
`references/signing.md` covers how to pick a certificate, what the keychain
access dialog does on the first call, and how to prepare a keychain for an
unattended run.

## Certificates and Other `<data>` Fields

A certificate payload carries its bytes in a `<data>` key. YAML has the
`!!binary` tag for that; JSON has no bytes type at all, which used to make
every certificate payload a YAML-only affair. Two markers close that:

```json
{
  "payloads": [
    {
      "PayloadType": "com.apple.security.root",
      "PayloadCertificateFileName": "ca.cer",
      "PayloadContent": {"__file__": "ca.der"}
    }
  ]
}
```

`{"__base64__": "MIIDXTCC..."}` takes the base64 text directly, line breaks
and spaces included, which is what you get from a PEM body or from
`base64 < ca.der`. `{"__file__": "ca.der"}` reads a file; a relative path
counts from the directory of the spec, not from the working directory, so the
same spec builds the same profile from anywhere. Both are resolved before
validation, anywhere in the spec, at any depth, in dictionaries and in lists.

Apple wants DER on a certificate payload. A PEM file goes in as PEM bytes,
because the marker copies what it reads, so convert first:

```bash
openssl x509 -in ca.pem -outform der -out ca.der
```

The marker replaces its whole dictionary, so nothing else may stand next to
it, and a value that is not valid base64 or a path that cannot be read ends
the run with exit code 2 and a message naming the spot, before any file is
written.

## Checking an Existing Profile

`build_mobileconfig.py` validates while it builds. `validate_mobileconfig.py`
takes the other direction: a finished `.mobileconfig`, whoever wrote it.

```bash
python3 scripts/validate_mobileconfig.py profile.mobileconfig
python3 scripts/validate_mobileconfig.py *.mobileconfig --strict
python3 scripts/validate_mobileconfig.py profile.mobileconfig --format json
```

It reads three shapes and tells you which one it got: an XML plist, a binary
plist, and a signed PKCS#7 container, which it unwraps with
`openssl smime -verify -noverify` before looking inside. The profile level
goes against `TopLevel.yaml`, every entry in `PayloadContent` against its own
schema, which is the same code path the build uses.

Findings come in two levels, and one rule separates them:

| Level | Meaning | Examples | Exit |
|-------|---------|----------|------|
| `FEHLER` | The schema is violated | required key missing, wrong type, value outside `rangelist` or `range`, `PayloadContent` missing or not a list | 2 |
| `WARNUNG` | The schema says nothing, or there is none | key not in the schema, payload type without a schema, a value failing a `format` regex, a `PayloadUUID` used twice | 1 |

`--manifests` works here too, and a run that used it says so in its report,
because a clean result whose rule came from a community source without a
license is not the same clean result as one against Apple's own schema.

The split is what makes the tool usable on foreign files. A profile out of a
real MDM regularly carries keys Apple never described and payloads from
vendors Apple has no schema for. As errors those would paint every such file
red. `--strict` turns every warning into an error, which is the mode for
profiles that come out of this repository.

Both levels are non-zero, so either one already fails a CI job. Use `--strict`
when a warning should count as a defect:

```yaml
- name: Validate profiles
  run: |
    python3 -m pip install pyyaml
    python3 scripts/fetch_schema.py
    python3 scripts/validate_mobileconfig.py profiles/*.mobileconfig --strict
```

There is no packaged GitHub Action for this yet; the snippet calls the script
directly, and it needs the schema cache, so `fetch_schema.py` runs first.

## Handling Secrets

A configuration profile carries credentials in the clear. The Wi-Fi payload
holds the network password, a VPN payload holds the shared secret, a mail
payload holds account data. The XML plist stores all of it unencrypted, so a
`.mobileconfig` file is exactly as sensitive as the passwords inside it, and
so is the spec file it was built from.

What that means in practice:

- Write output outside the repository. The quick start above uses
  `-o wifi.mobileconfig` in the current directory because it is short; in
  real use, point `-o` at a path you control. `.gitignore` covers
  `*.mobileconfig` and key material (`*.pem`, `*.key`, `*.p12`, `*.pfx`,
  `*.cer`, `*.crt`) as a backstop for the times you forget.
- Treat spec files like the profiles they produce. A spec with a real Wi-Fi
  password does not belong in version control either.
- Never send a private key through a chat window. `SKILL.md` instructs Claude
  to refuse that and ask for a file path on your machine instead.
- Hand the profile to the MDM server, then delete the local copy, or keep it
  where you keep other credentials.
- The example specs under `assets/examples/` use invented passwords
  (`supersecret123`, `schoolpass2026`). They are listed as placeholders in
  `tools/scan_secrets.py`; any other value behind a key like `Password`,
  `SharedSecret`, or `Passphrase` makes the scan and the CI job fail. The one
  exception is a boolean: `PasswordManagerEnabled: false` is a Chrome policy,
  not a credential, and `true`/`false`/`yes`/`no` pass.

Run the check yourself with `python3 tools/scan_secrets.py`. It reads only
what `git ls-files` reports, needs no network, and prints file and line for
every finding. It has no entropy heuristic and does not look at history, so
it complements a real scanner such as gitleaks rather than replacing it.

## Installation on Devices

- **macOS**: Double-click → System Settings → Privacy & Security → Profiles → Install
- **iOS/iPadOS**: Open via AirDrop/Mail/Safari → Settings → "Profile Downloaded" → Install
- **MDM**: Import into Jamf, Kandji, Mosyle, Intune, or Apple Profile Manager

## Examples

- `assets/examples/wifi_guest.json` — Simple WPA Wi-Fi profile
- `assets/examples/classroom_ipad.json` — Wi-Fi + iPadOS Restrictions combined

## Testing

```bash
python3 evals/run_tests.py        # Run all 10 eval tests
python3 evals/run_tests.py -v     # Verbose output
python3 evals/run_tests.py --eval-id 4   # Run a single test
```

The suite calls every script with `--offline`, so a populated schema cache is a prerequisite. Run `python3 scripts/fetch_schema.py` once, or fill the cache from a local clone with `--from-clone`.

CI runs the same suite on every push and pull request against `main`, plus nine checks outside the test runner: `VERSION` against the `CHANGELOG.md` section and against the download name this README documents, the validator run against a built profile and against three broken copies of it, the invented top-level key sent straight through the CLI, both signing paths driven against the output path, a certificate payload built from a JSON spec through both data markers, a schema inspection of the Wi-Fi payload, a Chrome profile built against ProfileManifests at a pinned commit, `tools/scan_secrets.py`, and a build of the release archive. That last one asserts the files the archive has to contain, the repository internals it must not contain, and identical bytes on two consecutive runs, so a broken package shows up before someone sets a tag rather than after. Eval 6 already covers the top-level rejection inside the suite; the CI step asserts the same contract at the shell level, where the exit code and the missing output file are what a caller actually sees. The signing step ends by handing its own signed output to the validator, and then the same file with one changed byte: that is the only place in this workflow where a PKCS#7 container exists, so it is the only place where unwrapping one can be measured. The certificate step generates its own throwaway certificate with `openssl`, because no certificate may live in this repository, and asserts that both markers put the same bytes into the profile that the DER file holds. The Wi-Fi inspection is the only coverage `inspect_payload.py` gets, since no eval calls it. The Chrome step is the only one that reaches ProfileManifests: it asserts that the payload type is rejected without `--manifests`, accepted with it, that an invented Chrome key still fails, and that no manifest ends up in the working tree. Both schema sources are pinned to a fixed commit, so a change upstream cannot turn the build red by itself. Bumping either commit is a deliberate edit in `.github/workflows/ci.yml`.

## Third-Party Domains

Apple's YAML covers Apple's domains. A payload of type `com.google.Chrome`,
`com.microsoft.office` or `us.zoom.config` is rejected under
`--validate-strict` as an unknown PayloadType, because Apple never described
it. `--manifests` adds
[ProfileManifests](https://github.com/ProfileManifests/ProfileManifests) as a
second source, the collection that also powers ProfileCreator and iMazing
Profile Editor.

```bash
python3 scripts/inspect_payload.py com.google.Chrome --manifests
python3 scripts/build_mobileconfig.py chrome.json \
  -o chrome.mobileconfig --validate-strict --manifests
```

Apple wins. ProfileManifests is only consulted for payload types Apple does
not describe at all, and nothing is merged, so it is always clear which rule
applied. For PPPC the difference is one key: Apple's TCC schema lists 24
services, ProfileManifests lists 25, and the extra one is `RemoteDesktop`.

Every run that used the second source says so on stderr, and
`inspect_payload.py` prints the origin in its header.

**ProfileManifests has no license.** No LICENSE file, and the GitHub API
reports `"license": null` (checked 2026-09-04). Without a license there is no
grant to redistribute, so nothing from it lives in this repository, nothing
ships in the release archive, and no manifest is used as a test fixture.
`--manifests` fetches one file at runtime into
`~/.cache/mobileconfig-builder/profilemanifests/<ref>/`. Pin the ref with
`--manifests-ref <sha>` when you want the same schema on the next run;
without it the default is the `master` branch. `references/schema-format.md`
documents how the manifest fields are translated and what is deliberately
dropped.

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

## Limitations

- **`<data>` markers take bytes at face value.** `{"__base64__": "..."}` and `{"__file__": "..."}` are resolved anywhere in the spec tree, before validation and regardless of what the schema expects at that spot, because binding the resolution to `<data>` would mean knowing the schema before the spec exists. A marker in the wrong place shows up as `expected <string>, got bytes`. `__file__` reads whatever path it is given, with no size limit, and puts those bytes into the profile as they are: a PEM file lands as PEM, and Apple wants DER on a certificate payload, so convert with `openssl x509 -outform der` first. Neither marker checks that the bytes are a certificate. `~` is expanded, an absolute path is taken as it stands, and there is no allowlist, so a spec is only as trustworthy as its source: read a foreign spec's `__file__` entries before you build it, or it pulls `~/.ssh/id_rsa` into a profile in plain text.
- **The schema cache never expires.** A cached file is served until you run `fetch_schema.py --refresh`. A payload type Apple adds shows up on the next online fetch because the file is missing locally, but keys Apple changes inside an existing file stay stale until a refresh.
- **The validator checks the schema, not the deployment.** `validate_mobileconfig.py` answers one question: do the keys, types and value ranges in this file match Apple's YAML? It says nothing about whether the profile does what you meant, whether the target OS supports the keys it carries (`supportedOS` is not evaluated, so an iOS-only key in a macOS profile passes), or whether an MDM will accept it. It does not verify who signed a file: `openssl smime -verify -noverify` checks the signature but skips the certificate chain, so a valid signature from an issuer nobody trusts passes. Encrypted payloads stay opaque, `EncryptedPayloadContent` is data and is not unwrapped. Output is text or JSON; there is no SARIF, so findings do not land in GitHub Code Scanning.
- **The second schema source is a community source.** ProfileManifests is maintained by Mac Admins, not by Google, Microsoft or Zoom. A green `--validate-strict` against a manifest means the keys and types match what the community wrote down. The manifest fields `pfm_conditionals`, `pfm_exclude`, `pfm_targets` and `pfm_app_min` are not translated, so a profile that violates those rules passes here.
- **Keychain signing is macOS only, and its success path is not in CI.** `--sign-identity` goes through `/usr/bin/security`, which exists on macOS and nowhere else; on any other platform it exits 2 and points at `--sign-cert`. Signing from PEM files still needs `openssl` in `PATH`. Eval 7 covers the failure paths of both on every platform. The success path of the keychain route was verified by hand against a throwaway keychain; `references/signing.md` has the import and `set-key-partition-list` commands that make an unattended run possible. It also cannot sign when two certificates in the keychain share a common name: `security cms -N` selects by name alone and takes no fingerprint, so the tool refuses instead of signing with a certificate it cannot name. Passing the SHA-1 does not get around that, and the PEM route does, because there the certificate itself is the argument.
- **Signing needs a writable output directory, not just a writable output file.** The signature is written to a temporary file next to the target and moved into place with `os.replace`, so that a failed run cannot leave behind the empty `.mobileconfig` that `openssl -out` used to truncate the previous valid profile into. The move needs write permission on the directory. In a directory with mode 555 the run ends with exit 2 and says so, and whatever was at the output path stays untouched. The old direct write failed there too, with a `PermissionError` traceback, because it put a `<name>.unsigned.mobileconfig` next to the target and needed the same permission.
- **PyYAML is installed at runtime.** On first use the scripts run `pip install pyyaml` when the module is missing, and retry with `--break-system-packages` for a Python whose packages the system manages. If both attempts fail, the script names the pip command to run by hand and exits 2. On a locked-down machine, install it yourself first.
- **Encrypted payloads are out of scope.** Apple allows a payload to be encrypted for one specific device. This tool writes plain text payloads only, which is why the secrets section below matters.
- **DDM is not covered.** See the note below.
- **CI covers one Python version.** The workflow runs on Python 3.12 with a current pip, against a pinned schema commit. The floor the requirements section names is checked by hand: for this release the eval suite, the CLI checks and the PyYAML auto-install were run on the Python 3.9 and pip 21.2.4 that ship with macOS. The current Apple schema is checked by hand too.

## Roadmap

Candidates, in no particular order, and none of them promised:

- Make the cache directory configurable through an environment variable instead of the fixed `~/.cache/mobileconfig-builder/`.
- **DDM declarations from the same spec.** The biggest one, and the one that decides whether this tool still matters in two years. `references/ddm.md` has the full write-up; the short version is below.

## Declarative Device Management (DDM)

Apple ships new functionality to DDM first. DDM declarations are JSON, not
`.mobileconfig`, they live on the MDM server rather than in a file you can
hand someone, and the device holds the state and reports back instead of
installing a document. This tool builds Configuration Profiles and nothing
else today.

The interesting part is what a spec file actually is here. It describes
intent, not a file format: a passcode policy, a Wi-Fi network, a set of
restrictions. The same intent has a DDM shape, and Apple describes both sides
in the same YAML format, with the same `payloadkeys`, `type`, `presence`,
`range` and `subkeys` fields. The validator in this repository would work on
declarations unchanged. One spec, two outputs, one set of rules.

What stops that from being a weekend job:

- **The mapping is a translation, not a rename.** For the passcode policy, 11
  of 13 keys are pure renames (`forcePIN` to `RequirePasscode`), one inverts
  its meaning (`allowSimple: false` equals `RequireComplexPasscode: true`),
  and one moves its allowed range (`maxPINAgeInDays` starts at 1,
  `MaximumPasscodeAgeInDays` at 0). A table that misses cases like these
  produces output that is schema-valid and factually wrong.
- **Most payloads have no counterpart.** The `release` branch has 121 payload
  types under `mdm/profiles/` and 36 configuration declarations under
  `declarative/declarations/configurations/`. Wi-Fi, VPN, certificates and the
  whole restrictions family are not among them.
- **`com.apple.configuration.legacy` is the honest bridge.** Its only required
  key is `ProfileURL`: the declaration points at a profile that stays a
  profile. A useful export would go native where it can and fall back to
  `legacy` for the rest, and say which of the two happened for every payload.
  An export that hides that difference is worse than none.

Order of work, if it gets built: fetch the declaration schemas, then an
`inspect_declaration.py`, then a hand-maintained mapping table, then the
export. Step two already pays for itself, because it answers the question
whether a given payload has a declaration at all. Locally only schema
validity is testable; whether a device accepts a declaration shows up on an
MDM server.

## Releases and Versioning

The version lives in `VERSION` at the repository root, one line, semantic
versioning. Nothing else keeps a copy of it: `CHANGELOG.md` gets the matching
section, the archive carries the file itself, and CI fails if the two drift
apart.

Releasing is three steps, and the last one is deliberate handwork:

1. Set `VERSION`, add the section to `CHANGELOG.md`, merge to `main`.
2. `git tag v$(cat VERSION)` and push the tag.
3. `.github/workflows/release.yml` checks the tag against `VERSION`, runs
   `scripts/package_release.py`, and creates the release as a **draft** with
   `mobileconfig-builder.zip` attached. Read it, write the release text,
   publish.

To see what a release will contain before tagging:

```bash
python3 scripts/package_release.py dist/mobileconfig-builder.zip
unzip -Z1 dist/mobileconfig-builder.zip
```

The 0.x number is deliberate. The known gaps are listed under Limitations,
and the command line interface may still change between minor versions.

## License

Apache License 2.0, see [LICENSE](LICENSE).

The Apple profile schemas this tool validates against come from
[apple/device-management](https://github.com/apple/device-management) and are
MIT-licensed by Apple Inc. They are fetched at runtime into
`~/.cache/mobileconfig-builder/` and are not part of this repository. See
[NOTICE](NOTICE).
