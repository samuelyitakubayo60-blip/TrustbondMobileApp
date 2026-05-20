---
title: Trustbond Backend
emoji: 📉
colorFrom: indigo
colorTo: pink
sdk: docker
app_port: 7860
pinned: false
---

# TrustBond Backend — Hugging Face Space

FastAPI backend for the TrustBond police safety platform (Musanze District, Rwanda).

## Required Space Secrets

Set these in **Settings → Variables and secrets** of this HF Space before deploying:

| Secret name | Description | Required |
|---|---|---|
| `DATABASE_URL` | PostgreSQL+PostGIS connection string: `postgresql://user:pass@host:5432/trustbond` | **Yes** |
| `SECRET_KEY` | JWT signing key (generate with `openssl rand -hex 32`) | **Yes** |
| `GROQ_API_KEY` | Free LLM key for hotspot recommendations — get at https://console.groq.com | Recommended |
| `GEMINI_API_KEY` | Fallback LLM key — get at https://aistudio.google.com | Optional |
| `CLOUDINARY_CLOUD_NAME` | Cloudinary cloud name for evidence file storage | Optional |
| `CLOUDINARY_API_KEY` | Cloudinary API key | Optional |
| `CLOUDINARY_API_SECRET` | Cloudinary API secret | Optional |
| `BREVO_API_KEY` | Brevo transactional email for sending police user credentials | Optional |
| `BREVO_SENDER_EMAIL` | Verified sender email address in Brevo | Optional |
| `FRONTEND_URL` | URL of the police dashboard (for email login links) | Optional |
| `CORS_ORIGINS` | Comma-separated allowed origins e.g. `https://your-dashboard.com` | Optional |

## Features

- DBSCAN hotspot clustering with scikit-learn (haversine distance, trust-score weighting)
- LLM-generated patrol recommendations via Groq (Llama 3.3 70B) → Gemini fallback → template fallback
- Real-time WebSocket notifications
- Evidence file uploads (Cloudinary)
- Police user management with JWT auth
- Geographic intelligence endpoints

## Local Development

```bash
docker compose up --build
```

Backend runs at `http://localhost:8000`, frontend at `http://localhost:80`.
