"""Sprint 2 HITL safety gate (SRS 4.2 / 5.2): preview fingerprint + apply guards.

Endpoints are exercised in-process by faking CherryPy's thread-local serving
context (request/response/session); capability tools are plain decorators that
store config on the function, so the raw method can be called directly.
"""
import os

os.environ.setdefault("DSA_MOCK", "1")  # keep device.py from importing netmiko

import cherrypy  # noqa: E402
import pytest  # noqa: E402

from app import db, main  # noqa: E402
from app.main import _fingerprint  # noqa: E402


# ---- _fingerprint (REQ-4.2-1/2) -------------------------------------------
def test_fingerprint_deterministic():
    cmds = ["vlan 10", "name Sales"]
    assert _fingerprint(cmds, 1) == _fingerprint(list(cmds), 1)
    assert len(_fingerprint(cmds, 1)) == 16


def test_fingerprint_changes_with_command():
    assert _fingerprint(["vlan 10"], 1) != _fingerprint(["vlan 20"], 1)
    assert _fingerprint(["vlan 10"], 1) != _fingerprint(["vlan 10", "name X"], 1)


def test_fingerprint_differs_per_device():
    cmds = ["vlan 10"]
    assert _fingerprint(cmds, 1) != _fingerprint(cmds, 2)


# ---- endpoints -------------------------------------------------------------
class _Req:
    def __init__(self, payload):
        import types
        self.json = payload
        self.method = "POST"
        self.remote = types.SimpleNamespace(ip="127.0.0.1")


class _Resp:
    status = 200


@pytest.fixture()
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///" + str(tmp_path / "hitl.db").replace("\\", "/"))
    monkeypatch.setenv("SECRET_KEY", "testkey")
    db.init()
    did = db.upsert_device("Default-Network", "10.0.0.1", "admin", "pw", "sec", "sw1",
                           {"hostname": "sw1", "platform": "Cisco", "version": "1", "mgmt_if": "Gi0/1"})
    a = main.Api()

    def call(payload):
        cherrypy.serving.request = _Req(payload)
        cherrypy.serving.response = _Resp()
        cherrypy.session = {"user": "admin", "device_id": did}
        return cherrypy.serving.response

    return a, call, did


def test_preview_lists_commands_without_touching_device(api, monkeypatch):
    a, call, _ = api
    monkeypatch.setattr(main.device, "push", lambda *_: pytest.fail("preview must not push"))
    monkeypatch.setattr(main.device, "running_config", lambda *_: pytest.fail("preview must not read config"))
    resp = call({"kind": "vlan", "vlan_id": 10, "name": "Sales"})
    out = a.preview()
    assert resp.status == 200
    assert out == {"ok": True, "commands": ["vlan 10", "name Sales"],
                   "preview_id": _fingerprint(["vlan 10", "name Sales"], 1)}


def test_preview_bad_input_is_400(api):
    a, call, _ = api
    resp = call({"kind": "nope"})
    out = a.preview()
    assert resp.status == 400 and "error" in out


def test_apply_requires_confirm(api, monkeypatch):
    a, call, _ = api
    monkeypatch.setattr(main.device, "push", lambda *_: pytest.fail("must not push without confirm"))
    resp = call({"kind": "vlan", "vlan_id": 10})
    out = a.apply()
    assert resp.status == 409 and "error" in out


def test_apply_rejects_stale_preview(api, monkeypatch):
    a, call, _ = api
    monkeypatch.setattr(main.device, "push", lambda *_: pytest.fail("must not push on stale preview"))
    resp = call({"kind": "vlan", "vlan_id": 10, "confirm": True, "preview_id": "deadbeef"})
    out = a.apply()
    assert resp.status == 409 and "error" in out


def test_apply_backs_up_then_pushes(api, monkeypatch):
    a, call, did = api
    pushed = {}
    monkeypatch.setattr(main.device, "push", lambda creds, cmds: pushed.update(cmds=cmds) or "ok")
    # running_config comes from the DSA_MOCK switch; back up must happen before push
    resp = call({"kind": "vlan", "vlan_id": 10, "confirm": True,
                 "preview_id": _fingerprint(["vlan 10"], did)})
    out = a.apply()
    assert resp.status == 200 and out["ok"] is True and out["backup_id"] >= 1
    assert pushed["cmds"] == ["vlan 10"]
    with db._Conn() as c:
        assert c.q("SELECT id FROM tbl_backups WHERE device_id=%s", (did,))[0]["id"] == out["backup_id"]


def test_apply_aborts_when_backup_fails(api, monkeypatch):
    a, call, did = api
    monkeypatch.setattr(main.device, "running_config", lambda *_: (_ for _ in ()).throw(RuntimeError("no ssh")))
    monkeypatch.setattr(main.device, "push", lambda *_: pytest.fail("must not push when backup fails"))
    resp = call({"kind": "vlan", "vlan_id": 10, "confirm": True,
                 "preview_id": _fingerprint(["vlan 10"], did)})
    out = a.apply()
    assert resp.status == 502 and "aborted" in out["error"]
