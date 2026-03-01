# Option C: Build Flask performance dashboard (system health + accuracy UI)

**Label:** enhancement
**Priority:** Low (Option B Streamlit Cloud dashboard is the recommended short-term path)

---

## Context

From the Feb 28 2026 session — we evaluated 4 options for mobile monitoring of picks,
system health, and model performance. Option C is a polished, fully-custom Flask dashboard.

**Current state:** `dashboards/performance_dashboard.py` exists but is an incomplete stub.
It imports Flask and defines routes but `dashboards/templates/index.html` was never created,
so every route returns a `jinja2.exceptions.TemplateNotFound: index.html` 500 error.

The Streamlit cloud dashboard (`dashboards/cloud_dashboard.py`) was built Feb 28 and covers
the same ground for now. Option C becomes worthwhile when we want a more polished,
public-facing monitoring page.

---

## What this needs

### 1. HTML templates (`dashboards/templates/`)
- `index.html` — main dashboard layout
- `_partials/` — reusable components (nav, stat cards, chart containers)

### 2. Dashboard sections
- **System status** — DB health, last prediction date + count per sport, API uptime
- **Today's picks** — filterable table (sport, tier, prop, direction)
- **Pipeline history** — last 7 days run log, success/failure, prediction counts
- **Accuracy charts** — overall, by tier, by prop type (Chart.js line + bar charts)
- **ML model performance** — accuracy trend over time per sport

### 3. Backend updates
- Connect routes to Supabase instead of local SQLite
- Set `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` env vars in host

### 4. Deployment
- Deploy to Railway, Render, or fly.io (all have free tiers)
- CI/CD from `master` branch on push
- Mobile-responsive CSS (Bootstrap or Tailwind)

---

## Why do this vs the Streamlit cloud dashboard?

| | Flask (Option C) | Streamlit Cloud (Option B — done) |
|---|---|---|
| Customization | Full HTML/CSS/JS control | Limited to Streamlit components |
| Charts | Chart.js, D3, anything | Streamlit native (decent but limited) |
| Mobile UX | Can be pixel-perfect | Good but opinionated |
| Build effort | Half day+ | Already done |
| Deployment | Railway/Render | Streamlit Community Cloud |
| Public-facing | Yes | Awkward (Streamlit branding) |

---

## Relevant files

- `dashboards/performance_dashboard.py` — Flask stub (routes exist, no templates)
- `dashboards/cloud_dashboard.py` — Streamlit cloud version (complete, Supabase-backed)
- `dashboards/smart_picks_app.py` — Local Streamlit app (SQLite-backed, working locally)
- `docs/sessions/2026-02-28.md` — Session notes with full option comparison
