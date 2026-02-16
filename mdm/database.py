from sqlalchemy import create_engine
from sqlalchemy import inspect, text
from sqlalchemy.orm import sessionmaker
from mdm.models import Base

DATABASE_URL = "sqlite:///./mdm/data/powerflex.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    Base.metadata.create_all(bind=engine)

    inspector = inspect(engine)

    if "sds_nodes" in inspector.get_table_names():
        sds_cols = {col["name"] for col in inspector.get_columns("sds_nodes")}
        if "cluster_node_id" not in sds_cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE sds_nodes ADD COLUMN cluster_node_id VARCHAR"))

    if "sdc_clients" in inspector.get_table_names():
        sdc_cols = {col["name"] for col in inspector.get_columns("sdc_clients")}
        if "cluster_node_id" not in sdc_cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE sdc_clients ADD COLUMN cluster_node_id VARCHAR"))

    if "chunks" in inspector.get_table_names():
        chunk_cols = {col["name"] for col in inspector.get_columns("chunks")}
        with engine.begin() as conn:
            if "generation" not in chunk_cols:
                conn.execute(text("ALTER TABLE chunks ADD COLUMN generation INTEGER DEFAULT 0"))
            if "checksum" not in chunk_cols:
                conn.execute(text("ALTER TABLE chunks ADD COLUMN checksum VARCHAR"))
            if "last_write_offset_bytes" not in chunk_cols:
                conn.execute(text("ALTER TABLE chunks ADD COLUMN last_write_offset_bytes INTEGER"))
            if "last_write_length_bytes" not in chunk_cols:
                conn.execute(text("ALTER TABLE chunks ADD COLUMN last_write_length_bytes INTEGER"))
            if "last_write_at" not in chunk_cols:
                conn.execute(text("ALTER TABLE chunks ADD COLUMN last_write_at DATETIME"))

    if "cluster_nodes" in inspector.get_table_names():
        cluster_cols = {col["name"] for col in inspector.get_columns("cluster_nodes")}
        with engine.begin() as conn:
            if "control_port" not in cluster_cols:
                conn.execute(text("ALTER TABLE cluster_nodes ADD COLUMN control_port INTEGER"))
            if "data_port" not in cluster_cols:
                conn.execute(text("ALTER TABLE cluster_nodes ADD COLUMN data_port INTEGER"))
            conn.execute(text("UPDATE cluster_nodes SET control_port = port WHERE control_port IS NULL"))
    # Phase 2: Discovery & Registration — seed cluster_secret if not exists
    if "cluster_config" in inspector.get_table_names():
        with engine.begin() as conn:
            result = conn.execute(text("SELECT COUNT(*) FROM cluster_config WHERE key = 'cluster_secret'"))
            if result.scalar() == 0:
                import secrets
                cluster_secret = secrets.token_hex(32)  # 64 hex chars = 32 bytes
                conn.execute(text(
                    "INSERT INTO cluster_config (key, value, description) VALUES (:k, :v, :d)"
                ), {"k": "cluster_secret", "v": cluster_secret, "d": "Shared secret for component authentication"})
            
            result = conn.execute(text("SELECT COUNT(*) FROM cluster_config WHERE key = 'cluster_name'"))
            if result.scalar() == 0:
                conn.execute(text(
                    "INSERT INTO cluster_config (key, value, description) VALUES (:k, :v, :d)"
                ), {"k": "cluster_name", "v": "powerflex_cluster_default", "d": "Cluster display name"})