# Web app

Next.js (App Router) frontend: upload documents -> free Case Strength report ->
Razorpay Checkout -> GRO letter -> escalate to Bima Bharosa -> Ombudsman. All
`app/api/*` routes are server-side proxies to the gateway that inject
`GATEWAY_API_KEY` themselves -- the browser never sees that key, only the
public Razorpay `key_id`.

## Setup

```bash
cp .env.local.example .env.local   # set GATEWAY_API_KEY to match the gateway's
npm install
npm run dev
```

## Known limitation, said plainly

**This has not been run.** `npm install` fails in the sandboxed dev environment
this was written in -- Node's TLS client gets a 403 from the npm registry where
`curl` to the identical URL gets 200, which looks like a TLS-fingerprint-based
filter rather than a real registry outage (the standard remediations,
`--use-system-ca` and `--strict-ssl=false`, were tried and didn't change the
403). That's a sandbox-specific network restriction, not expected to reproduce
on a normal machine. Run `npm install && npm run dev` on a machine with regular
internet access and treat this as unverified until that's done -- the backend
API it calls (every `/api/*` route here) has been tested directly and works;
this frontend code has only been reviewed, not executed.
