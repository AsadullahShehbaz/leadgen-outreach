from fastapi import FastAPI

app = FastAPI(title="LeadGen Agent")


@app.get("/health")
async def health():
    # Basic liveness check. Docker and update.sh use this.
    return {"status": "ok"}
