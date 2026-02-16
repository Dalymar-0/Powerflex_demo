from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from mdm.config import DATA_PLANE_BASE_PORT, MDM_API_PORT, SDC_SERVICE_PORT, GUI_PORT


@dataclass
class StartupProfile:
    role: str
    host: str
    port: int


def _require_valid_port(port: int, field_name: str = "port") -> None:
    if int(port) < 1 or int(port) > 65535:
        raise ValueError(f"{field_name} must be in range 1..65535")


def _require_non_empty_host(host: str) -> None:
    if not str(host or "").strip():
        raise ValueError("host is required")


def validate_mdm_profile(profile: StartupProfile) -> None:
    _require_non_empty_host(profile.host)
    _require_valid_port(profile.port)
    if int(profile.port) == int(DATA_PLANE_BASE_PORT):
        raise ValueError(
            f"MDM control-plane port {profile.port} conflicts with SDS data-plane base port {DATA_PLANE_BASE_PORT}"
        )


def validate_sds_profile(profile: StartupProfile, storage_root: str) -> None:
    _require_non_empty_host(profile.host)
    _require_valid_port(profile.port)
    if int(profile.port) == int(MDM_API_PORT):
        raise ValueError(f"SDS data-plane port {profile.port} conflicts with MDM API port {MDM_API_PORT}")
    if int(profile.port) == int(SDC_SERVICE_PORT):
        raise ValueError(f"SDS data-plane port {profile.port} conflicts with SDC service port {SDC_SERVICE_PORT}")
    if not str(storage_root or "").strip():
        raise ValueError("storage_root is required for SDS service")


def validate_sdc_profile(profile: StartupProfile, control_plane_url: str) -> None:
    _require_non_empty_host(profile.host)
    _require_valid_port(profile.port)
    if int(profile.port) == int(MDM_API_PORT):
        raise ValueError(f"SDC service port {profile.port} conflicts with MDM API port {MDM_API_PORT}")
    if int(profile.port) == int(DATA_PLANE_BASE_PORT):
        raise ValueError(f"SDC service port {profile.port} conflicts with SDS data-plane base port {DATA_PLANE_BASE_PORT}")

    parsed = urlparse(str(control_plane_url or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("control_plane_url must be a valid http(s) URL")


def validate_gui_profile(profile: StartupProfile, mdm_base_url: str) -> None:
    _require_non_empty_host(profile.host)
    _require_valid_port(profile.port)
    if int(profile.port) == int(MDM_API_PORT):
        raise ValueError(f"GUI port {profile.port} conflicts with MDM API port {MDM_API_PORT}")

    parsed = urlparse(str(mdm_base_url or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("mdm_base_url must be a valid http(s) URL")
