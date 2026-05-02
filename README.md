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
