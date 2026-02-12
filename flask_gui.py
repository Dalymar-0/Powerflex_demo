from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
import requests
import json
import time

app = Flask(__name__)
app.secret_key = 'powerflex-demo-secret'
BASE_URL = "http://127.0.0.1:8001"


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
        return render_template('sds_list.html', sds_nodes=sds_nodes, pds=pds)
    except Exception as e:
        flash(f"Error fetching SDS nodes: {e}", "danger")
        return render_template('sds_list.html', sds_nodes=[], pds=[])

@app.route('/sds/add', methods=['POST'])
def sds_add():
    try:
        name = request.form.get('name')
        total_capacity = request.form.get('total_capacity_gb')
        devices = request.form.get('devices')
        pd_id = request.form.get('pd_id')
        if not all([name, total_capacity, devices, pd_id]):
            flash("All fields required", "danger")
            return redirect(url_for('sds_list'))
        ok, payload, error = call_api("POST", "/sds/add", json={
            "name": name,
            "total_capacity_gb": float(total_capacity) if total_capacity else 0.0,
            "devices": devices,
            "protection_domain_id": int(pd_id) if pd_id else 0
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
        return render_template('sdc_list.html', sdcs=sdcs)
    except Exception as e:
        flash(f"Error fetching SDCs: {e}", "danger")
        return render_template('sdc_list.html', sdcs=[])

@app.route('/sdc/add', methods=['POST'])
def sdc_add():
    try:
        name = request.form.get('name')
        ok, payload, error = call_api("POST", "/sdc/add", json={"name": name})
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

# Demo Scenarios
@app.route('/scenarios')
def scenarios():
    return render_template('scenarios.html')

@app.route('/scenario_a', methods=['POST'])
def scenario_a():
    try:
        suffix = str(int(time.time()))
        pd_ok, pd_payload, pd_error = call_api("POST", "/pd/create", json={"name": f"PD1_{suffix}"})
        if not pd_ok:
            flash(f"Scenario A failed creating PD: {pd_error}", "danger")
            return redirect(url_for('scenarios'))

        pd = pd_payload
        pd_id = pd["id"]

        for i in range(1, 4):
            ok, _, error = call_api("POST", "/sds/add", json={
                "name": f"SDS{i}_{suffix}",
                "total_capacity_gb": 1000,
                "devices": "SSD,HDD",
                "protection_domain_id": pd_id
            })
            if not ok:
                flash(f"Scenario A failed adding SDS{i}: {error}", "danger")
                return redirect(url_for('scenarios'))

        pool_ok, pool_payload, pool_error = call_api("POST", "/pool/create", json={
            "name": f"Pool1_{suffix}",
            "pd_id": pd_id,
            "protection_policy": "two_copies",
            "total_capacity_gb": 2000
        })
        if not pool_ok:
            flash(f"Scenario A failed creating pool: {pool_error}", "danger")
            return redirect(url_for('scenarios'))

        pool_id = pool_payload["id"]

        sdc_ids = []
        for i in range(1, 3):
            sdc_ok, sdc_payload, sdc_error = call_api("POST", "/sdc/add", json={"name": f"SDC{i}_{suffix}"})
            if not sdc_ok:
                flash(f"Scenario A failed adding SDC{i}: {sdc_error}", "danger")
                return redirect(url_for('scenarios'))
            sdc_ids.append(sdc_payload["id"])

        vol_ok, vol_payload, vol_error = call_api("POST", "/vol/create", json={
            "name": f"Vol1_{suffix}",
            "size_gb": 500,
            "provisioning": "thin",
            "pool_id": pool_id
        })
        if not vol_ok:
            flash(f"Scenario A failed creating volume: {vol_error}", "danger")
            return redirect(url_for('scenarios'))

        vol_id = vol_payload["id"]
        map_ok, _, map_error = call_api("POST", "/vol/map", params={"volume_id": vol_id, "sdc_id": sdc_ids[0], "access_mode": "readWrite"})
        if not map_ok:
            flash(f"Scenario A failed mapping volume: {map_error}", "danger")
            return redirect(url_for('scenarios'))

        flash("Scenario A completed: Basic Deployment", "success")
    except Exception as e:
        flash(f"Scenario A failed: {e}", "danger")
    return redirect(url_for('scenarios'))

if __name__ == '__main__':
    app.run(debug=True)
