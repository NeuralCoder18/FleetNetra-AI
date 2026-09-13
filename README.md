# FleetNetra AI — Role-Based Urban Intelligence Prototype

This version adds role-based access for **Traffic Authority, Traffic Inspector, and Citizen** while keeping the bus/edge AI as a machine-to-machine source rather than a human dashboard user.

## Demo accounts
- Authority: `authority` / `authority123`
- Inspector: `inspector` / `inspector123`
- Citizen: `citizen` / `citizen123`

## Run backend
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
python seed_demo.py
python -m uvicorn main:app --reload --port 8000
```

## Run frontend
In another terminal:
```bash
npm install
npm run dev
```

## Role model
- **Authority:** full GIS, fleet intelligence, clustered AI road cases, heatmaps, road priority, assignments, community signals and Gemini reports.
- **Inspector:** assigned GIS/workbench and field verification only.
- **Citizen:** public reporting, own report tracking and safer-route utility.
- **Bus/Edge AI:** no human login; telemetry uses a device API key endpoint.

The prototype uses signed demo session tokens and backend authorization checks. Replace demo credentials and `AUTH_SECRET` before any real deployment.

## Prototype demo flow

- Authority: `authority / authority123`
- Inspector: `inspector / inspector123`
- Citizen: `citizen / citizen123`
- Bus Edge AI Console: open `/bus-demo` (device-authenticated prototype simulator; no human login)

The bus console sends live prototype GPS telemetry with an `X-Device-Key` and sends pothole inference events through `/api/edge/detect`. Authority users consume those stored observations as clustered road cases; authority users do not run the onboard detector.
