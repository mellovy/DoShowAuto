"""Pure functions that turn form input into Cisco IOS command lists (Sprint 1)."""
import ipaddress
import re

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$")
_IFACE = re.compile(r"^[A-Za-z]+[A-Za-z-]*\s?\d+(/\d+)*(\.\d+)?$")


def _name(v, what):
    if not _NAME.match(v or ""):
        raise ValueError(f"Invalid {what}: {v!r}")
    return v


def _iface(v):
    if not _IFACE.match((v or "").strip()):
        raise ValueError(f"Invalid interface: {v!r}")
    return v.strip()


def _vlan(v):
    v = int(v)
    if not 1 <= v <= 4094:
        raise ValueError("VLAN ID must be 1-4094")
    return v


def _banner_text(t):
    if not t or "^" in t:
        raise ValueError("Banner text is empty or contains '^'")
    return t


def _ip(v):
    return str(ipaddress.IPv4Address(v))


def _net(ip, mask):
    n = ipaddress.IPv4Network(f"{ip}/{mask}", strict=False)
    return str(n.network_address), str(n.netmask)


# ---- Access & Security -------------------------------------------------
def hostname(name):
    return [f"hostname {_name(name, 'hostname')}"]


def enable_secret(secret):
    if len(secret or "") < 8:
        raise ValueError("Enable secret must be at least 8 characters")
    return [f"enable secret {secret}"]


def ssh_setup(domain, username, password, key_bits=2048):
    _name(domain, "domain name")
    _name(username, "username")
    if len(password or "") < 8:
        raise ValueError("SSH password must be at least 8 characters")
    if int(key_bits) not in (1024, 2048, 4096):
        raise ValueError("Key size must be 1024, 2048 or 4096")
    return [f"ip domain-name {domain}", f"crypto key generate rsa modulus {int(key_bits)}",
            "ip ssh version 2", f"username {username} privilege 15 secret {password}",
            "line vty 0 4", "transport input ssh", "login local"]


def banner(motd=None, login=None):
    cmds = []
    if motd:
        cmds.append(f"banner motd ^{_banner_text(motd)}^")
    if login:
        cmds.append(f"banner login ^{_banner_text(login)}^")
    if not cmds:
        raise ValueError("Provide a MOTD or login banner")
    return cmds




# ---- Network Configuration --------------------------------------------
def vlan(vlan_id, name=None):
    cmds = [f"vlan {_vlan(vlan_id)}"]
    if name:
        cmds.append(f"name {_name(name, 'VLAN name')}")
    return cmds


def access_port(interface, vlan_id):
    return [f"interface {_iface(interface)}", "switchport mode access",
            f"switchport access vlan {_vlan(vlan_id)}"]


def trunk(interface, allowed=None, native=None):
    cmds = [f"interface {_iface(interface)}", "switchport mode trunk"]
    if allowed:
        ids = ",".join(str(_vlan(x)) for x in str(allowed).replace(" ", "").split(",") if x)
        cmds.append(f"switchport trunk allowed vlan {ids}")
    if native:
        cmds.append(f"switchport trunk native vlan {_vlan(native)}")
    return cmds


def static_route(network, mask, next_hop):
    net, m = _net(network, mask)
    return [f"ip route {net} {m} {_ip(next_hop)}"]


def interface_ip(interface, ip, mask, enable=True, description=None):
    addr = _ip(ip)
    ipaddress.IPv4Network(f"{addr}/{mask}", strict=False)
    cmds = [f"interface {_iface(interface)}"]
    if description:
        cmds.append(f"description {_name(description.replace(' ', '_'), 'description')}")
    cmds += [f"ip address {addr} {ipaddress.IPv4Network(f'0.0.0.0/{mask}').netmask}",
             "no shutdown" if enable else "shutdown"]
    return cmds






# ---- Device Ops --------------------------------------------------------
SAFE_SHOW = re.compile(r"^show\s+[A-Za-z0-9 _./|-]+$")


def show(cmd):
    cmd = " ".join((cmd or "").split())
    if not SAFE_SHOW.match(cmd):
        raise ValueError("Only 'show ...' commands are allowed")
    return cmd


# ---- UI-driven generators (match the SRS screens) -----------------------
def _wild(mask):
    return str(ipaddress.IPv4Network(f"0.0.0.0/{mask}").hostmask)


def _cidr(s):
    try:
        return ipaddress.IPv4Network(str(s).strip(), strict=False)
    except ValueError:
        raise ValueError(f"Invalid network: {s!r}")


def _text(v, what, n=200):
    v = (v or "").strip()
    if len(v) > n or "\n" in v or "\r" in v:
        raise ValueError(f"Invalid {what}")
    return v


def basic_config(hostname=None, banner_text=None, enable_secret_key=None, encryption=False):
    cmds = []
    if hostname:
        cmds += globals()["hostname"](hostname)
    if banner_text:
        cmds += banner(login=_text(banner_text, "banner", 500))
    if enable_secret_key:
        cmds += enable_secret(enable_secret_key)
    if encryption:
        cmds.append("service password-encryption")
    if not cmds:
        raise ValueError("Nothing to configure")
    return cmds


def interface_config(interface, assignment="static", ip=None, mask=None, description=None,
                     vlan_id=None, trunk=False, enabled=None):
    cmds = [f"interface {_iface(interface)}"]
    if description is not None and description != "":
        cmds.append(f"description {_text(description, 'description', 200)}")
    if assignment == "dhcp":
        cmds.append("ip address dhcp")
    elif ip:
        if not mask:
            raise ValueError("Subnet mask required")
        _net(ip, mask)
        cmds.append(f"ip address {_ip(ip)} {ipaddress.IPv4Network(f'0.0.0.0/{mask}').netmask}")
    if trunk:
        cmds.append("switchport mode trunk")
    elif vlan_id not in (None, ""):
        cmds += ["switchport mode access", f"switchport access vlan {_vlan(vlan_id)}"]
    if enabled is True:
        cmds.append("no shutdown")
    elif enabled is False:
        cmds.append("shutdown")
    if len(cmds) == 1:
        raise ValueError("Nothing to configure")
    return cmds


def dhcp_pool(name, network, mask=None, gateway=None, dns=None, start_ip=None,
              lease_days=1, lease_hours=0, lease_minutes=0):
    n = _cidr(f"{network}/{mask}") if mask else _cidr(network)
    cmds = []
    first = n.network_address + 1
    if start_ip:
        s = ipaddress.IPv4Address(start_ip)
        if s not in n:
            raise ValueError("Starting IP is outside the assigned network")
        if s > first:
            cmds.append(f"ip dhcp excluded-address {first} {s - 1}")
    cmds += [f"ip dhcp pool {_name(name, 'pool name')}", f"network {n.network_address} {n.netmask}"]
    if gateway:
        cmds.append(f"default-router {_ip(gateway)}")
    servers = [x for x in re.split(r"[\s,]+", dns or "") if x]
    if servers:
        cmds.append("dns-server " + " ".join(_ip(x) for x in servers))
    d, h, m = int(lease_days), int(lease_hours), int(lease_minutes)
    if not (0 <= d <= 365 and 0 <= h <= 23 and 0 <= m <= 59) or d + h + m == 0:
        raise ValueError("Invalid lease time")
    cmds.append(f"lease {d} {h} {m}")
    return cmds


def _classful(n):
    a = int(str(n.network_address).split(".")[0])
    return ipaddress.IPv4Network(f"{n.network_address}/{8 if a < 128 else 16 if a < 192 else 24}", strict=False).network_address


def dynamic_routing(protocol, process_id, networks, area=0):
    nets = [_cidr(x) for x in re.split(r"[\n,]+", networks or "") if x.strip()]
    if not nets:
        raise ValueError("At least one network to advertise is required")
    protocol = (protocol or "").lower()
    if protocol == "rip":
        out = ["router rip", "version 2", "no auto-summary"]
        for a in sorted({str(_classful(n)) for n in nets}):
            out.append(f"network {a}")
        return out
    pid = int(process_id)
    if not 1 <= pid <= 65535:
        raise ValueError("Process ID / AS must be 1-65535")
    if protocol == "ospf":
        return [f"router ospf {pid}"] + [f"network {n.network_address} {_wild(n.netmask)} area {int(area)}" for n in nets]
    if protocol == "eigrp":
        return [f"router eigrp {pid}"] + [f"network {n.network_address} {_wild(n.netmask)}" for n in nets]
    raise ValueError("Protocol must be OSPF, EIGRP or RIP")


_PO_MODES = {"lacp": ("active", "passive"), "pagp": ("desirable", "auto"), "static": ("on",)}


def etherchannel(group, protocol, interfaces, mode=None, description=None):
    if not 1 <= int(group) <= 64:
        raise ValueError("Group must be 1-64")
    protocol = (protocol or "lacp").lower()
    if protocol not in _PO_MODES:
        raise ValueError("Protocol must be LACP, PAgP or Static")
    mode = (mode or _PO_MODES[protocol][0]).lower()
    if mode not in _PO_MODES[protocol]:
        raise ValueError(f"Mode for {protocol.upper()} must be one of {_PO_MODES[protocol]}")
    ifs = [_iface(i) for i in (interfaces if isinstance(interfaces, list) else str(interfaces).split(",")) if str(i).strip()]
    if len(ifs) < 2:
        raise ValueError("EtherChannel needs at least 2 member interfaces")
    out = []
    for i in ifs:
        out += [f"interface {i}", f"channel-group {int(group)} mode {mode}"]
    if description:
        out += [f"interface port-channel {int(group)}", f"description {_text(description, 'description')}"]
    return out


def port_security(interfaces, enabled=True, max_mac=1, violation="shutdown", sticky=True):
    ifs = [_iface(i) for i in (interfaces if isinstance(interfaces, list) else str(interfaces).split(",")) if str(i).strip()]
    if not ifs:
        raise ValueError("Select at least one interface")
    if enabled and violation not in ("shutdown", "restrict", "protect"):
        raise ValueError("Violation must be shutdown, restrict or protect")
    if enabled and not 1 <= int(max_mac) <= 4097:
        raise ValueError("Max MAC must be 1-4097")
    out = []
    for i in ifs:
        out.append(f"interface {i}")
        if not enabled:
            out.append("no switchport port-security")
            continue
        out += ["switchport mode access", "switchport port-security",
                f"switchport port-security maximum {int(max_mac)}",
                f"switchport port-security violation {violation}",
                "switchport port-security mac-address sticky" if sticky else "no switchport port-security mac-address sticky"]
    return out
