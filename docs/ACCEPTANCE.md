# Acceptance Checklist

## 2026-09-02 Explicit Raspberry Pi Audio Routing Fix

Target: Raspberry Pi 5 at `192.168.5.12`, app path `/home/pi/.hermes/voice-web`, HTTPS port `8787`.

### Root Cause and Delivered Scope

- The former page exposed a Pi playback choice, but `startCall()` unconditionally reset `hermes.playTarget` to `browser`; therefore clicking `小七音箱` was undone when continuous voice mode started.
- Continuous voice capture still called browser `getUserMedia()` unconditionally. There was no input selector connecting continuous mode to the existing Pi recording API, so the browser microphone remained the actual input even when the Pi hardware was connected.
- The voice panel now has two independent, persistent selectors: `浏览器麦克风 / 小七麦克风` for input and `浏览器扬声器 / 小七音箱` for output.
- Pi input turns use the existing server-side recording job and are bounded to 5–8 seconds per turn. Browser input retains browser-side silence endpointing.
- Pi output no longer resets at call start. Continuous mode also waits for Pi playback completion before opening the next input turn, reducing speaker-to-microphone echo overlap.

### Verification Evidence

- The Pi OS exposed `USB PnP Sound Device` as capture and `M83` as playback; `/health` reported both `pi_record.available=true` and `pi_playback.available=true`.
- Local regression passed `48` Python tests and `6` call-mode Node tests. Python compile, inline JavaScript parse, JavaScript syntax, and `git diff --check` passed.
- The staged server started independently on `127.0.0.1:18792`; STT, TTS, Pi recording, Pi playback, and both new selectors were available before the live cutover.
- The first cutover attempt used an immediate socket probe and rolled back before Uvicorn had finished opening its socket. The previous four runtime files were restored by their exact SHA-256 values, the resulting systemd start limit was reset, and the old service returned healthy with `NRestarts=0` before a second cutover was attempted.
- The final cutover waited for real HTTPS readiness. `hermes-voice-web.service` returned `active/running`, `NRestarts=0`, and `ExecMainStatus=0`; `/health` reported STT, TTS, Pi recording, and Pi playback ready.
- Deployed SHA-256 values matched the staged files: `server.py` `aec0d531...`, `index.html` `3fcc77cd...`, `app.css` `ae5d65f7...`, and `README.md` `a522b27e...`.
- Real Chromium at `390 by 844` loaded `https://192.168.5.12:8787`, enabled both Pi choices, selected both choices, and preserved `hermes.inputTarget=pi` plus `hermes.playTarget=pi` across reload. The page reported zero console errors.

### Remaining Physical Gate

- The deployment and routing-state checks intentionally did not start recording or audible playback. They do not prove that a person can be heard through the Pi microphone or hear the reply through the M83 speaker.
- Final physical acceptance requires the user to refresh their own browser, select both `小七麦克风` and `小七音箱`, start voice mode, speak one short sentence, hear the reply from the Pi speaker, then end voice mode.
- Pi input currently records fixed 5–8 second turns; wake word, acoustic echo cancellation, barge-in, and natural server-side silence endpointing remain outside this change.

### Rollback

Run `/home/pi/.local/state/xiaoqi-device-routing/20260902T035701Z/rollback-device-routing.sh` on the Pi to restore the four previous files and restart `hermes-voice-web.service`.

## 2026-09-01 Checksummed Application Release

Target: Raspberry Pi 5 at `192.168.5.12`, mDNS name `pi5.local`, app path `/home/pi/.hermes/voice-web`, HTTPS port `8787`.

### Delivered Scope

- Deployed the complete application release built from clean source commit `47f337d0b5ab40376b0474d73af72a8c2490c5e0`.
- Deployed `server.py`, `index.html`, `app.css`, `call-mode.js`, `ui-motion.js`, requirements, service scripts, HTTPS documentation, and public CA artifacts from one verified bundle.
- Preserved `/home/pi/.hermes/.env`, sessions, reminders, audio cache, and the HTTPS server private key.
- Created a restricted pre-deployment backup and executable rollback at `/home/pi/.local/state/xiaoqi-release/20260901-172924/`.

### Verification Evidence

- Local regression passed `45` Python tests and `6` call-mode Node tests; Python, JavaScript, shell syntax, and `git diff --check` passed.
- The release archive and every bundled file passed SHA-256 verification before staging on the Pi.
- All deployed runtime, documentation, and public-CA hashes matched the staged release.
- `hermes-voice-web.service` restarted `active/running` with `NRestarts=0` and `ExecMainStatus=0`.
- Trusted HTTPS returned HTTP 200 with certificate verification result 0 for `/`, `/health`, `/call-mode.js`, `/app.css`, and `/ui-motion.js`; MIME types were correct.
- OpenSSL hostname and chain verification for `pi5.local` returned `Verification: OK` and `Verify return code: 0`.
- `/health` reported `provider=zai`, `model=glm-5.1`; a post-restart `/api/chat` request succeeded and its diagnostic session was removed.
- A deployed-browser check at a 390 by 844 viewport reported `window.isSecureContext=true`, microphone API availability, an enabled start control, transition to `正在听，请直接说话`, successful hangup UI cleanup, no failed network responses, and no console errors.
- A 1440 by 320 short-desktop check confirmed the composer was visible and scroll-reachable; a 1000 by 900 reduced-motion check confirmed the motion preference and UI kit were active.
- Post-deployment `/api/respond` and synthetic-audio `/api/converse` checks succeeded. The latter transcribed `最终不属语音链路，正常。`, produced a GLM reply, and returned a valid `audio/ogg` file of `29224` bytes.
- Diagnostic sessions, downloaded test files, and generated diagnostic audio were removed after verification.

### Physical Phone Acceptance

- The phone owner confirmed the dedicated local CA was trusted and the final URL opened without a certificate warning.
- Real microphone permission was granted and two consecutive spoken turns were recognized, answered by GLM, and played audibly on the phone.
- After ending voice mode, the phone's system microphone indicator disappeared and the page controls returned to their idle state.
- This closes browser/phone end-to-end acceptance. Raspberry Pi-native microphone and speaker acceptance remains separate because current Pi audio hardware has not been revalidated.

### Rollback

Run `/home/pi/.local/state/xiaoqi-release/20260901-172924/rollback-release.sh` on the Pi to restore the complete previous runtime set and restart the service. This rollback does not change the GLM provider configuration or HTTPS certificates.

## 2026-09-01 GLM China Provider Migration

Target: Raspberry Pi 5 at `192.168.5.12`, Hermes home `/home/pi/.hermes`, web service `hermes-voice-web.service`.

### Delivered Scope

- Migrated the Hermes default provider from `xiaomi / mimo-v2.5-pro` to `zai / glm-5.1`.
- Configured the GLM China Coding Plan endpoint: `https://open.bigmodel.cn/api/coding/paas/v4`.
- Stored the credential only as `GLM_API_KEY` in `/home/pi/.hermes/.env`; the value was never printed into project files or acceptance output.
- Set the Hermes model context length to `200000`, matching the installed Hermes metadata for `glm-5.1`.
- Preserved the former provider configuration in a restricted rollback backup at `/home/pi/.local/state/xiaoqi-glm/20260901-172039/`.

### Verification Evidence

- The installed Hermes version was `v0.12.0`; its built-in `zai` provider recognizes `GLM_API_KEY`, the China Coding Plan endpoint, and `glm-5.1`.
- Controlled endpoint probes returned HTTP 200 for both the China and global Coding Plan endpoints; the active configuration intentionally uses the China endpoint.
- A direct quiet Hermes request returned exactly `GLM连接正常`.
- After service restart, `hermes-voice-web.service` was `active/running`, `NRestarts=0`, and `/health` reported `provider=zai`, `model=glm-5.1`.
- A real `/api/chat` request returned `小七GLM文本链路正常`; its diagnostic session was deleted.
- A real `/api/respond` request returned `小七GLM语音回复正常` and a downloadable `audio/ogg` response of `28419` bytes.
- A synthetic speech `/api/converse` request transcribed `今天天气很好。`, generated a GLM reply, and returned a downloadable `audio/ogg` response of `121801` bytes.
- The `/api/converse` check verified the complete backend chain: Volcengine STT -> Hermes GLM -> Edge TTS.
- All diagnostic sessions, downloaded temporary files, and generated diagnostic audio were removed after verification.

### Remaining User-Side Gate

- Physical-phone acceptance is still pending: install and fully trust the local CA, grant real microphone permission, complete two consecutive spoken turns, hear both replies, end voice mode, and confirm the microphone indicator disappears.
- Raspberry Pi-native microphone and speaker acceptance remains separate because the currently connected Pi audio hardware has not been revalidated.

### Rollback

Run `/home/pi/.local/state/xiaoqi-glm/20260901-172039/rollback-glm-provider.sh` on the Pi to restore the previous Hermes `.env` and `config.yaml`, then restart the web service.

## 2026-08-31 Trusted LAN HTTPS Rollout

Target: Raspberry Pi 5 at `192.168.5.12`, mDNS name `pi5.local`, app path `/home/pi/.hermes/voice-web`, HTTPS port `8787`.

### Delivered Scope

- Replaced only the Hermes Voice Web user-unit launch command so the existing Uvicorn process serves explicit TLS on port `8787`.
- Issued a dedicated local-CA server leaf for `pi5.local`, `pi5`, and `192.168.5.12`; the CA private key was never copied to the Pi and was deleted after verification.
- Preserved the application runtime files, model/provider configuration, and both existing `.env` files unchanged.
- Added durable public CA artifacts under `docs/trusted-https/` and operating instructions in `docs/TRUSTED_HTTPS.md`.

### Verification Evidence

- Pre-change backup and executable rollback: `/home/pi/.local/state/xiaoqi-https/20260831-112636/`.
- Staged certificate passed OpenSSL server-purpose verification for both `pi5.local` and `192.168.5.12`; leaf and private key matched.
- Remote `systemd-analyze --user verify` passed before service replacement.
- Service became `active/running` at `2026-08-31 11:29:25 CST`, PID `8208`, `NRestarts=0`, and `ExecMainStatus=0` during deployment acceptance.
- Mac LAN probes returned HTTP 200 with `ssl_verify_result=0` for the page and health endpoint through both the mDNS name and IP address.
- The served leaf fingerprint matched the staged leaf: `7D:7E:4F:E4:B2:5E:79:C2:3C:84:F4:51:D9:5E:F5:1E:C9:2C:B2:AE:0C:25:EF:62:2A:D7:3C:3E:06:9F:69:0E`.
- `/`, `/health`, `/call-mode.js`, `/app.css`, and `/ui-motion.js` all returned HTTP 200 over HTTPS; the former plain-HTTP probe returned no page.
- Real Chromium at a 390 by 844 phone viewport reported `https:`, `window.isSecureContext=true`, `navigator.mediaDevices` present, `getUserMedia` available, and an enabled start-call button.
- Browser microphone permission was `granted`; a fake audio track entered `live` with echo cancellation, noise suppression, and automatic gain control, then was immediately stopped to `ended` without recording the user or invoking the model.
- Runtime-file and `.env` hash checks passed after restart; the CA private key was absent from the Pi.
- Local regression remained green after the transport/documentation rollout: `python3 -m pytest -q` passed `44` tests and `node --test tests/test_call_mode.js` passed `6` tests; `git diff --check` also passed.

### Remaining User-Side Gate

- Server-side trusted-HTTPS and secure-context acceptance is complete against the dedicated CA.
- Physical-phone acceptance is pending the phone owner's security actions: install `docs/trusted-https/xiaoqi-local-ca.cer`, enable SSL/TLS trust, open `https://pi5.local:8787/`, grant real microphone permission, and confirm listening. A certificate warning is a failure, not an accepted bypass.
- This rollout changes transport trust only; it does not add application authentication or resolve the independently documented dialogue-provider credential failure.

### Rollback

- Run `ssh pi@192.168.5.12 '/home/pi/.local/state/xiaoqi-https/20260831-112636/rollback-trusted-https.sh'` to snapshot the active TLS state and restore the original HTTP unit plus old certificate/key.
- Remove `XiaoQi LAN HTTPS Root 2026-08-31` separately from the phone trust store after rollback.

## 2026-08-30 Automatic Call Mode Rollout

Target: Raspberry Pi 5 at `192.168.5.12`, SSH alias `pi5`, app path `/home/pi/.hermes/voice-web`, HTTP port `8787`.

### Delivered Scope

- Deployed source provenance: local Git commit `50763c91ebcc26f0565b1c89159ef5297bf7df2f` on branch `codex/automatic-voice`.
- `call-mode.js`: deep state-machine Module with the `listening -> processing -> speaking -> listening` loop, abortable hangup, no-speech recovery, and a three-error limit for genuine runtime failures.
- `index.html`: browser media Adapter with microphone permission handling, echo/noise constraints, local voice activity detection, approximately 1.1 second silence endpointing, backend STT fallback, reply playback awaiting, control locking, mobile-first call layout, and stable hangup cleanup.
- `server.py`: no new model path; it serves the state-machine asset and reuses the existing Hermes `/api/respond` and `/api/converse` Interfaces.
- Browser microphone and speaker are the accepted hardware path for this version. Raspberry Pi-native capture remains unavailable until capture hardware is reconnected.

### Verification Evidence

- Pre-deployment backup: `/home/pi/.hermes/voice-web/backups/20260830-1949-before-automatic-voice-1669cc3/`.
- Silence-fix backup: `/home/pi/.hermes/voice-web/backups/20260830-1958-before-silence-fix-5b64705/`.
- Local backend tests: `python3 -m pytest -q` passed, `40 passed` with two pre-existing FastAPI `on_event` deprecation warnings.
- Local state-machine tests: `node --test tests/test_call_mode.js` passed, `6 passed`.
- Local Python compile, JavaScript parse, and `git diff --check` passed.
- Remote service restart succeeded at `2026-08-30 19:49:54 CST`; observed PID `3658` and `systemctl --user is-active` returned `active`.
- Remote `GET /health` returned `ok: true`; Volcengine STT reported `runtime=volcengine-v2-ws`, `ready=true`; Edge TTS reported `voice=zh-CN-XiaoxiaoNeural`, `ready=true`.
- Remote `GET /call-mode.js` returned HTTP 200, `cache-control: no-store`, and `content-type: text/javascript; charset=utf-8`.
- Deployed file SHA-256 values matched the local files: `server.py` `dab1e44e...`, `call-mode.js` `c394e365...`, and final `index.html` `8de03651...`.
- Real Chromium through `ssh -N -L 18788:127.0.0.1:8787 pi5` verified secure-context microphone access, start-call control locking, automatic capture, recovery, and hangup control restoration.
- The first remote browser run exposed Volcengine code `1013`, `No valid speeches found in input audio`; after the fix, four consecutive empty-audio turns were classified as no speech and automatically returned to `listening` without consuming the genuine-error budget.
- A final remote hangup check returned `state=通话已结束`, `preview=通话已结束。`, start enabled, and hangup disabled.
- Isolated TTS acceptance passed: a controlled local-response request returned HTTP 200 and a retrievable Ogg audio URL. The temporary web session and generated audio were removed from active storage and retained only with the diagnostic backup evidence.

### Open Acceptance Gates at That Rollout

- At the time of this rollout, end-to-end Hermes answering was blocked by Xiaomi MiMo HTTP 401 `Invalid API Key`. This historical blocker was resolved by the 2026-09-01 GLM China provider migration documented above.
- `/health` confirms that the Hermes CLI and provider configuration exist; it does not make an authenticated model request, so `ok: true` does not override the observed 401.
- The Pi currently has no ALSA capture hardware and no connected USB peripherals. The former `plughw:CARD=Device,DEV=0` microphone and M83 playback device from the May evidence are absent. HDMI appears as a playback candidate, but audible Pi-side playback was not accepted.
- Direct `http://192.168.5.12:8787` is not a browser secure context. Use the documented localhost SSH tunnel for the basic version; trusted HTTPS is still required for direct mobile/tablet microphone access.
- Wake word, barge-in, and full-duplex echo-controlled conversation are outside this basic version.

## 2026-05-04 Historical Acceptance

Date: 2026-05-04
Target: Raspberry Pi at `192.168.0.87`, app path `/home/pi/.hermes/voice-web`, HTTPS port `8787`.

## Objective

Make Hermes Voice Web good enough to stand as an independent developer project: documented, runnable, testable, deployable, verified end to end, and able to offer both browser-side and Raspberry Pi-side recording options.

## Artifact Checklist

- `server.py`: FastAPI backend with health, sessions, text chat, XiaoQi/Soul study-assistant prompt identity, transcript response, audio upload, stoppable Raspberry Pi `arecord` capture jobs, cached in-process local STT, audio serving, Hermes integration, TTS, guarded subprocess STT timeouts, and Pi-side audio playback for generated replies.
- `index.html`: Single-page console with sessions, text composer, browser/Pi playback toggle, separate browser/Pi voice controls, shared stop control, health panel, responsive layout, and audio playback.
- `requirements.txt`: Runtime Python dependencies.
- `requirements-dev.txt`: Test dependencies.
- `scripts/run-voice-web.sh`: Portable run script with Hermes env detection and optional TLS certs.
- `scripts/install-user-service.sh`: User systemd installer for unattended startup.
- `tests/test_server.py`: Regression tests for sessions, chat persistence, prompt identity, TTS audio URLs, Pi playback, Pi recording status/endpoint/stop behavior, inline local STT routing, STT health readiness, and audio path traversal rejection.
- `README.md`: Install, run, deploy, configure, test, and troubleshoot documentation.

## Verification Evidence

- Local compile: `python3 -m py_compile server.py` passed.
- Frontend parse: extracted inline script from `index.html` and parsed it with Node successfully.
- Local tests: `python3 -m pytest -q` passed, `15 passed`.
- Remote compile: `/home/pi/.hermes/hermes-agent/venv/bin/python -m py_compile server.py` passed.
- Remote health: `GET /health` returned `ok: true`.
- Remote Hermes CLI: `/home/pi/.hermes/hermes-agent/venv/bin/hermes`.
- Remote chat provider: `xiaomi / mimo-v2.5-pro`.
- Remote STT: `provider=local`, `ready=true`, cached `model.bin` size `145217532`.
- Remote STT runtime after optimization: `runtime=inline-cache`, `model_loaded=true`, `local_model_path=/home/pi/.cache/huggingface/hub/models--Systran--faster-whisper-base/snapshots/ebe41f70d5b6dfa9166e2c581c45c9c0cfc57b66`.
- Remote TTS: `provider=edge`, `voice=zh-CN-XiaoxiaoNeural`, `ready=true`.
- Remote Pi recording health: `pi_record.available=true`, selected device `plughw:CARD=Device,DEV=0`, `rate=16000`, `channels=1`.
- Remote Pi capture device: `arecord -l` shows `USB PnP Sound Device`, card `Device`, device `0`.
- Remote Pi WAV capture: `arecord -D plughw:CARD=Device,DEV=0 -f S16_LE -r 16000 -c 1 -d 2` produced a `64044` byte RIFF/WAVE file.
- Pi recording stop API: `POST /api/pi-record/start` starts a job, `POST /api/pi-record/{job_id}/stop` signals the active `arecord` process, honors stop requests that arrive before `arecord` is attached to the job, and `GET /api/pi-record/{job_id}` exposes recording/processing/complete/error states for the frontend stop button.
- Remote Pi stop verification: a 30 second job was stopped after 2 seconds; status moved from `recording` to `processing`, `stop_requested=true`, `elapsed=2`, and `pgrep -a arecord` returned no active recorder process.
- Text API: `POST /api/chat` returned `OK` and persisted a session.
- Transcript-to-speech API: `POST /api/respond` returned `服务运行正常，随时可以对话。` and generated `/audio/tts_20260504_102520.ogg`.
- Audio serving: `GET /audio/tts_20260504_102520.ogg` returned an Ogg Opus audio file.
- Upload conversation API: `POST /api/converse` with the generated Ogg file returned HTTP 200, transcript `服務運行正常,隨時可以對話。`, reply `好的，收到。服务正常就好，有什么需要随时说。`, and generated `/audio/tts_20260504_102836.ogg`.
- Upload conversation API after inline-cache optimization: `POST /api/converse` with `/home/pi/.hermes/audio_cache/tts_20260504_102520.ogg` returned HTTP 200 in `13.82s`, transcript `服務運行正常,隨時可以對話。`, and generated `/audio/tts_20260504_151959.ogg`.
- Pi recording API: `POST /api/pi-record` performed a 2 second server-side recording and reached STT; because no one spoke into the microphone during the check, it returned controlled HTTP 400 `No speech was transcribed`.
- Remote process check: exactly one `uvicorn server:app --host 0.0.0.0 --port 8787` process is listening.

## Residual Risks

- Backend local STT is CPU-bound and still slow on the Raspberry Pi, especially the first transcription after restart. The web process now keeps the local faster-whisper model loaded for later recordings, with subprocess fallback retained for compatibility.
- Pi-side recording cannot be fully validated through chat/TTS without real speech at the microphone; the deployed endpoint was validated through recording, STT invocation, and controlled empty-speech handling.
- This repository directory is not currently a git repository, so commit hygiene and history-level review cannot be performed here.
- Remote pytest is not installed in the Hermes venv; full tests were run locally, while the remote runtime was validated by compile and API checks.
