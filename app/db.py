import base64, hashlib, hmac, os, re, sqlite3
from cryptography.fernet import Fernet

URL = lambda: os.environ["DATABASE_URL"]
SQLITE = lambda: URL().startswith("sqlite")

SCHEMA = """
CREATE TABLE IF NOT EXISTS tbl_users(id SERIAL PRIMARY KEY, username TEXT UNIQUE NOT NULL, email TEXT DEFAULT '',
  pw_salt TEXT NOT NULL, pw_hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tbl_devices(id SERIAL PRIMARY KEY, network TEXT NOT NULL DEFAULT 'Default-Network',
  name TEXT NOT NULL, host TEXT UNIQUE NOT NULL, username TEXT NOT NULL, password_enc TEXT NOT NULL, secret_enc TEXT,
  device_type TEXT DEFAULT 'cisco_ios', platform TEXT DEFAULT '', version TEXT DEFAULT '', mgmt_if TEXT DEFAULT '',
  status TEXT DEFAULT 'Down', last_check TIMESTAMPTZ);
CREATE TABLE IF NOT EXISTS tbl_backups(id SERIAL PRIMARY KEY, device_id INT REFERENCES tbl_devices(id) ON DELETE CASCADE,
  taken_at TIMESTAMPTZ DEFAULT now(), config TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tbl_audit(id SERIAL PRIMARY KEY, at TIMESTAMPTZ DEFAULT now(), username TEXT,
  device_host TEXT, action TEXT, response TEXT);
CREATE TABLE IF NOT EXISTS tbl_settings(key TEXT PRIMARY KEY, value TEXT);
"""


class _Conn:
    """Tiny shim so the same %s SQL runs on PostgreSQL (production) and SQLite (dev/tests)."""
    def __enter__(self):
        if SQLITE():
            self.c = sqlite3.connect(URL().split("///", 1)[1])
            self.c.row_factory = sqlite3.Row
        else:
            import psycopg2, psycopg2.extras
            self.c = psycopg2.connect(URL(), cursor_factory=psycopg2.extras.RealDictCursor)
        return self

    def __exit__(self, *a):
        (self.c.rollback if a[0] else self.c.commit)()
        self.c.close()

    def q(self, sql, args=()):
        if SQLITE():
            sql = sql.replace("%s", "?").replace("now()", "CURRENT_TIMESTAMP")
            cur = self.c.execute(sql, args)
            return [dict(r) for r in cur.fetchall()] if cur.description else []
        cur = self.c.cursor()
        cur.execute(sql, args)
        return [dict(r) for r in cur.fetchall()] if cur.description else []


def _fernet():
    key = os.environ.get("SECRET_KEY", "dev")
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest()))


def _hash(pw, salt):
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), 200_000).hex()


def init():
    with _Conn() as c:
        s = SCHEMA
        if SQLITE():
            s = s.replace("SERIAL PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT").replace("TIMESTAMPTZ DEFAULT now()", "TEXT DEFAULT CURRENT_TIMESTAMP").replace("TIMESTAMPTZ", "TEXT")
            for stmt in filter(str.strip, s.split(";")):
                c.q(stmt)
        else:
            c.q(s)
        u, p = os.environ.get("ADMIN_USER"), os.environ.get("ADMIN_PASSWORD")
        if u and p and not c.q("SELECT 1 FROM tbl_users WHERE username=%s", (u,)):
            salt = os.urandom(16).hex()
            c.q("INSERT INTO tbl_users(username,pw_salt,pw_hash) VALUES(%s,%s,%s)", (u, salt, _hash(p, salt)))


# ---- users -------------------------------------------------------------
def check_login(user, pw):
    with _Conn() as c:
        r = c.q("SELECT * FROM tbl_users WHERE username=%s", (user,))
    return bool(r) and hmac.compare_digest(r[0]["pw_hash"], _hash(pw, r[0]["pw_salt"]))


def get_user(user):
    with _Conn() as c:
        r = c.q("SELECT username,email FROM tbl_users WHERE username=%s", (user,))
    return r[0] if r else None


def update_profile(old, username, email, password=None):
    with _Conn() as c:
        c.q("UPDATE tbl_users SET username=%s,email=%s WHERE username=%s", (username, email, old))
        if password:
            salt = os.urandom(16).hex()
            c.q("UPDATE tbl_users SET pw_salt=%s,pw_hash=%s WHERE username=%s", (salt, _hash(password, salt), username))


# ---- devices -----------------------------------------------------------
def upsert_device(network, host, user, pw, secret, name, facts):
    f = _fernet()
    with _Conn() as c:
        c.q("INSERT INTO tbl_devices(network,name,host,username,password_enc,secret_enc,platform,version,mgmt_if,status,last_check)"
            " VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,'Up',now()) ON CONFLICT(host) DO UPDATE SET network=EXCLUDED.network,"
            " name=EXCLUDED.name, username=EXCLUDED.username, password_enc=EXCLUDED.password_enc, secret_enc=EXCLUDED.secret_enc,"
            " platform=EXCLUDED.platform, version=EXCLUDED.version, mgmt_if=EXCLUDED.mgmt_if, status='Up', last_check=now()",
            (network, name, host, user, f.encrypt(pw.encode()).decode(), f.encrypt(secret.encode()).decode() if secret else None,
             facts.get("platform", ""), facts.get("version", ""), facts.get("mgmt_if", "")))
        return c.q("SELECT id FROM tbl_devices WHERE host=%s", (host,))[0]["id"]


def devices(network=None):
    with _Conn() as c:
        if network:
            return c.q("SELECT id,network,name,host,username,platform,version,mgmt_if,status,last_check FROM tbl_devices WHERE network=%s ORDER BY name", (network,))
        return c.q("SELECT id,network,name,host,username,platform,version,mgmt_if,status,last_check FROM tbl_devices ORDER BY name")


def networks():
    with _Conn() as c:
        return [r["network"] for r in c.q("SELECT DISTINCT network FROM tbl_devices ORDER BY network")]


def device_by_host(host):
    with _Conn() as c:
        r = c.q("SELECT id,username FROM tbl_devices WHERE host=%s", (host,))
    return r[0] if r else None


def set_status(dev_id, status, facts=None):
    with _Conn() as c:
        c.q("UPDATE tbl_devices SET status=%s,last_check=now() WHERE id=%s", (status, dev_id))
        if facts:
            c.q("UPDATE tbl_devices SET name=%s,platform=%s,version=%s,mgmt_if=%s WHERE id=%s",
                (facts["hostname"], facts["platform"], facts["version"], facts["mgmt_if"], dev_id))


def delete_device(dev_id):
    with _Conn() as c:
        c.q("DELETE FROM tbl_backups WHERE device_id=%s", (dev_id,))
        c.q("DELETE FROM tbl_devices WHERE id=%s", (dev_id,))


def device_creds(dev_id):
    with _Conn() as c:
        r = c.q("SELECT * FROM tbl_devices WHERE id=%s", (dev_id,))
    if not r:
        raise ValueError("No device selected. Connect to a device on the General page first.")
    r, f = r[0], _fernet()
    return {"id": r["id"], "name": r["name"], "device_type": r["device_type"], "host": r["host"], "username": r["username"],
            "password": f.decrypt(r["password_enc"].encode()).decode(),
            "secret": f.decrypt(r["secret_enc"].encode()).decode() if r["secret_enc"] else ""}


# ---- backups / audit / settings ---------------------------------------
def save_backup(dev_id, config):
    with _Conn() as c:
        c.q("INSERT INTO tbl_backups(device_id,config) VALUES(%s,%s)", (dev_id, config))
        return c.q("SELECT max(id) AS i FROM tbl_backups WHERE device_id=%s", (dev_id,))[0]["i"]


def audit(user, host, action, response=""):
    with _Conn() as c:
        c.q("INSERT INTO tbl_audit(username,device_host,action,response) VALUES(%s,%s,%s,%s)", (user, host, action, response[:4000]))


def audit_list():
    with _Conn() as c:
        return c.q("SELECT at,device_host,username,action FROM tbl_audit ORDER BY id DESC LIMIT 500")


def audit_clear():
    with _Conn() as c:
        c.q("DELETE FROM tbl_audit")


def setting(key, default=""):
    with _Conn() as c:
        r = c.q("SELECT value FROM tbl_settings WHERE key=%s", (key,))
    return r[0]["value"] if r else default


def set_setting(key, value):
    with _Conn() as c:
        c.q("INSERT INTO tbl_settings(key,value) VALUES(%s,%s) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value", (key, value))
