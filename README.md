# Infinity Job Search — Autonomous Multi-Platform Job Intelligence Relay

An intelligent, multi-source job intelligence engine that continuously monitors **X (Twitter)**, **Reddit**, **Hacker News**, **Remote Job Boards (Himalayas, We Work Remotely, Jobicy, Arbeitnow)**, **GitHub Paid Bounties**, **Telegram Job Channels**, and **Discord Boards**, classifies opportunities against your multi-track career taxonomy, scores each role (0–100), and sends rich job alert cards with one-click outreach pitch generation directly to your personal Telegram.

---

## 🎯 Target Career Tracks

1. **💻 Full-Stack / Backend Engineering**
   - *Roles:* Full Stack Engineer, Backend Engineer, Software Engineer, Web Engineer, API Developer.
   - *Stack:* TypeScript, React, Next.js, Node.js, PHP/Laravel, C#/.NET, PostgreSQL, REST APIs, Docker.

2. **🤖 AI & Agentic Systems Engineering**
   - *Roles:* AI Engineer, LLM Engineer, AI Developer, Agentic Engineer, Automation Engineer.
   - *Stack:* Python, FastAPI, LLMs, LangChain, LlamaIndex, Agents, RAG, Supabase, Vector DBs, Playwright.

3. **📊 Business Systems & Workforce Analytics**
   - *Roles:* Business Analyst, Systems Analyst, Workforce Planning Analyst, Data Analyst, Operations Analyst.
   - *Stack:* SQL, Excel, Power BI, Tableau, Process Mapping, Workforce Planning, Erlang, Capacity Modeling, KPIs.

---

## ⚡ Key Features

* **Multi-Source Ingestion:** Ingests live job postings from 7 distinct platforms in parallel.
* **Weighted Composite Scoring (0–100):** Evaluates role title match (35 pts), tech skill density (30 pts), location/timezone compatibility (20 pts), and pay transparency (15 pts).
* **Negative & Seeker Filter:** Disqualifies `[FOR HIRE]` seeker posts, unpaid gigs, and strict clearance/citizenship constraints.
* **Instant Pitch Generator:** Interactive `[📋 Pitch Snippet]` Telegram button generates a customized outreach message ready to paste directly into founder DMs or emails.
* **Interactive Bot Actions:** `[⭐ Save Job]`, `[🔇 Hide Poster (7d)]`, `[🌐 Open & Apply]`.
* **Zero-Cost Public APIs & Feeds:** Ingests Himalayas, HN Algolia, and Remote RSS feeds with no API subscriptions.

---

## 🚀 Quick Start

### 1. Install Dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

### 2. Configure Environment

Copy `.env.example` to `.env` and configure your Telegram bot credentials:

```bash
cp .env.example .env
```

Key configuration values:
```env
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
ADMIN_CHAT_ID=your_telegram_user_id
MIN_ALERT_SCORE=70
```

### 3. Run the Bot

```bash
python main.py
```

---

## 🧪 Testing

Run the full pytest suite:

```bash
pytest tests/ -v
```
