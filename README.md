# Jarvis Caller Portal

An invite-only, read-only call-list portal for the Jarvis client-acquisition
pipeline. It is deliberately separate from the Windows Jarvis runtime: callers
can only load their allocated public-business phone leads and refresh to receive
another batch. They cannot reach Jarvis, research controls, Gmail, finance, or
Client Project Manager.

## Deployment shape

- **Netlify** serves `web/`, provides invite-only Identity accounts, and runs a
  small function that verifies the caller before proxying to the API.
- **Railway** hosts the FastAPI service, a PostgreSQL database, and a daily
  collector job.
- Browser clients never receive the Railway shared secret. The API rejects all
  caller endpoints unless the request came through the Netlify function.

## What refresh means

`Refresh call list` does not scrape the web from a caller's laptop. It assigns
that caller the next available batch of already-prepared leads. This keeps the
page fast, avoids duplicate calls between friends, and prevents callers from
triggering uncontrolled research. A Railway cron job replenishes the pool.

## Railway

Create one Railway project with:

1. A PostgreSQL service.
2. An **API** service from this directory. Set its start command to the default
   Docker command and add the variables below.
3. A second **collector** service from the same directory with start command
   `python -m app.collect`. Configure it as a Railway cron service with
   `0 1 * * *`, which is 06:30 Asia/Kolkata (Railway cron is UTC).

Set these variables on both API and collector services:

```text
DATABASE_URL=${{Postgres.DATABASE_URL}}
PORTAL_SHARED_SECRET=<long random value>
CITY=Bangalore
DAILY_LIMIT=20
BATCH_SIZE=6
```

The API service also needs `PORT`, supplied automatically by Railway. Do not
place any Jarvis, Gmail, OpenAI, or Netlify credentials in this project.

After the API receives a public domain, set `RAILWAY_API_BASE_URL` and the same
`PORTAL_SHARED_SECRET` in Netlify's site environment variables.

## Netlify

Create a site from this directory. Netlify reads `netlify.toml` and publishes
the `web/` directory.

1. Enable **Identity**.
2. Set registration to **invite only**; invite each friend individually.
3. Add the `caller` role to every invited friend.
4. Set `RAILWAY_API_BASE_URL` and `PORTAL_SHARED_SECRET` as server-side site
   environment variables.

The caller page only becomes visible after an Identity login. The sole
operational control after login is **Refresh call list**.

## Import the existing Jarvis leads

Do not commit `client_acquisition/leads.json` or copy it into the Netlify
frontend. Once the Railway API is live, run this from `D:\Jarvis` with a
temporary, shell-only secret value:

```powershell
$env:PORTAL_API_URL = 'https://your-railway-api.up.railway.app'
$env:PORTAL_SHARED_SECRET = '<the Railway secret>'
& .\voiceenv\Scripts\python.exe -B .\client_acquisition_portal\scripts\import_existing_leads.py
```

The importer sends only the existing public-business lead records to the API.
It does not send any Jarvis configuration or credentials.

## Local verification

```powershell
& .\voiceenv\Scripts\python.exe -B -m pytest -q client_acquisition_portal\tests
& .\voiceenv\Scripts\python.exe -B -m uvicorn app.main:app --app-dir client_acquisition_portal --port 8010
```

For a local API smoke request, send the configured portal secret in the
`x-portal-secret` header. The production caller UI must use the Netlify
function rather than calling Railway directly.
