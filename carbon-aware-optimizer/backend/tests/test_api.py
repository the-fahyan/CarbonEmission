from datetime import timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import slots_payload


def now_of(c):
    from datetime import datetime
    return datetime.fromisoformat(c.get("/api/health").json()["sim_time"].rstrip("Z"))


def setup_timeline(c, values=(700, 600, 420, 250, 120, 110, 120, 300, 500, 650, 650, 650)):
    start = now_of(c).replace(second=0, microsecond=0)
    start -= timedelta(minutes=start.minute % 15)
    r = c.put("/api/telemetry", json=slots_payload(start, list(values)))
    assert r.status_code == 200, r.text
    return start


def job(**kw):
    base = {"name": "J", "duration_minutes": 15, "estimated_energy_kwh": 2.0, "priority": "normal", "deferrable": True}
    base.update(kw)
    return base


def test_health_and_docs(client):
    assert client.get("/api/health").json()["status"] == "ok"
    assert client.get("/docs").status_code == 200


def test_job_create_list_get_and_schedule(client):
    setup_timeline(client)
    r = client.post("/api/jobs", json=job(deadline=(now_of(client) + timedelta(hours=2)).isoformat() + "Z"))
    assert r.status_code == 201
    j = r.json()
    assert j["status"] in ("SCHEDULED", "WAITING") and j["scheduling_explanation"]
    assert client.get("/api/jobs").json()["total"] == 1
    assert client.get(f"/api/jobs/{j['id']}").json()["id"] == j["id"]
    dec = client.get(f"/api/jobs/{j['id']}/decisions").json()
    assert dec and dec[0]["explanation"]
    assert client.get(f"/api/jobs/{j['id']}/logs").json()
    assert client.get("/api/scheduler/history").json()


def test_invalid_requests_and_missing_resources(client):
    r = client.post("/api/jobs", json=job(duration_minutes=0))
    assert r.status_code == 422 and r.json()["error"] == "validation_error"
    assert client.post("/api/jobs", json=job(priority="urgent")).status_code == 422
    assert client.post("/api/jobs", json=job(estimated_energy_kwh=-1)).status_code == 422
    assert client.get("/api/jobs/999").status_code == 404
    assert client.post("/api/jobs/999/cancel").status_code == 404
    bad = client.put("/api/telemetry", json={"slots": [
        {"start_time": "2026-10-14T10:00:00Z", "duration_minutes": 30, "intensity_g_per_kwh": 5},
        {"start_time": "2026-10-14T10:15:00Z", "duration_minutes": 15, "intensity_g_per_kwh": 5}]})
    assert bad.status_code == 422 and "overlap" in " ".join(bad.json()["details"])
    assert client.put("/api/telemetry", json={"slots": [
        {"start_time": "2026-10-14T10:00:00Z", "duration_minutes": 15, "intensity_g_per_kwh": -5}]}).status_code == 422


def test_telemetry_crud_and_reschedule_on_change(client):
    setup_timeline(client)
    j = client.post("/api/jobs", json=job(deadline=(now_of(client) + timedelta(hours=2)).isoformat() + "Z")).json()
    before = j["scheduled_start"]
    t = client.get("/api/telemetry").json()
    assert t["mode"] == "manual_simulated" and t["slots"][0]["kind"] in ("current", "historical", "future")
    runs_before = len(client.get("/api/scheduler/history").json())
    # Make slot #3 (always >= 30 min after the floored timeline start, i.e. in the future regardless of the
    # wall-clock minute) the cleanest slot -> the plan must move there. (Slot 0 would make the test time-dependent.)
    first = t["slots"][2]["id"]
    assert client.patch(f"/api/telemetry/slots/{first}", json={"intensity_g_per_kwh": 1}).status_code == 200
    assert len(client.get("/api/scheduler/history").json()) == runs_before + 1
    after = client.get(f"/api/jobs/{j['id']}").json()["scheduled_start"]
    assert after != before and after == t["slots"][2]["start_time"]
    assert client.delete(f"/api/telemetry/slots/{first}").status_code == 200
    assert client.delete("/api/telemetry/slots/99999").status_code == 404


def test_cancel_and_retry_rules(client):
    setup_timeline(client)
    j = client.post("/api/jobs", json=job()).json()
    assert client.post(f"/api/jobs/{j['id']}/retry").status_code == 409  # not retryable yet
    assert client.post(f"/api/jobs/{j['id']}/cancel").json()["status"] == "CANCELLED"
    assert client.post(f"/api/jobs/{j['id']}/cancel").status_code == 409  # already cancelled
    assert client.post(f"/api/jobs/{j['id']}/retry").json()["status"] in ("SCHEDULED", "WAITING", "PENDING")


def test_full_execution_failure_retry_preserves_history(client):
    setup_timeline(client)
    j = client.post("/api/jobs", json=job(duration_minutes=30, simulate_failure=True, deferrable=False)).json()
    client.post("/api/worker/advance", json={"minutes": 40})
    j1 = client.get(f"/api/jobs/{j['id']}").json()
    assert j1["status"] == "FAILED" and len(j1["attempts"]) == 1
    assert client.post(f"/api/jobs/{j['id']}/retry").status_code == 200
    client.post("/api/worker/advance", json={"minutes": 60})
    j2 = client.get(f"/api/jobs/{j['id']}").json()
    assert j2["status"] == "COMPLETED" and len(j2["attempts"]) == 2
    assert [a["state"] for a in j2["attempts"]] == ["FAILED", "COMPLETED"]
    assert client.post(f"/api/jobs/{j['id']}/cancel").status_code == 409  # completed
    assert client.post(f"/api/jobs/{j['id']}/retry").status_code == 409
    # completed job is never executed again
    client.post("/api/worker/advance", json={"minutes": 120})
    assert len(client.get(f"/api/jobs/{j['id']}").json()["attempts"]) == 2


def test_running_not_marked_completed_early_and_cancel_running(client):
    setup_timeline(client)
    j = client.post("/api/jobs", json=job(duration_minutes=60, deferrable=False)).json()
    client.post("/api/worker/advance", json={"minutes": 5})
    cur = client.get(f"/api/jobs/{j['id']}").json()
    assert cur["status"] == "RUNNING" and 0 < cur["progress"] < 1
    assert client.post(f"/api/jobs/{j['id']}/cancel").json()["status"] == "CANCELLED"
    assert client.get(f"/api/jobs/{j['id']}").json()["attempts"][0]["state"] == "CANCELLED"


def test_capacity_enforced_in_worker(client):
    setup_timeline(client)
    client.patch("/api/settings", json={"capacity": 1})
    for _ in range(3):
        client.post("/api/jobs", json=job(duration_minutes=30, deferrable=False))
    client.post("/api/worker/advance", json={"minutes": 5})
    items = client.get("/api/jobs").json()["items"]
    assert sum(1 for i in items if i["status"] == "RUNNING") <= 1


def test_demo_load_requires_confirmation_and_keeps_user_jobs(client):
    setup_timeline(client)
    mine = client.post("/api/jobs", json=job(name="mine")).json()
    assert client.post("/api/demo/load", json={}).status_code == 400
    assert client.post("/api/demo/load", json={"confirm": True}).status_code == 200
    names = [i["name"] for i in client.get("/api/jobs?limit=200").json()["items"]]
    assert "mine" in names and client.get(f"/api/jobs/{mine['id']}").status_code == 200
    run = client.post("/api/scheduler/run").json()
    assert run["solver_status"] == "optimal" and run["jobs_unschedulable"] >= 1
    assert client.get("/api/scheduler/status").json()["diagnostics"]  # unschedulable job explained
    # reproducible: loading again replaces demo jobs, doesn't duplicate
    client.post("/api/demo/load", json={"confirm": True})
    assert sum(1 for i in client.get("/api/jobs?limit=200").json()["items"] if i["is_demo"]) == 9
    s = client.get("/api/analytics/summary").json()
    assert s["telemetry_mode"] == "manual_simulated"
    assert client.get("/api/logs/export.csv").text.startswith("id,sim_time_utc")
    assert client.get("/api/analytics/export.csv").status_code == 200
    assert client.get("/api/scheduler/preview").json()["ok"]


def test_failed_optimization_does_not_corrupt_records(client):
    setup_timeline(client)
    j = client.post("/api/jobs", json=job()).json()
    before = client.get(f"/api/jobs/{j['id']}").json()
    with patch("app.services.optimizer.milp") as m:
        class R:  # solver failure
            x = None; status = 4; fun = None
        m.return_value = R()
        run = client.post("/api/scheduler/run").json()
    assert run["committed"] is False and run["solver_status"] == "solver_error"
    after = client.get(f"/api/jobs/{j['id']}").json()
    assert after["status"] == before["status"] and after["scheduled_start"] == before["scheduled_start"]


def test_persistence_and_restart_reconciliation(tmp_path):
    url = f"sqlite:///{(tmp_path / 'p.db').as_posix()}"
    with TestClient(create_app(url, start_worker=False)) as c:
        setup_timeline(c)
        j = c.post("/api/jobs", json=job(duration_minutes=60, deferrable=False)).json()
        c.post("/api/worker/advance", json={"minutes": 5})
        assert c.get(f"/api/jobs/{j['id']}").json()["status"] == "RUNNING"
    # "crash/restart": new app on the same DB
    with TestClient(create_app(url, start_worker=False)) as c2:
        got = c2.get(f"/api/jobs/{j['id']}").json()
        assert got["status"] == "FAILED" and got["attempts"][0]["state"] == "INTERRUPTED"
        assert "restart" in got["status_reason"]
        assert len(c2.get("/api/telemetry").json()["slots"]) == 12
