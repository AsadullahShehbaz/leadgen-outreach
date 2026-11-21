from fastapi import FastAPI
from app.routers.auth import router as auth_router
from app.routers.setup import router as setup_router
from app.routers.system import router as system_router

app = FastAPI(title="LeadGen Agent")
app.include_router(auth_router)
app.include_router(setup_router)
app.include_router(system_router)


@app.get("/health")
async def health():
    # Basic liveness check. Docker and update.sh use this.
    return {"status": "ok"}
