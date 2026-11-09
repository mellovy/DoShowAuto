import hashlib, html, os, time
import cherrypy
from . import commands as cmd, db, device, parse

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_USER = lambda: os.environ.get("DEVICE_USER", "admin")
_fails = {}


def shell(page):
    show_console = page in ("general", "configure")
    console = """
<section id="console" class="dock"><div class="dock-tabs"><button class="tab on" data-t="cons">CONSOLE</button>
<button class="tab" data-t="calc" id="calc-tab" hidden>SUBNET CALCULATOR</button><span class="sp"></span><button id="dock-min" title="Collapse">&#8964;</button><button id="dock-x" title="Close">&#10005;</button></div>
<div class="dock-body"><div id="pane-cons"><div class="conshead"><span id="live-title">LIVE CONSOLE</span><button id="run" class="btn blue sm">&#9654; RUN</button></div>
<div id="term" class="term"></div><div class="termin"><span>user@ds-auto:~$</span><input id="cmdin" autocomplete="off" placeholder="show ..."></div></div>
<div id="pane-calc" hidden></div>
<aside class="maint"><h4>&#128295; MAINTENANCE</h4><button class="mbtn" data-m="save_config">Save Configuration</button><button class="mbtn" data-m="backup">Backup Config</button><button class="mbtn" data-m="nvram">Save to NVRAM</button></aside></div></section>""" if show_console else ""
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>DoShowAuto Console</title>
<link rel="stylesheet" href="/static/style.css"></head><body data-page="{page}">
<header><div class="brand">DoShowAuto Console</div><div class="netsel"><label>NETWORK</label><select id="network"></select></div></header>
<nav class="tabs"><a href="/" data-p="general">General</a>
<span class="dd"><a href="/configure" data-p="configure">Configure &#9662;</a><div class="ddm" id="cfgmenu">
<a href="/configure#interfaces">Interfaces</a><a href="/configure#dhcp">DHCP Pools</a><a href="/configure#vlans">VLANs</a><a href="/configure#routing">Routing</a><a href="/configure#etherchannel">EtherChannel</a><a href="/configure#portsec">Port Security</a></div></span>
<a href="/devices" data-p="devices">Devices</a><a href="/logs" data-p="logs">Logs</a></nav>
<main id="main"></main>{console}
<footer class="status"><span>Connected Device: <b id="st-dev">none</b> &nbsp;|&nbsp; Device Status: <b id="st-state">-</b></span><a href="/logout" class="signout">&#8999; SIGN OUT</a></footer>
<script src="/static/app.js"></script></body></html>"""


LOGIN = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>DoShowAuto - Sign in</title>
<link rel="stylesheet" href="/static/style.css"></head><body class="loginbody"><form method="post" class="logincard">
<div class="logo">DoShowAuto</div><p class="sub">Automated configuration management for Cisco devices</p>%s
<label>ADMIN USERNAME<input name="username" autocomplete="username" required autofocus></label>
<label>ACCESS TOKEN / PASSWORD<input name="password" type="password" autocomplete="current-password" required></label>
<label class="chk"><input type="checkbox" name="remember" value="1"> Remember this session</label>
<button class="btn blue wide">SIGN IN</button>
<p class="notice">&#9888; Restricted system. All access attempts and session activities are logged for auditing and compliance purposes.</p></form></body></html>"""


def jin():
    b = getattr(cherrypy.request, "json", None)
    return b if isinstance(b, dict) else {}


def auth():
    u = cherrypy.session.get("user")
    if not u:
        raise cherrypy.HTTPError(401, "Not signed in")
    return u


def cur_device():
    return db.device_creds(cherrypy.session.get("device_id"))


def bad(msg, code=400):
    cherrypy.response.status = code
    return {"error": str(msg)}


def ago(ts):
    if not ts:
        return "never"
    import datetime as dt
    t = ts if isinstance(ts, dt.datetime) else dt.datetime.fromisoformat(str(ts).replace("Z", "")).replace(tzinfo=dt.timezone.utc)
    s = int((dt.datetime.now(dt.timezone.utc) - (t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc))).total_seconds())
    return "just now" if s < 60 else f"{s // 60} mins ago" if s < 3600 else f"{s // 3600} hrs ago" if s < 86400 else f"{s // 86400} days ago"


# kind -> command builder (SRS 4.1.3 / screens 3.1.1.2 - 3.1.1.8)
def _b(p):
    k = p.get("kind")
    if k == "basic":
        return cmd.basic_config(p.get("hostname"), p.get("banner"), p.get("secret") if p.get("enable_secret") else None, bool(p.get("encryption")))
    if k == "interface":
        return cmd.interface_config(p["interface"], p.get("assignment", "static"), p.get("ip"), p.get("mask"), p.get("description"),
                                    p.get("vlan"), bool(p.get("trunk")), p.get("enabled"))
    if k == "dhcp":
        return cmd.dhcp_pool(p["name"], p["network"], p.get("mask"), p.get("gateway"), p.get("dns"), p.get("start_ip"),
                             p.get("lease_days", 1), p.get("lease_hours", 0), p.get("lease_minutes", 0))
    if k == "vlan":
        return cmd.vlan(p["vlan_id"], p.get("name"))
    if k == "static_route":
        return cmd.static_route(p["network"], p["mask"], p["next_hop"])
    if k == "dynamic_route":
        return cmd.dynamic_routing(p["protocol"], p.get("process_id"), p.get("networks"), p.get("area", 0))
    if k == "etherchannel":
        return cmd.etherchannel(p["group"], p.get("protocol"), p.get("interfaces", []), p.get("mode"), p.get("description"))
    if k == "portsec":
        return cmd.port_security(p.get("interfaces", []), bool(p.get("enabled", True)), p.get("max_mac", 1), p.get("violation", "shutdown"), bool(p.get("sticky", True)))
    raise ValueError("Unknown configuration type")


def _fingerprint(cmds, dev_id):
    """Stable id tying a reviewed command list to a device (REQ-4.2-1/2)."""
    return hashlib.sha256((f"{dev_id}|" + "\n".join(cmds)).encode()).hexdigest()[:16]


class Api:
    @cherrypy.expose
    @cherrypy.tools.json_out()
    def me(self):
        u = auth()
        nets = db.networks()
        net = cherrypy.session.get("network") or (nets[0] if nets else "Default-Network")
        did, dev = cherrypy.session.get("device_id"), None
        rows = db.devices()
        if not did and device.MOCK and rows:  # DSA_MOCK: auto-use the seeded simulated switch
            did = rows[0]["id"]; cherrypy.session["device_id"] = did
        for d in rows:
            if d["id"] == did:
                dev = {k: d[k] for k in ("id", "name", "host", "status", "network")}
        return {"user": db.get_user(u) or {"username": u, "email": ""}, "networks": nets or [net], "network": net,
                "device": dev, "ai_mode": db.setting("ai_mode", "local")}

    @cherrypy.expose
    @cherrypy.tools.json_in()
    @cherrypy.tools.json_out()
    def network(self):
        auth(); cherrypy.session["network"] = str(jin().get("name", ""))[:60] or "Default-Network"
        return {"ok": True}

    @cherrypy.expose
    @cherrypy.tools.json_in()
    @cherrypy.tools.json_out()
    def profile(self):
        u = auth(); p = jin()
        name = (p.get("username") or "").strip()
        if not name:
            return bad("Username required")
        if p.get("password") and len(p["password"]) < 8:
            return bad("Password must be at least 8 characters")
        try:
            db.update_profile(u, name, (p.get("email") or "").strip(), p.get("password") or None)
        except Exception as e:
            return bad(e)
        cherrypy.session["user"] = name
        db.audit(name, cherrypy.request.remote.ip, "updated the admin profile.")
        return {"ok": True}

    @cherrypy.expose
    @cherrypy.tools.json_in()
    @cherrypy.tools.json_out()
    def settings(self):
        auth(); mode = jin().get("ai_mode")
        if mode not in ("local", "cloud"):
            return bad("ai_mode must be local or cloud")
        db.set_setting("ai_mode", mode)
        return {"ok": True}

    @cherrypy.expose
    @cherrypy.tools.json_in()
    @cherrypy.tools.json_out()
    def connect(self):
        u = auth(); p = jin()
        ip, secret = (p.get("ip") or "").strip(), p.get("secret") or ""
        if not ip or not secret:
            return bad("IP address and auth secret are required")
        existing = db.device_by_host(ip)
        user = (p.get("username") or (existing or {}).get("username") or DEFAULT_USER()).strip()
        creds = {"device_type": "cisco_ios", "host": ip, "username": user, "password": secret, "secret": p.get("enable") or secret}
        try:
            facts = device.probe(creds)
        except Exception as e:
            return bad(f"Could not connect over SSH: {e}", 502)
        net = cherrypy.session.get("network") or "Default-Network"
        did = db.upsert_device(net, ip, user, secret, creds["secret"], facts["hostname"], facts)
        cherrypy.session["device_id"] = did; cherrypy.session["network"] = net
        db.audit(u, ip, f"connected to {facts['hostname']} over SSH.")
        return {"ok": True, "hostname": facts["hostname"]}

    @cherrypy.expose
    @cherrypy.tools.json_out()
    def devices(self):
        auth()
        rows = db.devices(cherrypy.session.get("network"))
        return [dict(r, last_check=ago(r["last_check"]), selected=r["id"] == cherrypy.session.get("device_id")) for r in rows]

    @cherrypy.expose
    @cherrypy.tools.json_in()
    @cherrypy.tools.json_out()
    def device(self, action=None):
        u = auth(); did = int(jin().get("id", 0))
        if action == "select":
            cherrypy.session["device_id"] = did
            return {"ok": True}
        if action == "delete":
            db.delete_device(did)
            if cherrypy.session.get("device_id") == did:
                cherrypy.session.pop("device_id", None)
            db.audit(u, "", f"deleted device #{did}.")
            return {"ok": True}
        if action == "check":
            try:
                facts = device.probe(db.device_creds(did)); db.set_status(did, "Up", facts)
                return {"ok": True, "status": "Up"}
            except Exception as e:
                db.set_status(did, "Down")
                return {"ok": False, "status": "Down", "error": str(e)}
        if action == "show":
            try:
                c = cmd.show(jin().get("command")); creds = db.device_creds(did)
                out = device.run(creds, c); db.audit(u, creds["host"], c, out)
                return {"output": out}
            except Exception as e:
                return bad(e)
        return bad("Unknown action", 404)

    @cherrypy.expose
    @cherrypy.tools.json_out()
    def inventory(self, kind=None):
        auth()
        try:
            raw = device.inventory_raw(cur_device())
        except Exception as e:
            return bad(e)
        ifs = parse.interfaces(raw["cfg"], raw["brief"])
        for i in ifs:
            i["short"] = parse.short(i["name"])
        if kind == "interfaces":
            return ifs
        if kind == "vlans":
            return parse.vlans(raw["vlan"])
        if kind == "dhcp":
            return parse.dhcp_pools(raw["cfg"], raw["dhcp"])
        if kind == "routes":
            return parse.routes(raw["cfg"])
        if kind == "etherchannel":
            return {"groups": parse.etherchannels(raw["ec"], ifs), "interfaces": ifs}
        if kind == "portsec":
            v = parse.portsec_counts(raw["ps"])
            return [dict(i, violations=v.get(i["short"], 0)) for i in ifs if i["name"].startswith(("Gigabit", "Fast", "Ten"))]
        return bad("Unknown inventory", 404)

    @cherrypy.expose
    @cherrypy.tools.json_in()
    @cherrypy.tools.json_out()
    def preview(self):
        auth(); p = jin()
        try:
            cmds = _b(p)
            creds = cur_device()
        except (ValueError, KeyError) as e:
            return bad(f"Invalid input: {e}")
        return {"ok": True, "commands": cmds, "preview_id": _fingerprint(cmds, creds["id"])}

    @cherrypy.expose
    @cherrypy.tools.json_in()
    @cherrypy.tools.json_out()
    def apply(self):
        u = auth(); p = jin()
        if not p.get("confirm"):
            return bad("Review the command preview and confirm before deploying.", 409)
        try:
            cmds = _b(p)
            creds = cur_device()
        except (ValueError, KeyError) as e:
            return bad(f"Invalid input: {e}")
        if p.get("preview_id") != _fingerprint(cmds, creds["id"]):
            return bad("The reviewed commands no longer match the preview. Review again.", 409)
        try:
            bid = db.save_backup(creds["id"], device.running_config(creds))
        except Exception as e:
            return bad(f"Pre-change backup failed; deployment aborted: {e}", 502)
        try:
            out = device.push(creds, cmds)
        except Exception as e:
            return bad(f"SSH error: {e}", 502)
        db.audit(u, creds["host"], "; ".join(cmds), out)
        if device.has_error(out):
            return {"ok": False, "commands": cmds, "output": out, "backup_id": bid, "error": "The device rejected one or more commands."}
        return {"ok": True, "commands": cmds, "output": out, "backup_id": bid}

    @cherrypy.expose
    @cherrypy.tools.json_in()
    @cherrypy.tools.json_out()
    def console(self):
        u = auth()
        try:
            c = cmd.show(jin().get("command")); creds = cur_device()
            out = device.run(creds, c)
        except Exception as e:
            return bad(e)
        db.audit(u, creds["host"], c, out)
        return {"output": out}

    @cherrypy.expose
    @cherrypy.tools.json_in()
    @cherrypy.tools.json_out()
    def maint(self):
        u = auth(); a = jin().get("action")
        try:
            creds = cur_device()
            if a == "save_config":
                cfg = device.running_config(creds)
                db.audit(u, creds["host"], "exported the running configuration.")
                return {"filename": f"{creds['name']}-{time.strftime('%Y%m%d-%H%M%S')}.cfg", "config": cfg}
            if a in ("backup", "nvram"):
                bid = db.save_backup(creds["id"], device.running_config(creds))   # SRS 5.2: backup always precedes a save
                msg = f"Backup #{bid} stored."
                db.audit(u, creds["host"], "backed up the running configuration.")
                if a == "nvram":
                    out = device.write_memory(creds)
                    db.audit(u, creds["host"], "write memory", out)
                    msg += "\n" + out
                return {"message": msg}
        except Exception as e:
            return bad(e)
        return bad("Unknown action")

    @cherrypy.expose
    @cherrypy.tools.json_out()
    def audit(self):
        auth()
        return [dict(r, at=str(r["at"])[:19]) for r in db.audit_list()]

    @cherrypy.expose
    @cherrypy.tools.json_in()
    @cherrypy.tools.json_out()
    def audit_clear(self):
        u = auth()
        if cherrypy.request.method != "POST":
            return bad("POST required", 405)
        db.audit_clear(); db.audit(u, "", "cleared the audit log.")
        return {"ok": True}


class App:
    api = Api()

    def _page(self, name):
        if not cherrypy.session.get("user"):
            raise cherrypy.HTTPRedirect("/login")
        return shell(name)

    @cherrypy.expose
    def index(self): return self._page("general")

    @cherrypy.expose
    def configure(self): return self._page("configure")

    @cherrypy.expose
    def devices(self): return self._page("devices")

    @cherrypy.expose
    def logs(self): return self._page("logs")

    @cherrypy.expose
    def login(self, username=None, password=None, remember=None):
        msg, ip = "", cherrypy.request.remote.ip
        if cherrypy.request.method == "POST":
            n, t = _fails.get(ip, (0, 0))
            if n >= 5 and time.time() - t < 300:
                msg = '<p class="err">Too many attempts. Try again in a few minutes.</p>'
            elif db.check_login(username or "", password or ""):
                _fails.pop(ip, None)
                cherrypy.session.regenerate()
                cherrypy.session["user"] = username
                if remember:
                    cherrypy.session.timeout = 60 * 24 * 30
                db.audit(username, ip, "Logged in the system.")
                raise cherrypy.HTTPRedirect("/")
            else:
                _fails[ip] = (n + 1, time.time())
                msg = '<p class="err">Invalid credentials.</p>'
        return LOGIN % msg

    @cherrypy.expose
    def logout(self):
        u = cherrypy.session.get("user")
        if u:
            db.audit(u, cherrypy.request.remote.ip, "Logged out.")
        cherrypy.lib.sessions.expire()
        raise cherrypy.HTTPRedirect("/login")


CONF = {"/": {"tools.sessions.on": True, "tools.sessions.timeout": 60, "tools.sessions.httponly": True,
              "tools.staticdir.root": HERE},
        "/static": {"tools.staticdir.on": True, "tools.staticdir.dir": "static", "tools.sessions.on": False}}


def _seed_demo_device():
    """DSA_MOCK: pre-register a simulated switch so no SSH connect is needed."""
    try:
        if db.devices():
            return
        db.upsert_device("Default-Network", "10.0.0.1", DEFAULT_USER(), "mock", "mock", "core-switch-01",
                         {"platform": "Cisco C9300-24T", "version": "17.06.03", "mgmt_if": "GigabitEthernet0/1"})
        print("DSA_MOCK: seeded simulated device core-switch-01 (10.0.0.1)")
    except Exception as e:
        print("DSA_MOCK: seed skipped:", e)


def main():
    for _ in range(30):
        try:
            db.init(); break
        except Exception as e:
            print("waiting for database:", e); time.sleep(2)
    if device.MOCK:
        _seed_demo_device()
    cherrypy.config.update({"server.socket_host": "0.0.0.0", "server.socket_port": int(os.environ.get("PORT", 8080)), "server.thread_pool": 20})
    cherrypy.quickstart(App(), "/", CONF)


if __name__ == "__main__":
    main()
