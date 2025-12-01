# TimeTrack User Guide

This guide explains how the TimeTrack platform captures working time, how deductions affect totals, and how team members and admins should use the system day to day.

## 1. System Overview
- **Purpose** – Provide a verifiable record of when every teammate is working, on break, or offline, and layer in roll-call checks to discourage idle sessions.
- **Core Flow** – Users sign in, start and stop sessions (work, lunch, short break), respond to roll-call prompts, and review their dashboard summary. Admins monitor roster activity, review deductions, and export or audit summaries.
- **Data Backbone** – Every action persists to PostgreSQL via FastAPI. Alembic migrations keep the schema consistent across deployments.

## 2. Key Concepts
- **Organization** – The tenant container. Each org has one owner plus members. Settings such as expected roll-call cadence live here.
- **Roles** – `OWNER` can manage users, shifts, and reports. `MEMBER/AGENT` focuses on their own sessions and roll calls.
- **Shifts & Windows** – Shifts define when work minutes can accrue. Only time that overlaps a scheduled shift window counts toward work totals, and shift start/end times convert automatically into each teammate’s preferred timezone.
- **Work Sessions** – Timestamped records with a `session_type` (`WORK`, `LUNCH`, `SHORT_BREAK`). Sessions open when you click a tile in the dashboard and close when you end it.
- **Roll Calls** – Randomized spot checks. A pending roll call shows on the dashboard banner; failing to respond in time creates an automatic deduction.
- **Deductions** – Minutes removed from net hours when breaks exceed allowances or when roll-call responses are late.
- **Manual Overrides** – Owners/admins can temporarily allow a teammate to start work without an assigned shift when schedules change last-minute.

## 3. How Time Is Counted
1. **Capture** – Each session records `started_at` and (when closed) `ended_at`. Open sessions continue accruing until stopped.
2. **Shift Alignment** – The attendance service slices every session against the day’s shift windows. Time outside scheduled windows is ignored, preventing accidental overnight accruals.
3. **Categorization** – Minutes are bucketed as:
   - `work_minutes` – Valid in-shift work time.
   - `lunch_minutes` – Lunch sessions within the shift.
   - `short_break_minutes` – Quick break sessions.
4. **Allowances** – Lunch has a 60-minute daily allowance; short breaks have 30 minutes. Anything above these thresholds is considered **overbreak** time.
5. **Roll-Call Penalties** – Each late roll-call response adds `ceil(delay_seconds / 60)` minutes of deduction for that date.
6. **Net Hours Formula** – `net_hours = max(0, min(8, work_minutes / 60) - (overbreak_minutes + rollcall_deduction_minutes) / 60)`. Totals are capped at one standard shift (8 hours) and never drop below zero.
7. **Historical Windows** – Weekly, monthly, and custom ranges sum the day-level summaries (no extra deductions are created during aggregation).

## 4. Using the Dashboard
- **Session Controls** – Use the prominent buttons to start Work, Lunch, or Break. Always close one session before opening another to avoid overlapping entries.
- **My Shifts Card** – The dashboard lists upcoming shifts in whatever timezone you select (device, personal preference, etc.), so everyone sees their schedule in local time while the system stores the canonical timezone from the admin who created it.
- **Timeline & Table** – Review the chronological list of events to verify every transition. Editable data lives in the Admin > Shifts/Reports pages; the dashboard is a read-only view for transparency.
- **Summary Card** – Shows today’s work, break, and deduction totals along with computed net hours.
- **Roll-Call Banner** – Appears when a roll call targets you. Click “Confirm” immediately to avoid deductions.
- **Team Roster** – Owners can see who is actively clocked in, what type of session they’re in, and since when. Device timezone labels help correlate remote teammates.

## 5. Range Summaries & Reports
- **Day/Week/Month Toggles** – On the dashboard summary widget, choose the preset that matches your review period. Weekly spans the last 7 days; Monthly spans the last 30.
- **Custom Range** – Enter explicit start/end dates to audit PTO weeks, compliance periods, or payroll cycles.
- **Admin Reports** – The Admin > Reports page layers organizational filters (team member, date range) on top of the same underlying calculations.

## 6. Recommended Daily Workflow
1. **Login & Confirm Status** – Ensure your timezone is correct (Profile page) so shift windows align properly.
2. **Start Work** – Hit “Start Work” right as your shift begins. The system records server time to prevent local clock tampering.
3. **Use Break Buttons** – Always transition to “Start Lunch” or “Start Break” before stepping away, then “End” when you return. Staying within the allowance avoids deductions automatically.
4. **Respond to Roll Calls** – Keep the dashboard tab open or enable email/push alerts (if configured). Acknowledge within the deadline to prevent penalties.
5. **End Work** – Close the session at shift end. Leaving a session open past your shift won’t add extra time (it is trimmed), but it may trigger compliance alerts.
6. **Review Summary** – Before logging off, glance at the summary widget. If you see unexpected deductions, expand the timeline to identify the underlying session.

## 7. Admin Best Practices
- **Shift Hygiene** – Keep shift templates up to date so new employees receive the correct windows and the attendance service has accurate bounds.
- **Timezone Accuracy** – When creating or editing shifts, the admin or owner’s profile timezone is captured as the template’s canonical timezone, and downstream dashboards convert that window for every viewer automatically.
- **Roster Monitoring** – Use the live roster to spot idle sessions (e.g., user “on Work” for hours without roll calls). Ping them or schedule an ad-hoc roll call.
- **Deductions Audit** – Admins can inspect `Admin > Reports` to see overbreak vs roll-call deductions per user and make adjustments when legitimate exceptions occur.
- **Manual Start Overrides** – If someone needs to clock in before their shift is configured, go to `Admin > Shifts`, grant a manual start, and remember to revoke it once their template is set.
- **Roll-Call Scheduler** – Cron endpoints (see `vercel.json`) run every 5 and 15 minutes; ensure they stay configured in hosting to keep roll calls flowing.

## 8. Troubleshooting
- **Can’t Start a Session** – Make sure a previous session ended; the system prevents overlapping entries. Refresh the page to fetch the latest open session state.
- **Totals Look Low** – Confirm your shift calendar matches when you actually worked. Time outside shifts is intentionally excluded.
- **Unexpected Overbreak** – Lunch over 60 minutes and combined short breaks over 30 minutes will auto-deduct. Split longer breaks into two sessions if policy allows to keep tracking explicit.
- **Roll-Call Deductions** – Check the timeline for “Roll-call Late” events. If you responded on time but still see a penalty, capture the timestamp and contact an admin to adjust the deduction.
- **Timezone Drift** – If you travel, update your profile timezone so the dashboard labels and shift windows align with local time.

## 9. Where to Go Next
- **Profile Page** – Update password, timezone, and notification preferences.
- **Admin Pages** – Manage users, assign shifts, review leaves, and export reports.
- **Scripts** – For self-hosted deployments, use `scripts/runserver.py` to ensure migrations run before the server boots, and run `scripts/smoke_test.py` in CI to catch environment issues early.

Armed with this guide, both team members and administrators can confidently operate TimeTrack, understand how every minute is computed, and maintain consistent, audit-ready records.