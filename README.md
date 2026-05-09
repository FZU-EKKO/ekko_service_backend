ekko backend

1. create `.env` from `.env.example`

2. install dependencies

```bash
pip install -r requirements.txt
```

3. start the server

```bash
uvicorn main:ekko --host 0.0.0.0 --port 8000 --reload
```

Judge service wiring:

- `ekko/.env` -> `EKKO_ANALYSIS_REMOTE_URL` should point to `ekko_judge_service`'s `POST /analyze`, for example `http://127.0.0.1:19002/analyze`
- `ekko/.env` -> `EKKO_ANALYSIS_REMOTE_TOKEN` must match `ekko_judge_service/.env` -> `EKKO_JUDGE_SERVICE_TOKEN`
