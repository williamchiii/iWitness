from fastapi import FastAPI

app = FastAPI()

@app.post("/health")
def health():
    return {"server": "healthy"}