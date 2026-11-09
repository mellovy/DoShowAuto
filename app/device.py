"""Netmiko SSHv2 execution layer (port 22 only). DSA_MOCK=1 swaps in a fake switch for UI work."""
import os
import re
from contextlib import contextmanager

# Case/format tolerant: Linux containers are case-sensitive, so accept dsa_mock too.
MOCK = (os.environ.get("DSA_MOCK") or os.environ.get("dsa_mock") or "").strip().lower() in ("1", "true", "yes", "on")

if not MOCK:
    from netmiko import ConnectHandler

MOCK_CFG = """hostname core-switch-01
!
ip dhcp excluded-address 192.168.10.1 192.168.10.9
ip dhcp excluded-address 10.50.0.1 10.50.0.99
!
ip dhcp pool POOL_VLAN_10
 network 192.168.10.0 255.255.255.0
 default-router 192.168.10.1
 dns-server 8.8.8.8
 lease 1 0 0
ip dhcp pool POOL_GUEST_WIFI
 network 10.50.0.0 255.255.252.0
 default-router 10.50.0.1
 dns-server 8.8.8.8 8.8.4.4
 lease 0 24 0
!
interface GigabitEthernet0/1
 description Uplink to Core-02
 ip address 10.0.1.1 255.255.255.252
 switchport mode trunk
 switchport port-security
 switchport port-security maximum 2
 switchport port-security violation shutdown
 switchport port-security mac-address sticky
 channel-group 1 mode active
!
interface GigabitEthernet0/2
 description Server_RACK_A1
 ip address 192.168.10.1 255.255.255.0
 switchport access vlan 10
 switchport port-security
 switchport port-security violation restrict
 channel-group 1 mode active
!
interface GigabitEthernet0/3
 ip address dhcp
 shutdown
!
interface GigabitEthernet0/4
 description Wi-Fi AP Office
 ip address 192.168.20.5 255.255.255.0
 switchport access vlan 20
 switchport port-security
 switchport port-security maximum 5
 switchport port-security violation protect
!
router ospf 100
 network 10.0.0.0 0.0.0.255 area 0
router rip
 network 10.0.0.0
router eigrp 100
 network 192.168.10.0 0.0.0.255
ip route 10.0.0.0 255.255.0.0 10.1.1.1
"""
MOCK_OUT = {
    "show ip interface brief": "Interface IP-Address OK? Method Status Protocol\nGigabitEthernet0/1 10.0.1.1 YES manual up up\nGigabitEthernet0/2 192.168.10.1 YES manual up up\nGigabitEthernet0/3 unassigned YES DHCP administratively down down\nGigabitEthernet0/4 192.168.20.5 YES manual up up\n",
    "show vlan brief": "VLAN Name Status Ports\n---- ---- ------ -----\n1    default active Gi0/3\n10   MANAGEMENT active Gi0/2\n20   VOICE_PROD active Gi0/4\n99   NATIVE_UNUSED active\n",
    "show etherchannel summary": "Group  Port-channel  Protocol    Ports\n------+-------------+-----------+-----------------------\n1      Po1(SU)         LACP      Gi0/1(P)    Gi0/2(P)\n",
    "show port-security": "Secure Port MaxSecureAddr CurrentAddr SecurityViolation Security Action\nGi0/1 2 1 0 Shutdown\nGi0/2 1 1 12 Restrict\n",
    "show ip dhcp pool": "Pool POOL_VLAN_10 :\n Total addresses : 240\n Leased addresses : 108\nPool POOL_GUEST_WIFI :\n Total addresses : 900\n Leased addresses : 828\n",
    "show version": "Cisco IOS Software, Version 17.06.03\ncisco C9300-24T (X86) processor\n",
}
_MOCK_APPLIED = []


class _Mock:
    def __init__(self, creds):
        self.creds = creds

    def send_config_set(self, cmds):
        _MOCK_APPLIED.extend(cmds)
        return "\n".join(f"{self.creds.get('host')}(config)#{c}" for c in cmds)

    def send_command(self, c, **_):
        if c == "show running-config":
            return MOCK_CFG
        return MOCK_OUT.get(c, f"(mock) {c}\n")

    def save_config(self):
        return "Building configuration...\n[OK]"

    def enable(self):
        pass


@contextmanager
def session(creds):
    if MOCK:
        yield _Mock(creds)
        return
    c = ConnectHandler(device_type=creds["device_type"], host=creds["host"], username=creds["username"],
                       password=creds["password"], secret=creds["secret"], port=22, conn_timeout=15)
    try:
        if creds["secret"]:
            c.enable()
        yield c
    finally:
        c.disconnect()


def has_error(out):
    return bool(re.search(r"^\s*% ", out or "", re.M))


def push(creds, commands):
    with session(creds) as c:
        return c.send_config_set(commands)


def run(creds, command):
    with session(creds) as c:
        return c.send_command(command)


def running_config(creds):
    return run(creds, "show running-config")


def write_memory(creds):
    with session(creds) as c:
        return c.save_config()


def probe(creds):
    """Connectivity check plus the facts shown on the Devices page."""
    with session(creds) as c:
        ver = c.send_command("show version")
        brief = c.send_command("show ip interface brief")
        cfg = c.send_command("show running-config | include ^hostname")
    host = re.search(r"^hostname (\S+)", cfg or "", re.M) or re.search(r"^hostname (\S+)", MOCK_CFG if MOCK else "", re.M)
    plat = re.search(r"^cisco (\S+)", ver, re.M | re.I)
    vers = re.search(r"Version ([\w.()]+)", ver)
    mgmt = next((l.split()[0] for l in brief.splitlines() if l.split()[1:2] == [creds["host"]]), "")
    return {"hostname": host.group(1) if host else creds["host"], "platform": f"Cisco {plat.group(1)}" if plat else "Cisco IOS",
            "version": vers.group(1).rstrip(",") if vers else "", "mgmt_if": mgmt}


def inventory_raw(creds):
    with session(creds) as c:
        return {"cfg": c.send_command("show running-config"),
                "brief": c.send_command("show ip interface brief"),
                "vlan": c.send_command("show vlan brief"),
                "dhcp": c.send_command("show ip dhcp pool"),
                "ec": c.send_command("show etherchannel summary"),
                "ps": c.send_command("show port-security")}
