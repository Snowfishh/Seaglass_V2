# Hosted demo on a Hugging Face Docker Space

This note prepares an optional public demo. Nothing here has been deployed. The project
README stays as it is. Only the Space's own copy of `README.md` takes the front matter below.

## What the hosted mode is

The repository [`Dockerfile`](../../Dockerfile) starts the service with
`ASPIRE_HOSTED_DEMO=true`. In that mode the service:

- accepts only the hostnames listed in `ASPIRE_ALLOWED_HOSTS`. Loopback names are refused
  too unless they are listed, and refused requests are audited as `host_not_allowed`;
- lets any visitor pick a demo persona. Each browser session holds its own persona;
- sets the session cookie `Secure` (still `HttpOnly`, `SameSite=Strict`) and sends HSTS;
- trusts `X-Forwarded-Proto` from the Space's TLS proxy. Only HTTPS state-changing requests
  are accepted, and the CSRF token plus an exact `https://<host>` Origin are still required.
  A request that the proxy forwarded as plain HTTP is audited as `insecure_transport`;
- runs `offline_extractive` over the fictional fixture only. It refuses to start if a live
  provider mode, a provider service or key, a non-fixture platform source, or a connectors
  config is set.

Default local runs are unchanged. Without `ASPIRE_HOSTED_DEMO=true` the service accepts
loopback hosts and loopback persona changes only.

## Exact Space settings

| Setting | Value |
|---|---|
| Space SDK | **Docker**, blank template |
| Hardware | **CPU basic** (free) |
| Visibility | Public |
| Port | `7860` (`app_port` below; also the image's `EXPOSE`) |
| Variable `ASPIRE_ALLOWED_HOSTS` | `<owner>-<space-name>.hf.space`, lowercase. Hugging Face turns `.` and `_` in the names into `-` |
| Secrets | **None**. The image generates its own session, audit and payload keys at every start |
| Persistent storage | **None**. Every restart resets the database, keys and audit log |

The Space `README.md` front matter:

```yaml
---
title: Aspire Internal Brain
emoji: 🔐
colorFrom: blue
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
license: apache-2.0
short_description: Permission-aware four-platform retrieval demo (fictional data)
---
```

The Space repository needs `Dockerfile`, `.dockerignore`, `pyproject.toml`,
`requirements.lock`, `src/` and `data/`, plus that README. `.dockerignore` is an allowlist.
`.env` files, `var/`, keys, databases and local provider keys never enter the image, even if
they are present in the pushed tree.

## Link the direct URL

Give judges `https://<owner>-<space-name>.hf.space`. Don't give them the
`huggingface.co/spaces/...` page. That page embeds the app in a cross-site iframe. The app
sends `frame-ancestors 'none'`, and its `SameSite=Strict` cookie is not sent inside a
third-party frame, so the embedded view stays blank. This is deliberate: the hosted mode
doesn't loosen framing or cookie rules.

## Shared-instance caveats (say these wherever the link is published)

- **All visitors share one instance and one database.** Revocation, sync and upstream-change
  actions are global. One visitor's revocation hides that source from everyone until the
  next restart.
- **The audit log records every visitor's queries.** Anyone can choose the auditor persona and
  see the safe audit trace for the demo tenant. Visitors should type nothing real.
- **State resets on restart.** That includes rebuilds, the free tier's sleep after inactivity,
  and Hugging Face maintenance. A new audit chain and new keys are generated every time.
- Personas are a selector, not authentication. The data is fictional, and no live model or
  real platform account is contacted.

## Checks after the first deploy (not yet done)

1. The Space log shows the `init-demo` JSON with `"provider_mode": "offline_extractive"`,
   then Uvicorn listening on `0.0.0.0:7860`. If the Space fails at start with
   `Hosted demo mode needs ASPIRE_ALLOWED_HOSTS`, the variable is missing.
2. `https://<owner>-<space-name>.hf.space/health` returns `{"status":"ok"}`.
3. In the browser, choose **employee** on `/ask` and submit the prefilled question. The
   persona change is a CSRF- and Origin-checked POST, so this proves the proxy scheme
   handling works.
4. If every page returns `{"detail":"Invalid host"}`, the proxy isn't passing the public
   hostname in `Host`. Don't add wildcards. Check which host arrives and list that exact name.

This setup assumes the Space proxy forwards the public `Host` and sets
`X-Forwarded-Proto: https`. It has only been checked with local tests and a local Uvicorn
run, not on Hugging Face itself. No Docker image was built in the preparation session,
because Docker wasn't available there.
