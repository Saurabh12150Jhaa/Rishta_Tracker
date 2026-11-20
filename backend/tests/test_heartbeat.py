from conftest import SECRET


def test_heartbeat_marks_worker_online_without_claiming_tasks(iso):
    iso.post("/api/worker/heartbeat", headers={"X-Worker-Secret": "bad"}, json={"hostname": "m"})
    assert iso.get("/api/worker/status", headers=iso.member_headers).json()["remote_mac_worker_online"] is False
    r = iso.post("/api/worker/heartbeat", headers={"X-Worker-Secret": SECRET}, json={"hostname": "mac1"})
    assert r.status_code == 200
    st = iso.get("/api/worker/status", headers=iso.member_headers).json()
    assert st["remote_mac_worker_online"] is True and st["worker_hostname"] == "mac1"
