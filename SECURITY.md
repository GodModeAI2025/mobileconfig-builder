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
is the repo root if you follow it literally. `.gitignore` now covers `*.mobileconfig` and key
material as a backstop, but a spec file with a real password is not covered by any pattern, and
`tools/scan_secrets.py` only sees what is already staged. Secret scanning and push protection are
enabled here, but they match provider token patterns, not a WPA passphrase in an XML plist, and
non-provider patterns are off.

**Attack path 2: signing fails and the cleartext stays behind. Closed.** Until the keychain work,
`scripts/build_mobileconfig.py` wrote the unsigned plist to `<output>.unsigned.mobileconfig`, called
`sign_profile`, and unlinked the temp file only afterwards. `sign_profile` raised when `openssl`
exited non-zero, so `tmp.unlink()` was never reached. Reproduced with a nonexistent cert path:
`leak.unsigned.mobileconfig` stayed on disk, mode 0644, containing
`<key>Password</key><string>supersecret123</string>`, next to a zero byte `leak.mobileconfig` that
reads like a finished profile, and the exception surfaced as a traceback. The unsigned plist now
goes to the signing tool over stdin and is never written to disk. The message is a message and not
a traceback, and the exit code is 2.

The first fix for the leftover file was half of one, and this is where it was half: the output file
was removed on failure *unless it existed before the run*. Which is the common case. A second build
onto the same path, after any change to the spec, hits an existing file, and both signing tools
truncate their output file when they open it. Measured with `wifi_guest.json`: 1378 bytes of valid
profile before the failed run, 0 bytes after, and the cleanup branch skipped the file because it
had existed. Signing now writes to a temporary file in the target directory and only moves it onto
the output path, with `os.replace`, once every check has passed. The output path therefore either
keeps what it had or gets a verified signature, and there is no longer a condition on when a file
may be deleted. Eval 7 asserts all of it, including that no file in the output directory contains
the example password and that an existing profile survives a failed run byte for byte.

The temporary file cost two cases of its own, and both are fixed rather than described away. A
symbolic link as the output path used to be written through, leaving the link in place; `os.replace`
on the link name replaced the link with a regular file and left the linked file at 0 bytes. Work
now happens on the `realpath`-resolved path, so the linked file gets the profile again, as it did
before. And the temporary file needs write permission on the *directory*, not just on the output
file: in a directory with mode 555 the run ends with exit 2 and a message, and whatever was at the
output path stays untouched. A CI step signs against all of it with a self-signed certificate:
normal case, a 254 character output name, symlink, directory as output path, and the failed second
build. That step is red against the state this repository had before these fixes.

**Attack path 3: a poisoned schema cache.** `fetch_schema.py:76-77` returns a file from
`~/.cache/mobileconfig-builder/<branch>/` whenever it exists and `--refresh` is not set. No TTL, no
checksum, no ETag. Whoever can write that directory decides what `--validate-strict` accepts.

**Attack path 4: the operator trusts the validator.** A profile can exit 0 under `--validate-strict`
and still be wrong, see gaps 3, 4 and 5. The damage is not a compromised host, it is a wrong policy
shipped to a fleet with a green check behind it.

Out of scope: the MDM server, the device, Apple's own schema, and the device trust stores.

## Trust Boundaries

**The private signing key never enters this process.** With `--sign-cert` it is passed by path and
handed to `openssl smime` as an argv value. With `--sign-identity` it is never named at all: the
key stays in the macOS keychain and `/usr/bin/security cms` signs inside it. Python reads neither.
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

Every item below was measured against the current `main`, not carried over from an earlier list.
The closed ones are named at the end, because the paragraphs further up still mention them.

1. **Seven payload types disable the unknown-key check.** `_check_keys` skips that branch when the
   schema declares an `ANY` key. Counted against the pinned release branch: 121 payload types, of
   which exactly seven carry such a key, all of them `com.apple.*ethernet*.managed`. Unknown keys
   pass there without complaint, in the build and in `validate_mobileconfig.py` alike.
2. **The unsigned output file gets default permissions.** `build_mobileconfig.py:1131` writes the
   profile with `write_bytes` and no chmod. Measured: 0644 for a profile holding a WPA passphrase,
   readable by everyone on a shared machine. The signed path is different, it sets the mode on its
   temporary file before the content goes in.
3. **Validation errors echo the offending value.** `build_mobileconfig.py:141` and `:156` print
   `value {value!r}` on rangelist and regex mismatches. No password key in the current Apple schema
   carries such a constraint, so no leak is known today, but the code has no notion of a secret key
   and the message lands in stderr and in any CI log.
4. **`ensure_yaml()` installs a package on its own.** It runs `pip install --quiet pyyaml` on first
   use and retries with `--break-system-packages`, unpinned and without a hash check. Install
   PyYAML yourself beforehand if that is not acceptable.
5. **The schema cache never expires and is never checked.** Attack path 3, `--refresh` is manual.
   `get_schema` takes no offline flag either: it uses what is remembered for the branch and goes to
   the network otherwise. Call `load_all_schemas(branch, offline=True)` first if a run must stay
   off the network.
6. **The shipped examples contain plausible cleartext passwords.**
   `assets/examples/wifi_guest.json:17`, `assets/examples/classroom_ipad.json:17`. Fine as demo
   values, dangerous as a copy template, because a copy keeps the README output path.
7. **`__file__` in a spec reads any path the process can read.** The marker takes the bytes as they
   are, with no allowlist and no size limit, and they end up in the profile in cleartext. A spec
   somebody else wrote deserves a look at its `__file__` entries before you build it.
8. **The validator does not say who signed a profile.** `validate_mobileconfig.py` unpacks a PKCS#7
   container with `openssl smime -verify -noverify`, which checks the signature but skips the
   certificate chain. A valid signature from an issuer nobody trusts passes. Nothing scans a
   finished profile for secrets either; `tools/scan_secrets.py` looks at the repository, not at a
   profile you hand it.

Closed since this list was first written, and named here because the sections above still refer to
them: the cleartext `.unsigned.mobileconfig` left behind by a failed signing run, which no longer
touches the disk at all because the profile goes to the signing tool through stdin; a `.gitignore`
that covered only `.DS_Store`; `--validate-strict` ignoring the top level, which is now checked
against `TopLevel.yaml`; the colliding payload types that build and inspect resolved in opposite
directions, where the schema loader now merges the files and a key counts as required only when
every file demands it; `_SCHEMA_CACHE` without a branch key; and the missing way to check a profile
that already exists.

## What This Project Does Not Do

- **No secret management.** Passwords in your spec end up in the output in cleartext. That is the
  profile format, not a bug. Anything stricter happens before the spec and after the output.
- **No payload encryption.** Per device payload encryption, the way an MDM does it, is missing.
- **No judgment about your certificate.** EKU, expiry, key usage, chain and issuer trust are
  unchecked. `openssl` signs with whatever you point it at, and `security cms` signs with whatever
  identity you name. What the tool does check is that the result is a PKCS#7 structure that unpacks
  back to exactly the profile it built, because `security cms -S` reports success on stderr-only
  failures. It also checks that the name it hands to `security cms -N` belongs to exactly one
  certificate in the keychain it was pointed at, and refuses otherwise. That check is about
  identifying the signer, not about judging it: `-N` selects by name alone and takes no
  fingerprint, so with two certificates of the same name the tool could not say afterwards which
  one signed. Whether `security cms` restricts itself to the keychain given with `--keychain` is
  not measured here and not claimed.
- **No policy review.** Schema valid means keys and types match Apple's YAML. It says nothing about
  whether a device accepts the profile or whether the policy behind it makes sense.
- **Unsigned profiles are for lab use.** Do not deploy them to production or through an MDM.
  `README.md:88` and `references/signing.md:3` say the same, nothing in the code enforces it:
  `build_mobileconfig.py:373-375` prints a hint and exits 0.
- **No guarantee about Apple's schema.** Whatever `apple/device-management` publishes is used as is,
  including its errors.
- **No SLA.** See the reporting section for what a response actually means here.
