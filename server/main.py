from fastapi import FastAPI

import db

app = FastAPI()

@app.post("/health")
def health():
    with db.connect() as conn:
        conn.execute("select 1")
    return {"server": "healthy", "database": "healthy"}
