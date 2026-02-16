"""
MDM Service Entrypoint - Phase 7 Update

FastAPI application for the MDM (Metadata Manager) component.
Includes all API routers, health monitoring, and startup initialization.
"""
import warnings
warnings.filterwarnings('ignore', category=DeprecationWarning, module='sqlalchemy')

from fastapi import FastAPI
import os
import logging

from mdm.api import pd, pool, sds, sdc, volume, metrics, rebuild, cluster, discovery, token, health
from mdm.database import init_db, SessionLocal
from mdm.startup_profile import StartupProfile, validate_mdm_profile
from mdm.health_monitor import HealthMonitor

logger = logging.getLogger(__name__)

app = FastAPI(title="PowerFlex MDM Service")

# Include all API routers
app.include_router(pd.router)
app.include_router(pool.router)
app.include_router(sds.router)
app.include_router(sdc.router)
app.include_router(volume.router)
app.include_router(metrics.router)
app.include_router(rebuild.router)
app.include_router(cluster.router)
app.include_router(discovery.router)  # Phase 2: Discovery & Registration
app.include_router(token.router)  # Phase 4: IO Authorization Tokens
app.include_router(health.router)  # Phase 7: Health Monitoring

# Global health monitor instance
health_monitor = None


@app.on_event("startup")
def startup_init():
    """Initialize database and start health monitor"""
    global health_monitor
    
    startup_port = int(os.getenv("POWERFLEX_MDM_API_PORT", "8001"))
    startup_host = str(os.getenv("POWERFLEX_MDM_BIND_HOST", "0.0.0.0"))
    validate_mdm_profile(StartupProfile(role="MDM", host=startup_host, port=startup_port))
    
    # Initialize database
    init_db()
    
    # Start health monitor (Phase 7)
    logger.info("Starting health monitor...")
    health_monitor = HealthMonitor(
        session_factory=SessionLocal,
        check_interval_seconds=10,
        heartbeat_timeout_seconds=30
    )
    health_monitor.start()
    
    # Inject health monitor into health API
    health.set_health_monitor(health_monitor)
    
    logger.info("MDM service startup complete")


@app.on_event("shutdown")
def shutdown_cleanup():
    """Stop health monitor on shutdown"""
    global health_monitor
    
    if health_monitor:
        logger.info("Stopping health monitor...")
        health_monitor.stop()
    
    logger.info("MDM service shutdown complete")


@app.get("/")
def root():
    return {
        "service": "mdm",
        "message": "PowerFlex MDM control-plane service running (restructured)",
    }
