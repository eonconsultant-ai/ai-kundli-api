# AI Kundli — backend source

This repository is the complete server source for **AI Kundli**, the Android app
published as `in.aikundli.app`. It is published under [AGPL-3.0](LICENSE) to meet
section 13 of that licence: the hosted API links `pyswisseph`, so people who use the
service over the network can obtain the corresponding source here.

- Live API: <https://aikundli-api-929797406951.us-central1.run.app>
- Health: `GET /health`, readiness: `GET /readyz`
- Request and response schemas: `app/schemas/`

Every release publishes the exact tree that was deployed, so the latest commit here
corresponds to the current production revision. The Android app is a separate program
that talks to this API over HTTP and is not part of this repository.

## What it does

- Swiss Ephemeris calculations: Kundli, divisional charts, Vimshottari dashas,
  Panchang, Ashtakoot matching, Life Chart and Lal Kitab placements.
- AI readings, chat and voice, proxied to Gemini (and optionally Groq for text chat)
  after the birth details are reduced to chart facts: only derived placements, dashas
  and the text the person typed or spoke leave this server.
- Daily quotas and Plus entitlements (Firestore in production, SQLite locally).
- Anonymous usage counters and an optional analytics summary behind a token.

## Run it

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

Copy `.env.example` to `.env` for local settings. Production uses the variables listed
in [`.env.production.example`](.env.production.example). No secrets are stored in this
repository — they live in Google Secret Manager and are mounted at runtime.

### Tests

```bash
pytest
ruff check .
```

## Deploy

The included `Dockerfile` builds the Cloud Run image. The Swiss Ephemeris data files
are checked in under `ephe/`; `scripts/fetch_ephemeris.py` fetches a different range.

## Privacy

Charts are computed from the birth details in each request and are not stored. The
server persists daily usage counters keyed by a random install ID, Plus entitlements
keyed by a Play purchase token, and AI reports people submit voluntarily.

## Licence

AGPL-3.0; see [LICENSE](LICENSE). `pyswisseph` and the Swiss Ephemeris data are
published by Astrodienst AG, which also sells a commercial Swiss Ephemeris licence for
projects that cannot accept the AGPL obligations.
