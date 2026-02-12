"""
PHASE 4: Background IO Worker
Runs in separate thread to generate workloads and aggregate metrics continuously.
"""

import threading
import time
import logging
from typing import Optional
from sqlalchemy.orm import Session, sessionmaker
from datetime import datetime
from app.services.io_simulator import IOSimulator
from app.models import StoragePool, Volume, SDSNode, SDCClient, EventLog, EventType

logger = logging.getLogger(__name__)


class BackgroundIOWorker:
    """
    Background thread worker that generates IO and updates metrics.
    
    Tasks:
    - Generate random workload every 100ms
    - Aggregate metrics every 5s
    - Log metrics to event log every 60s
    """

    def __init__(self, db_session_factory: sessionmaker, daemon: bool = True):
        """
        Initialize background worker.
        
        Args:
            db_session_factory: SQLAlchemy sessionmaker factory
            daemon: Whether to run as daemon thread
        """
        self.db_session_factory = db_session_factory
        self.daemon = daemon
        self.is_running = False
        self.thread: Optional[threading.Thread] = None
        self.simulator: Optional[IOSimulator] = None

        # Configuration
        self.workload_tick_ms = 100  # Generate IO every 100ms
        self.metrics_aggregation_sec = 5  # Aggregate metrics every 5s
        self.metrics_logging_sec = 60  # Log to EventLog every 60s

    def start(self) -> None:
        """Start the background worker thread."""
        if self.is_running:
            logger.warning("IO worker already running")
            return

        self.is_running = True
        self.thread = threading.Thread(target=self._run, daemon=self.daemon)
        self.thread.start()
        logger.info("Background IO worker started")

    def stop(self) -> None:
        """Stop the background worker thread."""
        if not self.is_running:
            return

        self.is_running = False
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("Background IO worker stopped")

    def _run(self) -> None:
        """Main worker loop - runs in separate thread."""
        db = None  # Initialize to None for finally block safety
        try:
            # Create simulator with fresh session
            db = self.db_session_factory()
            self.simulator = IOSimulator(db)

            # Timing trackers
            next_metrics_agg = time.time() + self.metrics_aggregation_sec
            next_metrics_log = time.time() + self.metrics_logging_sec

            while self.is_running:
                try:
                    # Generate workload tick
                    self._generate_workload(db)

                    # Check if time to aggregate metrics
                    now = time.time()
                    if now >= next_metrics_agg:
                        self._aggregate_metrics(db)
                        next_metrics_agg = now + self.metrics_aggregation_sec

                    # Check if time to log metrics
                    if now >= next_metrics_log:
                        self._log_metrics(db)
                        next_metrics_log = now + self.metrics_logging_sec

                    # Sleep for workload tick interval
                    time.sleep(self.workload_tick_ms / 1000.0)

                except Exception as e:
                    logger.error(f"Error in IO worker loop: {str(e)}", exc_info=True)
                    time.sleep(1)  # Back off on error

        except Exception as e:
            logger.error(f"Fatal error in IO worker: {str(e)}", exc_info=True)
        finally:
            if db:
                db.close()
            self.is_running = False
            logger.info("IO worker thread exiting")

    def _generate_workload(self, db: Session) -> None:
        """Generate random IO workload for this tick."""
        try:
            if self.simulator:
                self.simulator.generate_workload_tick(self.workload_tick_ms)
        except Exception as e:
            logger.error(f"Workload generation error: {str(e)}")

    def _aggregate_metrics(self, db: Session) -> None:
        """Aggregate metrics across pools, volumes, SDS, and SDC."""
        try:
            if not self.simulator:
                return

            # Aggregate pool metrics
            pools = db.query(StoragePool).all()
            for pool in pools:
                pool_id = int(pool.id)  # type: ignore
                metrics = self.simulator.aggregate_pool_metrics(pool_id)
                if metrics:
                    # Update pool current metrics (already done in aggregate_pool_metrics via sql_update)
                    pass

            # Aggregate SDS metrics
            sds_nodes = db.query(SDSNode).all()
            for sds in sds_nodes:
                sds_id = int(sds.id)  # type: ignore
                metrics = self.simulator.aggregate_sds_metrics(sds_id)
                # Already updated in aggregate_sds_metrics

            # Aggregate SDC metrics
            sdcs = db.query(SDCClient).all()
            for sdc in sdcs:
                sdc_id = int(sdc.id)  # type: ignore
                metrics = self.simulator.aggregate_sdc_metrics(sdc_id)
                # Already updated in aggregate_sdc_metrics

            db.commit()

        except Exception as e:
            logger.error(f"Metrics aggregation error: {str(e)}")
            db.rollback()

    def _log_metrics(self, db: Session) -> None:
        """Log current metrics to EventLog for retention."""
        try:
            # Get current pool metrics
            pools = db.query(StoragePool).all()
            for pool in pools:
                if self.simulator:
                    pool_id = int(pool.id)  # type: ignore
                    metrics = self.simulator.aggregate_pool_metrics(pool_id)
                    if metrics and metrics.get("total_iops", 0) > 0:
                        # Log to event log
                        event = EventLog(
                            event_type=EventType.IO_ERROR,  # Reuse as metrics event (TODO: add METRICS event type)
                            message=f"Pool metrics: {metrics['total_iops']:.0f} IOPS, "
                            f"{metrics['total_bandwidth_mbps']:.2f} MB/s, "
                            f"{metrics['average_latency_ms']:.1f}ms latency",
                            pool_id=pool_id,
                        )
                        db.add(event)

            db.commit()

        except Exception as e:
            logger.error(f"Metrics logging error: {str(e)}")
            db.rollback()


# Global worker instance
_io_worker: Optional[BackgroundIOWorker] = None


def init_io_worker(db_session_factory: sessionmaker) -> BackgroundIOWorker:
    """
    Initialize and start the background IO worker.
    
    Args:
        db_session_factory: SQLAlchemy sessionmaker
        
    Returns:
        BackgroundIOWorker instance
    """
    global _io_worker
    if _io_worker is None:
        _io_worker = BackgroundIOWorker(db_session_factory)
        _io_worker.start()
    return _io_worker


def stop_io_worker() -> None:
    """Stop the background IO worker."""
    global _io_worker
    if _io_worker:
        _io_worker.stop()
        _io_worker = None


def get_io_worker() -> Optional[BackgroundIOWorker]:
    """Get the current IO worker instance."""
    return _io_worker
