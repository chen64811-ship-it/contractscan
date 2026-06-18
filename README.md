# ContractScan — AI Contract Risk Analyzer

Scan contracts in seconds. Upload a PDF, Word doc, image, or paste text — ContractScan uses AI to flag risky clauses, detect missing provisions, and give you an actionable risk score.

Built with **FastAPI** + **DeepSeek LLM**. Dark UI. No signup required.

---

## Features

| Feature | Description |
|---------|-------------|
| 📄 Multi-format upload | PDF, Word (.docx), Excel, PNG/JPG — drag & drop |
| 📝 Paste text | Copy-paste contract text, analyze instantly |
| 🔍 Risk detection | LLM scans for liability traps, unfair terms, ambiguous language |
| ⚠️ Missing provisions | Flags what should be in the contract but isn't |
| 📊 Risk score | Overall score + per-clause breakdown |
| 🖼️ OCR (scanned PDFs) | PaddleOCR extracts text from image-based documents |
| 🐳 Docker deploy | One-command deploy via `docker-compose up` |
| 🎨 Dark UI | Clean, modern, responsive — ready for commercial use |

## Quick Start

### Option 1: Run locally

```bash
# Clone
git clone https://github.com/chen64811-ship-it/contractscan.git
cd contractscan

# Install backend dependencies
py -V:3.11 -m pip install -r backend/requirements.txt

# Set up config (copy and edit)
cp .env.example backend/.env
# Edit backend/.env → add your DeepSeek API key

# Start server
cd backend
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

Open http://localhost:8000 in your browser.

### Option 2: Docker

```bash
# Set up your API key first
cp .env.example backend/.env
# Edit backend/.env → add your DeepSeek API key

# Launch
docker-compose up -d
```

Notes:
- The compose file now includes a MySQL service (`mysql`) used by the backend.
- The container will attempt to run Alembic migrations on startup. To run migrations manually:

```bash
# Run migrations (when database is ready)
docker-compose run --rm contractscan sh -c "alembic -c backend/alembic.ini upgrade head"
```

If you prefer to customize DB credentials, edit `backend/.env` (the `DATABASE_URL` setting) before starting.

Backup & Restore
-----------------

Create a backup (requires Docker running):

```bash
./backend/scripts/backup_mysql.sh
```

Restore from backup:

```bash
./backend/scripts/restore_mysql.sh backups/contractscan_YYYYmmddHHMMSS.sql.gz
```

CI Migrations
-------------

The repository includes a GitHub Actions workflow `.github/workflows/ci-migrations.yml` which runs Alembic migrations against a test MySQL service to ensure migrations apply cleanly.

Local demo
----------

Start everything and wait for the service health:

```bash
./backend/scripts/local_demo.sh
```

This will start `docker-compose`, wait until the backend reports healthy, and print the health endpoint output.

### Option 3: OCR support (GPU)

For scanned/image-based PDFs, install PaddleOCR with GPU:

```bash
py -V:3.11 -m pip install paddlepaddle-gpu==2.6.2 -i https://mirror.baidu.com/pypi/simple
py -V:3.11 -m pip install -r backend/requirements.txt
```

Set `OCR_USE_GPU=true` in your `.env`.

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Web UI |
| `POST` | `/api/analyze` | Upload file + analyze (multipart: `file`) |
| `POST` | `/api/analyze-text` | Analyze raw text (JSON: `{"text": "..."}`) |
| `POST` | `/api/debug-analyze` | Debug: returns raw LLM response |
| `GET` | `/api/health` | Health check |

Swagger docs: http://localhost:8000/api/docs

## Tech Stack

| Layer | Tech |
|-------|------|
| Backend | **FastAPI** (Python 3.11+) |
| Frontend | Vanilla HTML/CSS/JS — single file, zero deps |
| AI / LLM | **DeepSeek** via OpenAI-compatible SDK |
| PDF parsing | PyMuPDF + pdfminer + PaddleOCR (fallback) |
| OCR | PaddleOCR (CPU/GPU) |
| Container | Docker + docker-compose |

## Pricing

| Plan | Price | What you get |
|------|-------|-------------|
| **Free** | $0 | 10 analyses/month, text up to 5,000 chars, no OCR |
| **Pro** | $29/mo | 200 analyses/month, 50-page PDFs, OCR, priority LLM |
| **Business** | $99/mo | Unlimited analyses, bulk upload, API access, custom clause templates |
| **Enterprise** | Custom | On-premise deploy, custom LLM backend, SLA, SSO |

*Need something in between? Email hello@contractscan.ai for a custom plan.*

## Configuration

All config lives in `backend/.env`:

```env
# Server
HOST=0.0.0.0
PORT=8000

# LLM (Required)
LLM_API_KEY=your_deepseek_api_key
LLM_API_BASE=https://api.deepseek.com
LLM_MODEL=deepseek-chat

# OCR (Optional — for scanned documents)
OCR_USE_GPU=true
OCR_LANG=en
```

## Project Structure

```
contractscan/
├── backend/
│   ├── app.py              # FastAPI entry point
│   ├── routes/             # API route handlers
│   ├── services/           # LLM analyzer, text extractors
│   └── requirements.txt
├── frontend/
│   └── index.html          # Single-page app (HTML/CSS/JS)
├── docker-compose.yml
├── Dockerfile
├── Dockerfile.gpu          # GPU-accelerated variant
├── .env.example
└── LICENSE
```

## FAQ

**Q: What LLM does this use?**
A: DeepSeek by default. You can swap to any OpenAI-compatible API (OpenAI, Groq, etc.) by changing `LLM_API_BASE` and `LLM_MODEL` in `.env`.

**Q: Does it support Chinese contracts?**
A: Yes. The LLM prompt works with both English and Chinese contracts. Set `OCR_LANG=ch` for Chinese OCR.

**Q: How long does analysis take?**
A: Typically 5–15 seconds depending on document length and LLM response time.

**Q: Is my contract data stored?**
A: No. Files are processed in memory and deleted after analysis. Your API key, your data.

## License

MIT © 2025 ContractScan
