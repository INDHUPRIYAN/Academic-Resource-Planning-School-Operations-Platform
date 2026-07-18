# Keeping the app awake (no "Render loading page")

## The problem

Render's **free** plan spins a web service down after ~15 minutes with no inbound
traffic. The next visitor triggers a cold start and sits on Render's loading screen for
roughly 30-60 seconds.

## Why the GitHub Action is not enough

`.github/workflows/keep-alive.yml` pings the service on a schedule, but **GitHub does
not guarantee cron timing**. Scheduled workflows are deprioritised under load and are
commonly delayed 15-60 minutes, or skipped. Render sleeps at 15 minutes, so a late run
arrives after the service is already asleep.

Measured on this repo: workflow pushed at **12:13**, still **zero runs** 53 minutes
later, despite a 10-minute schedule.

Treat the workflow as a backup only.

---

## The fix: an external uptime pinger (2 minutes, free)

Use a dedicated pinger with a 1-5 minute interval. Recommended: **cron-job.org** (free,
down to 1-minute intervals, reliable timing).

### cron-job.org

1. Sign up at <https://cron-job.org> (free).
2. **Create cronjob**.
3. Title: `Avinashi GGHSS keep-alive`
4. URL:
   ```
   https://avinashi-gghss.onrender.com/health
   ```
5. Schedule: **every 5 minutes** (comfortably under Render's ~15 min cutoff).
6. Save. Enable notifications on failure so you learn if the app goes down.

### UptimeRobot (alternative)

1. Sign up at <https://uptimerobot.com> (free: 50 monitors, 5-minute interval).
2. **Add New Monitor** → type **HTTP(s)**.
3. URL: `https://avinashi-gghss.onrender.com/health`, interval **5 minutes**.

You get uptime monitoring and alerting as a bonus - useful once real schools depend on
this.

---

## Why `/health` and not the homepage

`/health` is deliberately dependency-free (it does **not** touch the database), so the
ping is cheap and cannot fail during a brief database hiccup.

There is also `/health/ready`, which *does* check the database and returns **503** when
it is unreachable. Point a **separate** monitor at `/health/ready` if you want to be
alerted when the database is down - but keep the *keep-alive* pinger on `/health`, or a
database blip would look like an outage and spam you.

---

## Honest limits of this workaround

- **Free-plan hours:** the free plan includes 750 instance-hours/month; a month is ~730
  hours. Keeping **one** service awake fits, but leaves almost no headroom for a second
  free service on the same account.
- **The free database expires.** Render free Postgres now expires **30 days** after
  creation (plus a 14-day grace period), then it is **deleted with all data**. Keeping
  the web service awake does nothing about this - migrate the database (e.g. to Neon,
  whose free tier is permanent).
- **No SLA.** Fine for a pilot. Once a school depends on this daily, the real fix is
  Render's paid **Starter** plan (~$7/month), which never sleeps. Then delete the
  workflow and the pinger.
