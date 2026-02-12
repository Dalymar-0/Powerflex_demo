
from fastapi import FastAPI
from app.api import pd, pool, sds, sdc, volume, metrics, rebuild

app = FastAPI()

app.include_router(pd.router)
app.include_router(pool.router)
app.include_router(sds.router)
app.include_router(sdc.router)
app.include_router(volume.router)
app.include_router(metrics.router)
app.include_router(rebuild.router)

@app.get("/")
def root():
    return {"message": "PowerFlex Simulator API running"}
