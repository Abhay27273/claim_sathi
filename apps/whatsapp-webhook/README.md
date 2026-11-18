# WhatsApp webhook

Built directly into the gateway (`services/gateway/whatsapp.py` +
`GET`/`POST /webhook/whatsapp` in `main.py`), not a separate deployable app --
simpler than running two servers for what the original plan sketched as its
own `apps/whatsapp-webhook/` service.

**Tested, no Meta account needed for this part:**
- `GET /webhook/whatsapp` -- the verification handshake. Correct
  `WHATSAPP_VERIFY_TOKEN` returns the challenge; wrong token gets 403.
- `POST /webhook/whatsapp` signature check -- a forged `X-Hub-Signature-256`
  is rejected (401); a correctly-HMAC'd one passes through.
- `parse_incoming_message()` against Meta's real (documented) payload shape --
  correctly extracts a document/image message, correctly ignores status
  callbacks and plain text (returns `None`, not an error).
- Phone -> policy auto-provisioning: a new number gets a user/family/
  family_member/policy shell created once; contacting again reuses it rather
  than duplicating.
- End to end: a correctly-signed webhook POST passes signature check, rate
  limiting, and provisioning, then fails exactly where it should --
  `download_media()` hitting the real Graph API with no real token. Confirmed
  the failure happens there, not earlier.

**Not tested -- needs a real WhatsApp Business Account:**
`download_media()` and `send_text_message()`, both needing `WHATSAPP_TOKEN`
and `WHATSAPP_PHONE_NUMBER_ID` from Meta's App Dashboard.

**Known v1 simplification, not a bug:** each incoming document triggers its
own case immediately. There's no multi-message accumulation yet (send
rejection letter, then separately send policy wording, then say "done") --
each document run on its own, so a user sending two documents gets two
separate cases rather than one case with two documents attached. A real
conversation state machine (buffer documents per phone in Redis, process on a
"done" command or a debounce timeout) is the natural next step, deliberately
not built here to keep this session's scope to what's testable.
