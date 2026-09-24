# Body Tester - Cosmos Innovation

A touch-screen kiosk application for health self-checks. A React frontend
drives the screen and sensors (via the local backend); a Python/FastAPI
backend talks to the sensors, does on-device face recognition, and
syncs patients/measurements with the Bodytester clinic cloud API.

```
┌─────────────────┐  HTTP (localhost:8000)  ┌──────────────────────┐  HTTPS   ┌────────────────────────────┐
│  React frontend  │ ───────────────────────▶│  Python/FastAPI      │ ───────▶ │ Bodytester clinic backend  │
│  (kiosk screen)  │◀─────────────────────── │  backend (this repo) │◀──────── │ bodytester-microservice.uz │
└─────────────────┘                          └──────────┬───────────┘          └────────────────────────────┘
                                                          │ serial / I2C / GPIO
                                                          ▼
                                              height, weight, BP, SpO2,
                                              temperature sensors + camera
```

## 🌟 Features

### User Registration
- **Camera integration**: face capture via webcam, on-device detection (`face-api.js`)
- **Buttonless kiosk recognition**: camera continuously scans; a known patient is
  identified automatically (local cache first, clinic server as fallback) and
  asked to confirm ("Bu sizmisiz?") before continuing
- **Name input**: for new patients
- **Guest mode**: skip registration, no data sent to the clinic backend

### Health Measurements
- **Birth date input**: calendar (ISO 8601) — age is never sent to the clinic
  server, it is computed there from the birth date
- **Gender selection**
- **Temperature, weight/height, blood oxygen (SpO2), blood pressure & pulse**

### Advanced Features
- **Select All mode**: run every measurement type sequentially in one pass
- **Offline-safe submission**: measurements are queued on disk and retried
  automatically if the clinic backend is unreachable
- **Responsive, kiosk-oriented UI**

## 📁 Project Structure

```
Body_tester/
├── public/                       # static assets, face-api.js models
├── src/                          # React frontend
│   ├── components/               # Button, etc.
│   ├── layout/                   # Header, MainLayout
│   ├── pages/
│   │   ├── Registration.jsx      # camera capture, buttonless identify, "Bu sizmisiz?" confirm
│   │   ├── Home.jsx
│   │   ├── AgeInput.jsx          # birth-date calendar (route: /age-input)
│   │   ├── Selection.jsx         # choose measurement(s) / "select all"
│   │   ├── GenderSelection.jsx   # gender + triggers /face/enroll for new patients
│   │   ├── TemperatureMeasurement.jsx
│   │   ├── WeightHeightMeasurement.jsx
│   │   ├── OxygenMeasurement.jsx
│   │   ├── BloodPressureMeasurement.jsx
│   │   └── Success.jsx           # summary + triggers /submit
│   ├── styles/                   # SCSS (base/layout/pages)
│   └── App.jsx                   # routes
└── backend/                       # Python/FastAPI kiosk backend (runs on the device)
    ├── server.py                  # FastAPI app: sensors + /face/*, /submit, /queue
    ├── bodytester_api.py          # HTTP client for the clinic API, measurement queue
    ├── face_recognition.py        # InsightFace (buffalo_l) embedding extraction
    ├── face_cache.py               # local SQLite face cache + sync with clinic API
    ├── hx711_weight_sensor.py, *_sensor_test.py  # sensor drivers/scripts
    ├── requirements.txt
    └── .env                       # BODYTESTER_SERIAL / BODYTESTER_SECRET (not committed)
```

The frontend talks **only** to the local backend at `http://localhost:8000`.
The local backend is the only thing that talks to the clinic cloud API — the
frontend never sees the clinic's URL, token, or device secret.

## 🔌 Backend ↔ Clinic API integration

Base URL: `https://bodytester-microservice.bodytester.uz/api` (kiosk API
contract; see `backend/bodytester_api.py` header comments for section
references). Configured via `backend/.env`:

```
BODYTESTER_SERIAL=<device serial number>
BODYTESTER_SECRET=<device secret, dsk_...>
BODYTESTER_API_URL=<optional override>
```

If unset, sensors still work but `/submit` and `/face/*` return `503`.

### Endpoints used

| Method | Path | Purpose |
|---|---|---|
| POST | `/clinic/devices/token/` | Exchange serial+secret for a bearer token (~30 min TTL, refreshed automatically) |
| POST | `/clinic/patients/identify/` | Server-side face match (fallback when the local cache misses) |
| POST | `/clinic/patients/` | Enroll a new patient (embedding + `birth_date`, **not** age) |
| POST | `/clinic/patients/measurement/` | Submit one measurement (idempotent via `client_measurement_id`) |
| GET | `/clinic/faces/sync/` | Paginated sync of the clinic's face vectors + names into the local cache |
| GET | `/clinic/faces/ids/` | Reconciliation check (total count mismatch) |

### Face recognition & local cache

- `face_recognition.py` computes a 512-d ArcFace embedding (InsightFace
  `buffalo_l`) from a captured frame; low-quality/low-score frames are dropped.
- `face_cache.py` keeps a local SQLite mirror of the clinic's face vectors
  **and names** (`first_name`/`last_name` from the sync response), so a
  returning patient is recognized instantly, offline, with their name shown
  on the "Bu sizmisiz?" confirmation — no server round-trip needed.
- The cache resyncs on every new token and once an hour in the background.
- If the on-device match is rejected ("Yo'q, men emasman"), the kiosk treats
  the person as a **new** patient and calls `/face/enroll` with the same
  embedding; the clinic server itself detects real duplicates
  (`possible_duplicate_of`) — the kiosk does not try to resolve this itself.

### Error handling & retry policy

Per the kiosk API contract:

| Situation | Behavior |
|---|---|
| `401` on the token endpoint | device is blocked/invalid — local face cache is wiped |
| `403` on any other endpoint | token refreshed once, request retried once |
| `429` | the `Retry-After` header is read and respected before the next attempt |
| `5xx` / network error | exponential backoff: 30s → 60s → 120s → … capped at 30 min |
| Measurement send failure | queued on disk (`pending_measurements.json`), retried with the same `client_measurement_id` so the server de-dupes |

This applies both to the measurement queue (`bodytester_api.MeasurementQueue`)
and the face-cache sync worker (`face_cache.start_sync_worker`).

## 📱 Application Flow

1. **Registration** (`/`) — camera capture (or guest mode). Known patients are
   recognized automatically and shown a "Bu sizmisiz?" confirmation.
2. **Home** (`/home`)
3. **Birth date** (`/age-input`) — calendar input, skipped for already-known patients
4. **Selection** (`/selection`) — choose measurement(s), or "select all"
5. **Gender selection** (`/gender-selection`) — new patients are enrolled here
   (`/face/enroll`) with the embedding + birth date + gender
6. **Measurement pages** (`/measurement/*`)
7. **Success** (`/success`) — submits the session's measurements (`/submit`)

## 🎨 Technology Stack

**Frontend**: React, React Router DOM, SCSS, React Icons, `face-api.js`
(on-device face detection), Web APIs (`getUserMedia`).

**Backend**: Python 3, FastAPI + Uvicorn, InsightFace/ONNX Runtime (face
recognition), OpenCV, SQLite (face cache), `pyserial`/`smbus2`/`gpiozero`
(sensor I/O), `requests` (clinic API client).

## 🛠️ Development

### Frontend

```bash
npm install
npm start          # dev server on :3000, expects the backend on :8000
npm run build       # production build -> build/
```

### Backend

```bash
cd backend
python3 -m venv ../venv && source ../venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in BODYTESTER_SERIAL / BODYTESTER_SECRET (not committed)
python server.py       # runs on :8000
```

Diagnostics while it's running:
- `GET /face/cache/status` — cache size, sync status, last error
- `GET /face/cache/view` — auto-refreshing HTML view of the cache
- `GET /queue` — pending (unsent) measurements

## 📝 Notes

- Camera permission is required for registration/identification.
- Non-clinic data (session UI state) lives in browser `localStorage`; it is
  cleared on the Success screen. Clinic data (patients, measurements) lives
  only on the clinic server plus the local recognition cache.
- `backend/face_cache.sqlite3`, `backend/.env`, `backend/pending_measurements.json`
  and `backend/server_legacy.py` (old script with a hardcoded secret) are
  intentionally excluded from version control — see `.gitignore`.

## 🗓️ Recent changes

- **Birth date replaces age** end-to-end: the kiosk now collects an ISO 8601
  birth date (calendar input) instead of a free-typed age; the clinic server
  computes age itself and rejects requests that still send `age`.
- **Retry policy fixed** to match the kiosk API contract: `429` responses now
  wait for the server's `Retry-After` header instead of a fixed 30s; `5xx`/
  network failures now back off exponentially (30s → 60s → … → 30 min) instead
  of retrying at a flat interval. Applies to both the measurement queue and
  the face-cache sync worker.
- **Face sync now captures patient names** (`first_name`/`last_name` from
  `/clinic/faces/sync/`), not just embeddings — so patients recognized purely
  from the local cache (no server round-trip) are shown by name on the
  confirmation screen, not just "Bemor #ID".
- **"Yo'q, men emasman" now leads to enrollment**, not just a re-scan: the
  rejected match is treated as a new patient and sent to `/face/enroll` with
  its embedding; the clinic server's own duplicate detection
  (`possible_duplicate_of`) is the safety net, not client-side logic.

## 🤝 Contributing

This is a private project for Cosmos Innovation. For contributions or questions, please contact the project maintainers.

## 📄 License

Private project - All rights reserved.

---

**Developed by Cosmos Innovation**
*"Innovatsion kelajakni biz bilan birga quring"*
