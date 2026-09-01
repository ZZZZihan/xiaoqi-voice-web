# XiaoQi trusted LAN HTTPS

## Current endpoint

- Preferred phone URL: `https://pi5.local:8787/`
- Current-IP fallback: `https://192.168.5.12:8787/`
- Raspberry Pi service: `hermes-voice-web.service`
- Application directory: `/home/pi/.hermes/voice-web`
- Deployment backup: `/home/pi/.local/state/xiaoqi-https/20260831-112636`

The existing Hermes Voice Web process still owns port `8787`; systemd now starts Uvicorn with an explicit TLS certificate and key. No reverse proxy, public DNS, cloud tunnel, provider change, or secret migration was introduced.

HTTPS supplies the browser secure context needed by `navigator.mediaDevices.getUserMedia`. It does not add user authentication: another device that can reach the Raspberry Pi on the LAN can still load the application, just as it could before this change.

## Trust certificate for a phone

The phone must trust the dedicated local root certificate before opening the final URL. Do not bypass a browser certificate warning: a warning means trust installation is incomplete.

Use the DER certificate for phone installation:

- `docs/trusted-https/xiaoqi-local-ca.cer`
- SHA-256: `e9347ff4c7871b28097dc10f6916aa1c8c98ab33a0911b9c32aee974943fdbfe`
- Displayed root name: `XiaoQi LAN HTTPS Root 2026-08-31`
- Root certificate expiry: `2028-12-03 03:27:56 UTC`

The PEM copy at `docs/trusted-https/xiaoqi-local-ca.pem` is for command-line verification. Transfer the `.cer` file to the phone with AirDrop, a USB/file-transfer path, or another channel you control.

### iPhone or iPad

1. Open `xiaoqi-local-ca.cer` on the device and install the downloaded profile.
2. Go to **Settings > General > About > Certificate Trust Settings**.
3. Under **Enable full trust for root certificates**, enable full trust for **XiaoQi LAN HTTPS Root 2026-08-31**.
4. Open `https://pi5.local:8787/` in Safari. If `.local` resolution is unavailable, use `https://192.168.5.12:8787/`.
5. Tap **开启语音**, allow microphone access, and confirm that the page enters its listening state.

Apple documents that a manually installed certificate is not automatically trusted for SSL/TLS and that full trust must be enabled separately: <https://support.apple.com/en-us/102390>.

### Android

Android menu names vary by version and manufacturer. On a current Pixel, start at **Settings > Security & privacy > More security settings > Encryption & credentials > Install a certificate**. Install `xiaoqi-local-ca.cer` as a CA certificate, not as a client identity certificate. Then open the preferred URL in Chrome and allow microphone access.

Google's current Pixel certificate-management guide is: <https://support.google.com/pixelphone/answer/2844832?hl=en>.

If Chrome still shows a certificate warning, remove the partial installation and repeat the CA-certificate flow. Do not continue through the warning, because that is not the trusted-path acceptance condition.

## Certificate scope and renewal

The server leaf certificate is limited to:

- `DNS:pi5.local`
- `DNS:pi5`
- `IP:192.168.5.12`

Leaf fingerprint (SHA-256):

`7D:7E:4F:E4:B2:5E:79:C2:3C:84:F4:51:D9:5E:F5:1E:C9:2C:B2:AE:0C:25:EF:62:2A:D7:3C:3E:06:9F:69:0E`

The leaf certificate expires on `2027-10-02 03:27:56 UTC`. The one-use CA signing key was not copied to the Raspberry Pi and was deleted after deployment verification. Renewal therefore requires issuing a new dedicated CA/leaf pair and installing the new root on the phone; this intentionally prevents the current root from being used to sign additional certificates.

## Verification

From a machine on the same LAN:

```bash
curl --noproxy '*' \
  --cacert docs/trusted-https/xiaoqi-local-ca.pem \
  https://pi5.local:8787/health

openssl s_client \
  -connect 192.168.5.12:8787 \
  -servername pi5.local \
  -verify_hostname pi5.local \
  -verify_return_error \
  -CAfile docs/trusted-https/xiaoqi-local-ca.pem \
  </dev/null
```

Deployment acceptance on 2026-08-31 covered all of the following:

- TLS chain and hostname verification for both `pi5.local` and `192.168.5.12`.
- HTTP 200 for `/`, `/health`, `/call-mode.js`, `/app.css`, and `/ui-motion.js` over HTTPS.
- The old HTTP request to port `8787` no longer served the page.
- A 390 by 844 Chromium viewport reported `window.isSecureContext === true` and exposed `navigator.mediaDevices.getUserMedia`.
- A permission-granted fake microphone track became `live` and was immediately stopped to `ended`; this avoided recording a real microphone or calling the dialogue provider.
- The application runtime-file hashes and both existing `.env` hashes remained unchanged.

Actual phone acceptance remains a user-side check because installing a trusted root and granting real microphone permission are device security decisions.

## Rollback

Run the saved rollback script from the Mac:

```bash
ssh pi@192.168.5.12 \
  '/home/pi/.local/state/xiaoqi-https/20260831-112636/rollback-trusted-https.sh'
```

The script first snapshots the active HTTPS unit and certificate, then restores the backed-up pre-HTTPS service-unit contents and old certificate/key, reloads the user systemd manager, and restarts `hermes-voice-web.service` in its former HTTP mode. Verify the restored endpoint with:

```bash
curl --noproxy '*' http://192.168.5.12:8787/health
```

Rollback on the Raspberry Pi does not remove trust from a phone. Remove **XiaoQi LAN HTTPS Root 2026-08-31** separately from the phone's installed profiles or user credentials. The public CA files may remain on disk, but they are inactive and cannot sign anything because the CA private key was not retained.
