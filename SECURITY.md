# Security Policy

## Supported Versions

No tags, no releases, three commits. Only the current state of `main` is supported and only `main`
gets fixed. If you run an older commit, update before you report anything.

## Reporting a Vulnerability

Use GitHub Private Vulnerability Reporting, which is enabled on this repo:

**https://github.com/GodModeAI2025/mobileconfig-builder/security/advisories/new**

Do not open a public issue for a security problem. This repo is public, issues are public from the
first second, and this tool handles Wi-Fi passphrases, VPN shared secrets and signing keys.

Expect an acknowledgement within a few days and an assessment within two weeks. This is a one person
side project without an on-call rotation. If a report sits longer than two weeks, ping the advisory
thread. Useful in a report: the sanitized spec file, the exact command line, the schema cache state.

## Threat Model

**What is worth stealing.** The product of this tool is a file that carries credentials in
cleartext, and everything below follows from that. A generated `.mobileconfig` contains whatever
secrets the spec holds, as plain XML: the shipped example carries a WPA passphrase
(`assets/examples/wifi_guest.json:17`), and the payload types for VPN, mail and PKCS#12 carry shared
secrets, account passwords and key material the same way. Next to the output sits the signing key,
referenced by path via `--sign-key`.

**Attack path 1: the profile lands in git.** The quick start writes into the working directory
(`-o wifi.mobileconfig` in `README.md:26`, `-o guest-wifi.mobileconfig` in `index.html:509`), which
is the repo root if you follow it literally. `.gitignore` has one line, `.DS_Store`, so `git add -A`
commits the passphrase. Secret scanning and push protection are enabled here, but they match
provider token patterns, not a WPA passphrase in an XML plist, and non-provider patterns are off.

**Attack path 2: signing fails and the cleartext stays behind.** `scripts/build_mobileconfig.py`
writes the unsigned plist to `<output>.unsigned.mobileconfig` in lines 361-366, calls `sign_profile`,
and unlinks the temp file only afterwards. `sign_profile` raises at line 299 when `openssl` exits
non-zero, so `tmp.unlink()` is never reached. Reproduced with a nonexistent cert path:
`leak.unsigned.mobileconfig` stayed on disk, mode 0644, containing
`<key>Password</key><string>supersecret123</string>`, next to a zero byte `leak.mobileconfig` that
reads like a finished profile. The exception surfaced as a traceback.

**Attack path 3: a poisoned schema cache.** `fetch_schema.py:76-77` returns a file from
`~/.cache/mobileconfig-builder/<branch>/` whenever it exists and `--refresh` is not set. No TTL, no
checksum, no ETag. Whoever can write that directory decides what `--validate-strict` accepts.

**Attack path 4: the operator trusts the validator.** A profile can exit 0 under `--validate-strict`
and still be wrong, see gaps 3, 4 and 5. The damage is not a compromised host, it is a wrong policy
shipped to a fleet with a green check behind it.

Out of scope: the MDM server, the device, Apple's own schema, and the device trust stores.

## Trust Boundaries

**The private signing key never enters this process.** It is passed by path and handed to
`openssl smime` as an argv value (`build_mobileconfig.py:286-299`). Python never reads the file.
Keep it that way in any patch.

**No private keys through chat.** The rule lives in `references/signing.md:50-54` and belongs in a
security policy too: never paste a private key into a chat window, with Claude or any other
assistant. Give the file path. An assistant has to refuse the key and must not offer a generated
self-signed cert as a workaround, since such a profile still shows "Not Verified" on the device.

Treated as trusted, without verification:

- Every path you pass to `--sign-cert`, `--sign-key`, `--sign-ca`. They are forwarded to `openssl`
  uninspected.
- HTTPS responses from `api.github.com` and `raw.githubusercontent.com`. Filenames from the API
  listing become cache paths directly (`fetch_schema.py:58-59`, `69-70`), filtered only by suffix.
- Anything already sitting in the local schema cache.
- Every spec value that passes the schema check. Passwords are copied verbatim into the output, and
  `evals/run_tests.py:157-158` asserts exactly that.

The boundary runs between spec file and output file. What goes into the spec is your job, and
everything after the output (transport, MDM import, device install) is outside this tool.

## Known Gaps

All open in `main` today.

1. **Cleartext leftover after a failed signing run.** Attack path 2. Until it is fixed, run
   `rm -f *.unsigned.mobileconfig` after a failed attempt and delete the zero byte output file.
2. **`.gitignore` covers nothing relevant.** One line, `.DS_Store`. Missing: `*.mobileconfig`,
   `*.unsigned.mobileconfig`, `*.pem`, `*.key`, `*.p12`, `__pycache__`. Cheapest gap in this list,
   still open.
3. **`--validate-strict` does not look at the top level.** `build_profile`
   (`build_mobileconfig.py:222-280`) validates only the entries in `PayloadContent`; `meta` is
   copied through unchecked at line 278, and `TopLevel.yaml` is never loaded. Verified: a spec with
   an invented `TotallyMadeUpKey`, `ConsentText` as an integer (schema: `<dictionary>`) and
   `PayloadRemovalDisallowed` as a string (schema: `<boolean>`) exits 0 and writes all three into
   the profile.
4. **Seven payload types disable the unknown-key check.** `_check_keys` skips that branch when the
   schema declares an `ANY` key (`build_mobileconfig.py:153`, `170`). In the release branch that is
   the seven `com.apple.*ethernet*.managed` schemas, where unknown keys pass without complaint.
5. **Two payload types collide and the two scripts disagree.** Apple's release branch ships 127 YAML
   files for 121 payload types; `com.apple.MCX` appears in 6 of them, `com.apple.extensiblesso` in
   2. `inspect_payload.py:31-41` returns the first match, `load_all_schemas`
   (`build_mobileconfig.py:61-81`) overwrites until the last one wins. Verified:
   `inspect_payload.py com.apple.MCX` documents `EnableGuestAccount` from
   `com.apple.MCX(Accounts).yaml`, a build with that key fails with
   `unknown key 'EnableGuestAccount'` because validation ran against `com.apple.MCX(WiFi).yaml`.
   Hits FileVault and Kerberos SSO. `references/payload-cheatsheet.md:106` names it, the code does
   not handle it.
6. **Output files get default permissions.** `plistlib.dump` into a plain `open(..., "wb")`
   (`build_mobileconfig.py:362-363`, `371-372`), no chmod. Measured: 0644 for a profile holding a
   WPA passphrase, readable by everyone on a shared machine.
7. **Validation errors echo the offending value.** `build_mobileconfig.py:115` and `:130` print
   `value {value!r}` on rangelist and regex mismatches. No password key in the current Apple schema
   carries such a constraint, so no leak is known today, but the code has no notion of a secret key
   and the message lands in stderr and in any CI log.
8. **`ensure_yaml()` installs a package on its own.** `fetch_schema.py:30-38` runs
   `pip install --quiet --break-system-packages pyyaml` on first use, unpinned and without hash
   check. On the macOS system Python 3.9 that pip rejects the flag and the script dies with a
   traceback. Install PyYAML yourself beforehand.
9. **The schema cache never expires and is never checked.** Attack path 3, `--refresh` is manual.
10. **`_SCHEMA_CACHE` has no branch key.** The global at `build_mobileconfig.py:58` is filled once,
    `load_all_schemas` returns it for any branch (line 65), and `get_schema` (85-86) drops the
    offline flag. The CLI masks this via the preload at line 228, a direct import does not.
11. **The shipped examples contain plausible cleartext passwords.**
    `assets/examples/wifi_guest.json:17`, `assets/examples/classroom_ipad.json:17`. Fine as demo
    values, dangerous as a copy template, because a copy keeps the README output path.
12. **No way to check an existing profile.** Validation happens only while building from a spec.
    Nothing reads a `.mobileconfig` back in, verifies its signature, or scans it for secrets.

## What This Project Does Not Do

- **No secret management.** Passwords in your spec end up in the output in cleartext. That is the
  profile format, not a bug. Anything stricter happens before the spec and after the output.
- **No payload encryption.** Per device payload encryption, the way an MDM does it, is missing.
- **No judgment about your certificate.** EKU, expiry, key usage, chain and issuer trust are
  unchecked. `openssl` signs with whatever you point it at.
- **No policy review.** Schema valid means keys and types match Apple's YAML. It says nothing about
  whether a device accepts the profile or whether the policy behind it makes sense.
- **Unsigned profiles are for lab use.** Do not deploy them to production or through an MDM.
  `README.md:88` and `references/signing.md:3` say the same, nothing in the code enforces it:
  `build_mobileconfig.py:373-375` prints a hint and exits 0.
- **No guarantee about Apple's schema.** Whatever `apple/device-management` publishes is used as is,
  including its errors.
- **No SLA.** See the reporting section for what a response actually means here.
