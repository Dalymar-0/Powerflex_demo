import os


def _int_env(name: str, default: int) -> int:
    raw = str(os.getenv(name, str(default))).strip()
    try:
        return int(raw)
    except Exception:
        return default


CONTROL_PLANE_BASE_PORT = _int_env("POWERFLEX_CONTROL_BASE_PORT", 9100)
DATA_PLANE_BASE_PORT = _int_env("POWERFLEX_DATA_BASE_PORT", 9700)
MDM_API_PORT = _int_env("POWERFLEX_MDM_API_PORT", 8001)
SDC_SERVICE_PORT = _int_env("POWERFLEX_SDC_SERVICE_PORT", 8003)
GUI_PORT = _int_env("POWERFLEX_GUI_PORT", 5000)
MDM_BASE_URL = str(os.getenv("POWERFLEX_MDM_BASE_URL", "http://127.0.0.1:8001")).strip()
