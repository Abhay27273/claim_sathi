# Deadline scheduler

`deadlines.py` is real, tested code -- a polling worker (not Celery/RQ; a plain
loop is plenty at this volume) that tracks the GRO 30-day response window and
the Ombudsman 1-year filing window in the `deadlines` table. Run it as its own
process: `python -m services.scheduler.deadlines`.

`schedule_gro_deadline()`/`schedule_ombudsman_deadline()` are called from
`services/gateway/main.py` right after a GRO letter is successfully drafted.

What's missing: an actual notification channel. `check_due_reminders()` logs a
warning when something's due -- that's the hook point for a real WhatsApp/email/
SMS send once one of those exists (none do yet; WhatsApp intake itself isn't
built either).
