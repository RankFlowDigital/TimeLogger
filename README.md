# Self-Hosted Team Monitoring & Roll Call System

## Tech Stack
- **Backend**: FastAPI (Python 3)
- **ORM**: SQLAlchemy + Alembic (PostgreSQL)
- **Frontend**: Jinja2 templates, vanilla JS, Tailwind-lite custom CSS
- **Deployment**: Vercel (Python serverless for API, static assets for templates)

## Phase Plan
1. **Core Platform** *(complete)*
   - FastAPI scaffolding, auth, dashboard, chat, and Alembic wiring.
2. **Scheduling & Attendance Rules** *(shipped here)*
   - Shift & leave CRUD, stricter lunch/break transitions, better history/profile views.
3. **Roll Calls & Deductions**
   - Cron endpoints, frontend polling/audio, deduction capture (partially in place → finish reporting polish & alerts).
4. **Polish & Deployment**
   - Sound toggles, responsive tweaks, CSV exports, incident logging.

## Environment & Secrets
Create a `.env` file (based on `.env.example`) before running the app:

```
SECRET_KEY=change-me
SESSION_COOKIE=team_monitor_session
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/team_monitor
ROLLCALL_TICK_TOKEN=dev-cron-token
```

> **Note:** update `DATABASE_URL` to your reachable Postgres. All settings are consumed through `pydantic-settings`.

## Database Migrations
Alembic is configured for Postgres. Generate + apply the baseline schema as soon as your database is reachable:

```bash
alembic revision --autogenerate -m "init"
alembic upgrade head
```

In this repo the initial migration (`alembic/versions/20241128_120000_init.py`) is already authored because the remote Postgres instance was not accessible from this environment. Re-run the commands above on your machine to ensure the schema actually exists.

## Scheduled Roll Calls
Two internal endpoints need to be pinged on a schedule:

| Endpoint | Purpose | Suggested cadence |
| --- | --- | --- |
| `POST /api/internal/rollcall-tick?token=$ROLLCALL_TICK_TOKEN` | Pre-plan five roll calls per org per hour with random 5–16 minute gaps | Every ~15 minutes |
| `POST /api/internal/rollcall-expire?token=$ROLLCALL_TICK_TOKEN` | Mark unanswered roll calls as `MISSED` | Every ~5 minutes |

`vercel.json` declares matching cron jobs for Vercel. If you deploy elsewhere, replicate the same cadence via your scheduler and supply either the `x-rollcall-token` header or the `?token=` query parameter.

`rollcall-tick` can be called less frequently because it now seeds the current hour with future `RollCall` rows whose `triggered_at` timestamps follow a random (unpredictable) pattern while honoring the 5-minute minimum and ~16-minute maximum spacing. Clients only see a roll call once its `triggered_at` time passes, ensuring the experience feels random despite relying on predictable cron hits.

### Roll Call Frequency Per Organization
- Organization owners can open the Admin dashboard and set the "roll calls per hour" value (1–12). The scheduler still spaces the prompts randomly between 5 and 16 minutes—it simply adjusts how many will occur inside the hour.
- Settings are stored per organization, so different teams can use different intensities without redeploying the app.

## Roll-Call Audio
Place a `rollcall.mp3` file inside `app/static/sounds/`. The frontend references `/static/sounds/rollcall.mp3` when a roll call modal opens. Any short attention-grabbing clip works; keep it lightweight (<200 KB) to avoid slow loads.

## Running Locally
```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Then open `http://localhost:8000`, sign up (first user becomes OWNER), add shifts/leaves, and exercise dashboards/chat/roll-call polling.

> **Neon tip:** set `DATABASE_URL` in `.env` to the Neon connection string before starting `uvicorn` so the local server talks to the managed database.

## Docker Deployment

You can run the entire stack inside a container (this is also how the Vercel deployment is configured now):

```bash
docker build -t timelogger .
docker run --env-file .env -p 8000:8000 timelogger
```

Vercel will automatically build the provided `Dockerfile` using `@vercel/docker`, so no additional runtime hacks are needed—`pip`/Python versions are defined entirely inside the container image.

## Demo Seed (Optional)

If you'd like instant demo data in your Neon (or local) database, run the helper script after setting `DATABASE_URL`:

```bash
python -m scripts.seed_demo
```

This creates a "Demo Org" with two accounts:

| Role | Email | Password |
| --- | --- | --- |
| Owner | `owner@example.com` | `demo1234` |
| Member | `agent@example.com` | `demo1234` |

You can log in with those credentials immediately. The script is idempotent, so re-running it simply ensures the records exist.
