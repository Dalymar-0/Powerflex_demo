from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
import requests
import json
import os
import atexit

from mgmt.monitor import ComponentMonitor, get_cached_data, get_all_cached_keys
from mgmt.alerts import (
    get_active_alerts,
    get_recent_alerts,
    get_alert_counts,
    acknowledge_alert,
    resolve_alert,
    format_alert_for_display,
    get_alert_history_summary,
)

app = Flask(__name__)
app.secret_key = 'powerflex-demo-secret'
BASE_URL = str(os.getenv("POWERFLEX_MDM_BASE_URL", "http://127.0.0.1:8001")).strip()

# Initialize component monitor (starts background thread)
component_monitor = ComponentMonitor(mdm_base_url=BASE_URL, poll_interval=10, cache_ttl=30)
component_monitor.start()

# Register cleanup on shutdown
def shutdown_monitor():
    component_monitor.stop()

atexit.register(shutdown_monitor)


def call_api(method: str, path: str, **kwargs):
    resp = requests.request(method, f"{BASE_URL}{path}", timeout=10, **kwargs)
    try:
        payload = resp.json()
    except Exception:
        payload = {"raw": resp.text}

    if 200 <= resp.status_code < 300:
        return True, payload, None

    if isinstance(payload, dict):
        error = payload.get("detail") or payload.get("error") or payload.get("raw")
    else:
        error = str(payload)
    return False, payload, f"HTTP {resp.status_code}: {error}"


def get_active_cluster_nodes_with_capability(capability: str):
    ok, payload, _ = call_api("GET", "/cluster/nodes")
    if not ok:
        return []
    nodes = payload.get("nodes", []) if isinstance(payload, dict) else []
    cap = capability.upper()
    return [
        node for node in nodes
        if isinstance(node, dict) and node.get("status") == "ACTIVE" and cap in [c.upper() for c in node.get("capabilities", [])]
    ]


def get_discovered_components_by_type(component_type: str):
    ok, payload, _ = call_api("GET", "/discovery/topology")
    if not ok:
        return []
    components = payload.get("components", []) if isinstance(payload, dict) else []
    wanted = component_type.upper()
    return [
        comp for comp in components
        if isinstance(comp, dict) and str(comp.get("component_type", "")).upper() == wanted
    ]

@app.route('/')
def index():
    return render_template('dashboard.html')

# Protection Domain Routes
@app.route('/pd')
def pd_list():
    try:
        pds = requests.get(f"{BASE_URL}/pd/list").json()
        return render_template('pd_list.html', pds=pds)
    except Exception as e:
        flash(f"Error fetching PDs: {e}", "danger")
        return render_template('pd_list.html', pds=[])

@app.route('/pd/create', methods=['POST'])
def pd_create():
    try:
        name = request.form.get('name')
        ok, payload, error = call_api("POST", "/pd/create", json={"name": name})
        if ok:
            flash(f"PD created: {payload}", "success")
        else:
            flash(f"Error creating PD: {error}", "danger")
    except Exception as e:
        flash(f"Error creating PD: {e}", "danger")
    return redirect(url_for('pd_list'))

@app.route('/pd/<int:pd_id>/delete', methods=['POST'])
def pd_delete(pd_id):
    try:
        ok, _, error = call_api("DELETE", f"/pd/{pd_id}")
        if ok:
            flash("PD deleted", "success")
        else:
            flash(f"Error deleting PD: {error}", "danger")
    except Exception as e:
        flash(f"Error deleting PD: {e}", "danger")
    return redirect(url_for('pd_list'))

# Storage Pool Routes
@app.route('/pool')
def pool_list():
    try:
        pools = requests.get(f"{BASE_URL}/pool/list").json()
        pds = requests.get(f"{BASE_URL}/pd/list").json()
        return render_template('pool_list.html', pools=pools, pds=pds)
    except Exception as e:
        flash(f"Error fetching pools: {e}", "danger")
        return render_template('pool_list.html', pools=[], pds=[])

@app.route('/pool/create', methods=['POST'])
def pool_create():
    try:
        name = request.form.get('name')
        pd_id = request.form.get('pd_id')
        protection_policy = request.form.get('protection_policy')
        total_capacity = request.form.get('total_capacity')
        if not all([name, pd_id, protection_policy, total_capacity]):
            flash("All fields required", "danger")
            return redirect(url_for('pool_list'))
        ok, payload, error = call_api("POST", "/pool/create", json={
            "name": name,
            "pd_id": int(pd_id) if pd_id else 0,
            "protection_policy": protection_policy,
            "total_capacity_gb": float(total_capacity) if total_capacity else 0.0
        })
        if ok:
            flash(f"Pool created: {payload}", "success")
        else:
            flash(f"Error creating pool: {error}", "danger")
    except Exception as e:
        flash(f"Error creating pool: {e}", "danger")
    return redirect(url_for('pool_list'))

@app.route('/pool/<int:pool_id>/health')
def pool_health(pool_id):
    try:
        health = requests.get(f"{BASE_URL}/pool/{pool_id}/health").json()
        return jsonify(health)
    except Exception as e:
        return jsonify({"error": str(e)})

# SDS Node Routes
@app.route('/sds')
def sds_list():
    try:
        sds_nodes = requests.get(f"{BASE_URL}/sds/list").json()
        pds = requests.get(f"{BASE_URL}/pd/list").json()
        sds_capable_nodes = get_active_cluster_nodes_with_capability("SDS")
        discovered_sds_nodes = get_discovered_components_by_type("SDS")
        if isinstance(sds_nodes, list) and len(sds_nodes) == 0 and len(discovered_sds_nodes) > 0:
            flash(
                "SDS services are discovered by MDM, but SDS entities are not yet registered. "
                "Add SDS entries here to manage them in this page.",
                "warning"
            )
        return render_template(
            'sds_list.html',
            sds_nodes=sds_nodes,
            pds=pds,
            sds_capable_nodes=sds_capable_nodes,
            discovered_sds_nodes=discovered_sds_nodes,
        )
    except Exception as e:
        flash(f"Error fetching SDS nodes: {e}", "danger")
        return render_template('sds_list.html', sds_nodes=[], pds=[], sds_capable_nodes=[], discovered_sds_nodes=[])

@app.route('/sds/add', methods=['POST'])
def sds_add():
    try:
        name = request.form.get('name')
        total_capacity = request.form.get('total_capacity_gb')
        devices = request.form.get('devices')
        pd_id = request.form.get('pd_id')
        cluster_node_id = request.form.get('cluster_node_id')
        if not all([name, total_capacity, devices, pd_id, cluster_node_id]):
            flash("All fields required", "danger")
            return redirect(url_for('sds_list'))
        ok, payload, error = call_api("POST", "/sds/add", json={
            "name": name,
            "total_capacity_gb": float(total_capacity) if total_capacity else 0.0,
            "devices": devices,
            "protection_domain_id": int(pd_id) if pd_id else 0,
            "cluster_node_id": cluster_node_id,
        })
        if ok:
            flash(f"SDS node added: {payload}", "success")
        else:
            flash(f"Error adding SDS: {error}", "danger")
    except Exception as e:
        flash(f"Error adding SDS: {e}", "danger")
    return redirect(url_for('sds_list'))

@app.route('/sds/<int:sds_id>/fail', methods=['POST'])
def sds_fail(sds_id):
    try:
        ok, _, error = call_api("POST", f"/sds/{sds_id}/fail")
        if ok:
            flash(f"SDS {sds_id} marked as DOWN", "warning")
        else:
            flash(f"Error: {error}", "danger")
    except Exception as e:
        flash(f"Error: {e}", "danger")
    return redirect(url_for('sds_list'))

@app.route('/sds/<int:sds_id>/recover', methods=['POST'])
def sds_recover(sds_id):
    try:
        ok, _, error = call_api("POST", f"/sds/{sds_id}/recover")
        if ok:
            flash(f"SDS {sds_id} marked as UP", "success")
        else:
            flash(f"Error: {error}", "danger")
    except Exception as e:
        flash(f"Error: {e}", "danger")
    return redirect(url_for('sds_list'))

# SDC Client Routes
@app.route('/sdc')
def sdc_list():
    try:
        sdcs = requests.get(f"{BASE_URL}/sdc/list").json()
        sdc_capable_nodes = get_active_cluster_nodes_with_capability("SDC")
        discovered_sdcs = get_discovered_components_by_type("SDC")
        if isinstance(sdcs, list) and len(sdcs) == 0 and len(discovered_sdcs) > 0:
            flash(
                "SDC services are discovered by MDM, but SDC entities are not yet registered. "
                "Add SDC entries here to map volumes from this GUI.",
                "warning"
            )
        return render_template('sdc_list.html', sdcs=sdcs, sdc_capable_nodes=sdc_capable_nodes, discovered_sdcs=discovered_sdcs)
    except Exception as e:
        flash(f"Error fetching SDCs: {e}", "danger")
        return render_template('sdc_list.html', sdcs=[], sdc_capable_nodes=[], discovered_sdcs=[])

@app.route('/sdc/add', methods=['POST'])
def sdc_add():
    try:
        name = request.form.get('name')
        cluster_node_id = request.form.get('cluster_node_id')
        ok, payload, error = call_api("POST", "/sdc/add", json={"name": name, "cluster_node_id": cluster_node_id})
        if ok:
            flash(f"SDC added: {payload}", "success")
        else:
            flash(f"Error adding SDC: {error}", "danger")
    except Exception as e:
        flash(f"Error adding SDC: {e}", "danger")
    return redirect(url_for('sdc_list'))

# Volume Routes
@app.route('/volume')
def volume_list():
    try:
        volumes = requests.get(f"{BASE_URL}/vol/list").json()
        pools = requests.get(f"{BASE_URL}/pool/list").json()
        sdcs = requests.get(f"{BASE_URL}/sdc/list").json()
        discovered_sdcs = get_discovered_components_by_type("SDC")
        if isinstance(sdcs, list) and len(sdcs) == 0 and len(discovered_sdcs) > 0:
            flash("No SDC entities found for volume mapping. Add SDC clients first from the SDC page.", "warning")
        return render_template('volume_list.html', volumes=volumes, pools=pools, sdcs=sdcs)
    except Exception as e:
        flash(f"Error fetching volumes: {e}", "danger")
        return render_template('volume_list.html', volumes=[], pools=[], sdcs=[])

@app.route('/volume/create', methods=['POST'])
def volume_create():
    try:
        name = request.form.get('name')
        size_gb = request.form.get('size_gb')
        provisioning = request.form.get('provisioning')
        pool_id = request.form.get('pool_id')
        if not all([name, size_gb, provisioning, pool_id]):
            flash("All fields required", "danger")
            return redirect(url_for('volume_list'))
        ok, payload, error = call_api("POST", "/vol/create", json={
            "name": name,
            "size_gb": float(size_gb) if size_gb else 0.0,
            "provisioning": provisioning,
            "pool_id": int(pool_id) if pool_id else 0
        })
        if ok:
            flash(f"Volume created: {payload}", "success")
        else:
            flash(f"Error creating volume: {error}", "danger")
    except Exception as e:
        flash(f"Error creating volume: {e}", "danger")
    return redirect(url_for('volume_list'))

@app.route('/volume/<int:vol_id>/map', methods=['POST'])
def volume_map(vol_id):
    try:
        sdc_id = request.form.get('sdc_id')
        access_mode = request.form.get('access_mode')
        if not all([sdc_id, access_mode]):
            flash("All fields required", "danger")
            return redirect(url_for('volume_list'))
        ok, _, error = call_api("POST", "/vol/map", params={
            "volume_id": vol_id,
            "sdc_id": int(sdc_id) if sdc_id else 0,
            "access_mode": access_mode
        })
        if ok:
            flash("Volume mapped", "success")
        else:
            flash(f"Error mapping volume: {error}", "danger")
    except Exception as e:
        flash(f"Error mapping volume: {e}", "danger")
    return redirect(url_for('volume_list'))

@app.route('/volume/<int:vol_id>/unmap', methods=['POST'])
def volume_unmap(vol_id):
    try:
        sdc_id = request.form.get('sdc_id')
        if not sdc_id:
            flash("SDC ID required", "danger")
            return redirect(url_for('volume_list'))
        ok, _, error = call_api("POST", "/vol/unmap", params={
            "volume_id": vol_id,
            "sdc_id": int(sdc_id) if sdc_id else 0
        })
        if ok:
            flash("Volume unmapped", "success")
        else:
            flash(f"Error unmapping volume: {error}", "danger")
    except Exception as e:
        flash(f"Error unmapping volume: {e}", "danger")
    return redirect(url_for('volume_list'))

@app.route('/volume/<int:vol_id>/extend', methods=['POST'])
def volume_extend(vol_id):
    try:
        new_size = request.form.get('new_size_gb')
        if not new_size:
            flash("New size required", "danger")
            return redirect(url_for('volume_list'))
        ok, _, error = call_api("POST", "/vol/extend", params={
            "volume_id": vol_id,
            "new_size_gb": float(new_size) if new_size else 0.0
        })
        if ok:
            flash("Volume extended", "success")
        else:
            flash(f"Error extending volume: {error}", "danger")
    except Exception as e:
        flash(f"Error extending volume: {e}", "danger")
    return redirect(url_for('volume_list'))

@app.route('/volume/<int:vol_id>/delete', methods=['POST'])
def volume_delete(vol_id):
    try:
        ok, _, error = call_api("DELETE", f"/vol/{vol_id}")
        if ok:
            flash("Volume deleted", "success")
        else:
            flash(f"Error deleting volume: {error}", "danger")
    except Exception as e:
        flash(f"Error deleting volume: {e}", "danger")
    return redirect(url_for('volume_list'))


@app.route('/volume/<int:vol_id>/io/write', methods=['POST'])
def volume_io_write(vol_id):
    flash("GUI is monitor-only for volume IO. Use SDC/REST APIs for read/write operations.", "danger")
    return redirect(url_for('volume_list'))


@app.route('/volume/<int:vol_id>/io/read', methods=['POST'])
def volume_io_read(vol_id):
    flash("GUI is monitor-only for volume IO. Use SDC/REST APIs for read/write operations.", "danger")
    return redirect(url_for('volume_list'))

# Metrics Routes
@app.route('/metrics')
def metrics():
    try:
        pools = requests.get(f"{BASE_URL}/pool/list").json()
        volumes = requests.get(f"{BASE_URL}/vol/list").json()
        sds_nodes = requests.get(f"{BASE_URL}/sds/list").json()
        return render_template('metrics.html', pools=pools, volumes=volumes, sds_nodes=sds_nodes)
    except Exception as e:
        flash(f"Error fetching metrics: {e}", "danger")
        return render_template('metrics.html', pools=[], volumes=[], sds_nodes=[])

@app.route('/metrics/pool/<int:pool_id>')
def metrics_pool(pool_id):
    try:
        metrics = requests.get(f"{BASE_URL}/metrics/pool/{pool_id}").json()
        return jsonify(metrics)
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route('/metrics/volume/<int:vol_id>')
def metrics_volume(vol_id):
    try:
        metrics = requests.get(f"{BASE_URL}/metrics/volume/{vol_id}").json()
        return jsonify(metrics)
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route('/metrics/sds/<int:sds_id>')
def metrics_sds(sds_id):
    try:
        metrics = requests.get(f"{BASE_URL}/metrics/sds/{sds_id}").json()
        return jsonify(metrics)
    except Exception as e:
        return jsonify({"error": str(e)})

# Rebuild Routes
@app.route('/rebuild')
def rebuild():
    try:
        pools = requests.get(f"{BASE_URL}/pool/list").json()
        return render_template('rebuild.html', pools=pools)
    except Exception as e:
        flash(f"Error fetching pools: {e}", "danger")
        return render_template('rebuild.html', pools=[])

@app.route('/rebuild/<int:pool_id>/start', methods=['POST'])
def rebuild_start(pool_id):
    try:
        ok, payload, error = call_api("POST", f"/rebuild/start/{pool_id}")
        if ok:
            flash(f"Rebuild started: {payload}", "success")
        else:
            flash(f"Error starting rebuild: {error}", "danger")
    except Exception as e:
        flash(f"Error starting rebuild: {e}", "danger")
    return redirect(url_for('rebuild'))

@app.route('/rebuild/<int:pool_id>/status')
def rebuild_status(pool_id):
    try:
        status = requests.get(f"{BASE_URL}/rebuild/status/{pool_id}").json()
        return jsonify(status)
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route('/cluster/bootstrap/minimal', methods=['POST'])
def bootstrap_minimal_cluster():
    try:
        ok, payload, error = call_api("POST", "/cluster/bootstrap/minimal", json={})
        if ok:
            created = payload.get("created", 0) if isinstance(payload, dict) else 0
            updated = payload.get("updated", 0) if isinstance(payload, dict) else 0
            prefix = payload.get("prefix", "demo") if isinstance(payload, dict) else "demo"
            flash(f"Minimal topology bootstrapped for prefix '{prefix}' (created={created}, updated={updated})", "success")
        else:
            flash(f"Bootstrap failed: {error}", "danger")
    except Exception as e:
        flash(f"Bootstrap failed: {e}", "danger")
    return redirect(url_for('index'))

# Health Dashboard Routes
@app.route('/health')
def health_dashboard():
    """Health dashboard page (HTML)."""
    try:
        # Get cached health data
        health_summary = get_cached_data("health_summary") or {}
        health_metrics = get_cached_data("health_metrics") or {}
        alert_counts = get_alert_counts()
        active_alerts = get_active_alerts(limit=10)
        
        # Get component health data and organize by type
        component_health_data = get_cached_data("component_health")
        components_by_type = {}
        
        if component_health_data:
            if isinstance(component_health_data, dict):
                components = component_health_data.get("components", [])
            elif isinstance(component_health_data, list):
                components = component_health_data
            else:
                components = []
                
            # Group components by type
            for comp in components:
                comp_type = comp.get("type", "unknown")
                if comp_type not in components_by_type:
                    components_by_type[comp_type] = []
                components_by_type[comp_type].append(comp)
        
        # Format alerts for display
        active_display = [format_alert_for_display(a) for a in active_alerts]
        
        return render_template(
            'health_dashboard.html',
            health_summary=health_summary,
            health_metrics=health_metrics,
            alert_counts=alert_counts,
            active_alerts=active_display,
            components_by_type=components_by_type
        )
    except Exception as e:
        flash(f"Error loading health dashboard: {e}", "danger")
        return render_template(
            'health_dashboard.html',
            health_summary={},
            health_metrics={},
            alert_counts={"total": 0, "critical": 0, "error": 0, "warning": 0, "info": 0},
            active_alerts=[],
            components_by_type={}
        )

@app.route('/health/api/summary')
def health_api_summary():
    """Health dashboard data API (JSON)."""
    try:
        # Get cached health data from monitor
        health_summary = get_cached_data("health_summary") or {}
        component_health_data = get_cached_data("component_health")
        health_metrics = get_cached_data("health_metrics") or {}
        pool_list = get_cached_data("pool_list") or []
        volume_list = get_cached_data("volume_list") or []
        
        # Get alert counts
        alert_counts = get_alert_counts()
        
        # Test expects health_summary, health_metrics, alert_counts as top-level keys
        summary = {
            "health_summary": health_summary if isinstance(health_summary, dict) else {},
            "health_metrics": health_metrics if isinstance(health_metrics, dict) else {},
            "alert_counts": alert_counts if isinstance(alert_counts, dict) else {},
            "component_health": component_health_data,
            "pools": {
                "total": len(pool_list) if isinstance(pool_list, list) else 0,
                "total_capacity_gb": sum(p.get("total_capacity_gb", 0) for p in pool_list if isinstance(p, dict)) if isinstance(pool_list, list) else 0,
                "available_capacity_gb": sum(p.get("available_capacity_gb", 0) for p in pool_list if isinstance(p, dict)) if isinstance(pool_list, list) else 0,
            },
            "volumes": {
                "total": len(volume_list) if isinstance(volume_list, list) else 0,
            }
        }
        
        return jsonify(summary)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/health/api/components')
def health_api_components():
    """Component monitoring data API (JSON) - returns list of components directly."""
    try:
        # Get cached component health data from monitor
        component_health_data = get_cached_data("component_health")
        
        # Extract components list
        components = []
        
        if isinstance(component_health_data, dict):
            components = component_health_data.get("components", [])
        elif isinstance(component_health_data, list):
            components = component_health_data
        
        # Test expects a direct list, not a dict wrapper
        return jsonify(components)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Alerts Routes
@app.route('/alerts')
def alerts_list():
    """Alerts management page (HTML)."""
    try:
        # Get active and recent alerts
        active_alerts = get_active_alerts(limit=50)
        recent_alerts = get_recent_alerts(hours=24, limit=100)
        alert_counts = get_alert_counts()
        alert_history = get_alert_history_summary(hours=24)
        
        # Format alerts for display
        active_display = [format_alert_for_display(a) for a in active_alerts]
        recent_display = [format_alert_for_display(a) for a in recent_alerts]
        
        return render_template(
            'alerts_list.html',
            active_alerts=active_display,
            recent_alerts=recent_display,
            alert_counts=alert_counts,
            alert_history=alert_history
        )
    except Exception as e:
        flash(f"Error fetching alerts: {e}", "danger")
        return render_template(
            'alerts_list.html',
            active_alerts=[],
            recent_alerts=[],
            alert_counts={"total": 0, "critical": 0, "error": 0, "warning": 0, "info": 0},
            alert_history={"total_alerts": 0, "resolved": 0}
        )

@app.route('/alerts/acknowledge/<int:alert_id>', methods=['POST'])
def alert_acknowledge(alert_id):
    """Acknowledge an alert."""
    try:
        username = request.form.get('username', 'admin')
        success = acknowledge_alert(alert_id, username)
        if success:
            flash(f"Alert {alert_id} acknowledged", "success")
        else:
            flash(f"Failed to acknowledge alert {alert_id}", "danger")
    except Exception as e:
        flash(f"Error acknowledging alert: {e}", "danger")
    return redirect(url_for('alerts_list'))

@app.route('/alerts/resolve/<int:alert_id>', methods=['POST'])
def alert_resolve(alert_id):
    """Resolve an alert."""
    try:
        username = request.form.get('username', 'admin')
        success = resolve_alert(alert_id, username)
        if success:
            flash(f"Alert {alert_id} resolved", "success")
        else:
            flash(f"Failed to resolve alert {alert_id}", "danger")
    except Exception as e:
        flash(f"Error resolving alert: {e}", "danger")
    return redirect(url_for('alerts_list'))

if __name__ == '__main__':
    host = str(os.getenv("POWERFLEX_GUI_BIND_HOST", "0.0.0.0")).strip()
    port = int(str(os.getenv("POWERFLEX_GUI_PORT", "5000")).strip())
    debug = str(os.getenv("POWERFLEX_GUI_DEBUG", "false")).strip().lower() in {"1", "true", "yes"}
    app.run(host=host, port=port, debug=debug)
