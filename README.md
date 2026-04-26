# 🏏 Cricket Scorebook

A mobile-first, ball-by-ball cricket scoring web app built with Flask.

## Features
- ⚡ Direct scoring (no login, data persists until tab/browser closes)
- 🔐 Google login (saves match history for 48 hours)
- 🪙 Coin toss system
- 🏏 Last-man batting support (gali cricket!)
- 📊 Live scorecard with batsmen, bowlers, extras, fall of wickets
- ↩ Undo last ball
- 📄 Detailed PDF scorecard download
- 📱 Fully mobile-optimized (portrait)

## Run Locally

```bash
# 1. Create virtual environment
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run
python app.py
```

Open http://localhost:5000 in your browser (or phone browser on same WiFi).

## Deploy to Render

1. Push to GitHub
2. Create account at render.com
3. New → Web Service → connect your GitHub repo
4. Build command: `pip install -r requirements.txt`
5. Start command: `gunicorn app:app --bind 0.0.0.0:$PORT`
6. Add env var: `SECRET_KEY` = any random string

## Real Google OAuth Setup

1. Go to https://console.cloud.google.com
2. Create project → APIs & Services → Credentials
3. Create OAuth 2.0 Client ID (Web application)
4. Add your domain to Authorized JavaScript origins
5. Copy the Client ID
6. In `templates/index.html`, set `GOOGLE_CLIENT_ID = 'your-id-here'`
7. In `app.py`, replace the mock login with real token verification using `google-auth` library

## Tech Stack
- Backend: Python + Flask + SQLAlchemy
- Database: SQLite (local) / PostgreSQL (production)
- PDF: ReportLab
- Frontend: Vanilla HTML/CSS/JS (no framework)
- Fonts: Playfair Display + DM Sans + JetBrains Mono
