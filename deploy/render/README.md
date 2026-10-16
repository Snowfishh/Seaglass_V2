# Hosted demo on Render

The public demo runs at **<https://seaglass.onrender.com>**. A local run at
`http://127.0.0.1:8000` is reachable only from the machine running it.

## What the hosted mode is

The repository [`Dockerfile`](../../Dockerfile) starts the service with
`ASPIRE_HOSTED_DEMO=true`. In that mode the service:

- accepts only the hostnames listed in `ASPIRE_ALLOWED_HOSTS`. Loopback names are refused
  too unless they are listed, and refused requests are audited as `host_not_allowed`;
- lets any visitor pick a demo persona. Each browser session holds its own persona;
- sets the session cookie `Secure` (still `HttpOnly`, `SameSite=Strict`) and sends HSTS;
- trusts `X-Forwarded-Proto` from Render's TLS proxy. Only HTTPS state-changing requests
  are accepted, and the CSRF token plus an exact `https://<host>` Origin are still required.
  A request that the proxy forwarded as plain HTTP is audited as `insecure_transport`;
- runs `offline_extractive` over the fictional fixture only. It refuses to start if a live
  provider mode, a provider service or key, a non-fixture platform source, or a connectors
  config is set.

Default local runs are unchanged. Without `ASPIRE_HOSTED_DEMO=true` the service accepts
loopback hosts and loopback persona changes only. See
[security notes](../../docs/security.md#hosted-demo-mode-opt-in) for the full boundary.

## Service settings

| Setting | Value |
|---|---|
| Service type | Web service, runtime **Docker** |
| Repository and branch | `Snowfishh/Seaglass_V2`, `main` |
| Dockerfile and context | `./Dockerfile`, repository root (`.`) |
| Plan and region | **Free**, Singapore, one instance |
| Port | `7860`, the image's `EXPOSE` and Uvicorn port; Render detects it |
| Environment variable `ASPIRE_ALLOWED_HOSTS` | `seaglass.onrender.com`, exactly. Add a custom domain here too if one is attached. No wildcards |
| Secrets | **None**. The image generates its own session, audit and payload keys at every start |
| Persistent disk | **None**. Every restart resets the database, keys and audit log |
| Auto-deploy | **Off**. A push to `main` does not go live until a deploy is started manually |
| Health check path | Not set. `/ready` is suitable once a commit that has it is deployed (see below) |

`.dockerignore` is an allowlist (`pyproject.toml`, `requirements.lock`, `src/`, `data/`).
`.env` files, `var/`, keys, databases and local provider keys never enter the image, even if
they are present in the repository checkout.

## Shared-instance caveats (say these wherever the link is published)

- **All visitors share one instance and one database.** Revocation, sync and upstream-change
  actions are global. One visitor's revocation hides that source from everyone until the
  next restart.
- **The audit log records every visitor's queries.** Anyone can choose the auditor persona and
  see the safe audit trace for the demo tenant. Visitors should type nothing real.
- **State resets on restart.** That includes deploys, the free plan's sleep after about 15
  minutes without traffic, and Render maintenance. A new audit chain and new keys are
  generated every time.
- **The first request after sleep is slow.** Waking the free instance takes roughly 20–60
  seconds; later requests are fast.
- Personas are a selector, not authentication. The data is fictional, and no live model or
  real platform account is contacted.

## Checks after each deploy

1. The deploy log shows the `init-demo` JSON with `"provider_mode": "offline_extractive"`,
   then Uvicorn listening on `0.0.0.0:7860`. If the service fails at start with
   `Hosted demo mode needs ASPIRE_ALLOWED_HOSTS`, the variable is missing.
2. `https://seaglass.onrender.com/health` returns `{"status":"ok"}`.
   `/ready` returns 200 once the database is present and writable, the audit tables exist and
   the first platform sync has completed, and 503 with the failing check until then.
3. In the browser, choose **employee** on `/ask` and submit the prefilled question. The
   persona change is a CSRF- and Origin-checked POST, so this proves the proxy scheme
   handling works.
4. If every page returns `{"detail":"Invalid host"}`, the proxy isn't passing the public
   hostname in `Host`, or `ASPIRE_ALLOWED_HOSTS` doesn't match it. Don't add wildcards. Check
   which host arrives and list that exact name.

## Deployment record

- **15 October 2026.** The first deploy (`6670835`) built but exited at startup with "Fixture
  file must remain inside its root"; `d71a4be` fixed the fixture lookup for an installed
  package and went live.
- **16 October 2026.** Checked from outside Render against the live `d71a4be` deploy:
  `/health` returned 200 (22.7 s, waking from sleep), `/ask` returned 200, and a persona
  change followed by a typed four-platform question returned an answered, cited packet.
  `/ready` returned 404 because that deploy predates it. `main` was then at `67a3b21`, which
  is not deployed yet.
