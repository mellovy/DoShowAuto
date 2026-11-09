"""Pure functions that turn form input into Cisco IOS command lists (Sprint 1)."""
import ipaddress
import re

_NAME = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,61}[A-Za-z0-9])?$")
_HOSTNAME = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
_IFACE = re.compile(r"^([A-Za-z][A-Za-z-]*)\s?(\d+(?:/\d+)*(?:\.\d+)?)$")

# IOS interface types as canonical (lowercase, hyphen-stripped) names. An
# abbreviation is accepted when it is a prefix of one of these, matching how
# IOS itself resolves short interface names (Gi, Fa, Te, Po, ...).
_IFACE_TYPES = (
    "ethernet", "fastethernet", "gigabitethernet", "tengigabitethernet",
    "twentyfivegige", "fortygige", "fortygigabitethernet", "hundredgige",
    "twogigabitethernet", "portchannel", "loopback", "vlan", "tunnel",
    "serial", "bvi", "dialer", "async", "virtualtemplate", "virtualaccess",
    "nve", "mgmt",
)


def _name(v, what, maxlen=63):
    v = v or ""
    if len(v) > maxlen or not _NAME.match(v):
        raise ValueError(
            f"Invalid {what}: {v!r} (1-{maxlen} chars, letters/digits/._-, "
            "must start and end with a letter or digit)")
    return v


def _hostname(v):
    if not _HOSTNAME.match(v or ""):
        raise ValueError(
            f"Invalid hostname: {v!r} (1-63 chars, letters/digits/hyphens, "
            "must start and end with a letter or digit)")
    return v


def _iface(v):
    s = (v or "").strip()
    m = _IFACE.match(s)
    if not m:
        raise ValueError(
            f"Invalid interface: {v!r} (expected e.g. GigabitEthernet0/1 or Gi0/1)")
    kind = m.group(1).lower().replace("-", "")
    if len(kind) < 2 or not any(t.startswith(kind) for t in _IFACE_TYPES):
        raise ValueError(
            f"Unknown interface type {m.group(1)!r}: use e.g. GigabitEthernet0/1, "
            "Gi0/1, FastEthernet0/0, TenGigabitEthernet1/1, Port-channel1")
    return s


def _vlan(v):
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise ValueError(f"Invalid VLAN ID {v!r}: must be a number 1-4094")
    if not 1 <= n <= 4094:
        raise ValueError(f"Invalid VLAN ID {n}: must be 1-4094")
    return n


def _banner_text(t):
    if not t or not str(t).strip():
        raise ValueError("Banner text must not be empty")
    if "^" in t:
        raise ValueError("Banner text must not contain '^' (the banner delimiter)")
    return t


def _ip(v, what="IP address"):
    try:
        return str(ipaddress.IPv4Address(str(v).strip()))
    except (ipaddress.AddressValueError, ValueError):
        raise ValueError(f"Invalid {what} {v!r}: expected dotted-quad, e.g. 192.168.1.1")


def _mask(m):
    """Validate a subnet mask (dotted or prefix) and return the dotted form."""
    try:
        return str(ipaddress.IPv4Network(f"0.0.0.0/{str(m).strip()}").netmask)
    except ValueError:
        raise ValueError(
            f"Invalid subnet mask {m!r}: expected a contiguous mask or prefix length, "
            "e.g. 255.255.255.0 or 24")


def _net(ip, mask):
    try:
        n = ipaddress.IPv4Network(f"{str(ip).strip()}/{str(mask).strip()}", strict=False)
    except ValueError:
        raise ValueError(
            f"Invalid network/mask {ip!r}/{mask!r}: network must be a valid IPv4 "
            "address and mask a contiguous subnet mask (e.g. 255.255.255.0)")
    return str(n.network_address), str(n.netmask)


# ---- Access & Security -------------------------------------------------
def hostname(name):
    return [f"hostname {_hostname(name)}"]


def enable_secret(secret):
    if len(secret or "") < 8:
        raise ValueError("Enable secret must be at least 8 characters")
    return [f"enable secret {secret}"]


def ssh_setup(domain, username, password, key_bits=2048):
    _name(domain, "domain name")
    _name(username, "username")
    if len(password or "") < 8:
        raise ValueError("SSH password must be at least 8 characters")
    try:
        bits = int(key_bits)
    except (TypeError, ValueError):
        raise ValueError(f"Invalid RSA key size {key_bits!r}: must be 1024, 2048 or 4096")
    if bits not in (1024, 2048, 4096):
        raise ValueError(f"Invalid RSA key size {bits}: must be 1024, 2048 or 4096")
    return [f"ip domain-name {domain}", f"crypto key generate rsa modulus {bits}",
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
        cmds.append(f"name {_name(name, 'VLAN name', 32)}")
    return cmds


def access_port(interface, vlan_id):
    return [f"interface {_iface(interface)}", "switchport mode access",
            f"switchport access vlan {_vlan(vlan_id)}"]


def _vlan_list(s):
    """Normalise an allowed-VLAN list, preserving IOS ranges (10,20-30)."""
    out = []
    for part in re.split(r"[,\s]+", str(s or "").strip()):
        if not part:
            continue
        if "-" in part:
            a, _, b = part.partition("-")
            lo, hi = _vlan(a), _vlan(b)
            if lo >= hi:
                raise ValueError(f"Invalid VLAN range {part!r}: start must be below end")
            out.append(f"{lo}-{hi}")
        else:
            out.append(str(_vlan(part)))
    if not out:
        raise ValueError("Allowed VLAN list must not be empty")
    return ",".join(out)


def trunk(interface, allowed=None, native=None):
    cmds = [f"interface {_iface(interface)}", "switchport mode trunk"]
    if allowed:
        cmds.append(f"switchport trunk allowed vlan {_vlan_list(allowed)}")
    if native:
        cmds.append(f"switchport trunk native vlan {_vlan(native)}")
    return cmds


def static_route(network, mask, next_hop):
    net, m = _net(network, mask)
    return [f"ip route {net} {m} {_ip(next_hop, 'next hop')}"]


def interface_ip(interface, ip, mask, enable=True, description=None):
    addr = _ip(ip)
    m = _mask(mask)
    cmds = [f"interface {_iface(interface)}"]
    if description:
        cmds.append(f"description {_name(description.replace(' ', '_'), 'description')}")
    cmds += [f"ip address {addr} {m}", "no shutdown" if enable else "shutdown"]
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
        raise ValueError(f"Invalid network {s!r}: expected CIDR or network/mask, e.g. 10.0.0.0/24")


def _text(v, what, n=200):
    v = (v or "").strip()
    if len(v) > n or "\n" in v or "\r" in v:
        raise ValueError(f"Invalid {what}: max {n} chars, no line breaks")
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
            raise ValueError("Subnet mask is required when a static IP is given")
        cmds.append(f"ip address {_ip(ip)} {_mask(mask)}")
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
        s = ipaddress.IPv4Address(_ip(start_ip, "starting IP"))
        if s not in n:
            raise ValueError(f"Starting IP {s} is outside the assigned network {n}")
        if s > first:
            cmds.append(f"ip dhcp excluded-address {first} {s - 1}")
    cmds += [f"ip dhcp pool {_name(name, 'pool name')}", f"network {n.network_address} {n.netmask}"]
    if gateway:
        cmds.append(f"default-router {_ip(gateway, 'default gateway')}")
    servers = [x for x in re.split(r"[\s,]+", dns or "") if x]
    if servers:
        cmds.append("dns-server " + " ".join(_ip(x, "DNS server") for x in servers))
    d, h, m = int(lease_days), int(lease_hours), int(lease_minutes)
    if not (0 <= d <= 365 and 0 <= h <= 23 and 0 <= m <= 59) or d + h + m == 0:
        raise ValueError(
            f"Invalid lease time {d}d {h}h {m}m: days 0-365, hours 0-23, "
            "minutes 0-59 and not all zero")
    cmds.append(f"lease {d} {h} {m}")
    return cmds


def _classful(n):
    a = int(str(n.network_address).split(".")[0])
    return ipaddress.IPv4Network(f"{n.network_address}/{8 if a < 128 else 16 if a < 192 else 24}", strict=False).network_address


def _area(a):
    s = str(a).strip()
    try:
        if "." in s:
            parts = s.split(".")
            if len(parts) != 4:
                raise ValueError
            octs = [int(p) for p in parts]
            if any(not 0 <= o <= 255 for o in octs):
                raise ValueError
            val = (octs[0] << 24) | (octs[1] << 16) | (octs[2] << 8) | octs[3]
        else:
            val = int(s)
    except (TypeError, ValueError):
        raise ValueError(f"Invalid OSPF area {a!r}: use 0-4294967295 or dotted form 0.0.0.0")
    if not 0 <= val <= 4294967295:
        raise ValueError(f"Invalid OSPF area {a!r}: must be 0-4294967295")
    return val


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
    try:
        pid = int(process_id)
    except (TypeError, ValueError):
        raise ValueError(f"Invalid process ID / AS {process_id!r}: must be an integer 1-65535")
    if not 1 <= pid <= 65535:
        raise ValueError(f"Invalid process ID / AS {pid}: must be 1-65535")
    if protocol == "ospf":
        a = _area(area)
        return [f"router ospf {pid}"] + [f"network {n.network_address} {_wild(n.netmask)} area {a}" for n in nets]
    if protocol == "eigrp":
        return [f"router eigrp {pid}"] + [f"network {n.network_address} {_wild(n.netmask)}" for n in nets]
    raise ValueError(f"Invalid routing protocol {protocol!r}: must be OSPF, EIGRP or RIP")


_PO_MODES = {"lacp": ("active", "passive"), "pagp": ("desirable", "auto"), "static": ("on",)}


def etherchannel(group, protocol, interfaces, mode=None, description=None):
    try:
        g = int(group)
    except (TypeError, ValueError):
        raise ValueError(f"Invalid channel group {group!r}: must be an integer 1-48")
    if not 1 <= g <= 48:
        raise ValueError(f"Invalid channel group {g}: must be 1-48")
    protocol = (protocol or "lacp").lower()
    if protocol not in _PO_MODES:
        raise ValueError(f"Invalid protocol {protocol!r}: must be LACP, PAgP or Static")
    mode = (mode or _PO_MODES[protocol][0]).lower()
    if mode not in _PO_MODES[protocol]:
        raise ValueError(
            f"Invalid mode {mode!r} for {protocol.upper()}: must be one of {', '.join(_PO_MODES[protocol])}")
    ifs = [_iface(i) for i in (interfaces if isinstance(interfaces, list) else str(interfaces).split(",")) if str(i).strip()]
    if len(ifs) < 2:
        raise ValueError("EtherChannel needs at least 2 member interfaces")
    out = []
    for i in ifs:
        out += [f"interface {i}", f"channel-group {g} mode {mode}"]
    if description:
        out += [f"interface port-channel {g}", f"description {_text(description, 'description')}"]
    return out


def port_security(interfaces, enabled=True, max_mac=1, violation="shutdown", sticky=True):
    ifs = [_iface(i) for i in (interfaces if isinstance(interfaces, list) else str(interfaces).split(",")) if str(i).strip()]
    if not ifs:
        raise ValueError("Select at least one interface")
    if enabled and violation not in ("shutdown", "restrict", "protect"):
        raise ValueError(f"Invalid violation mode {violation!r}: must be shutdown, restrict or protect")
    out = []
    if enabled:
        try:
            mm = int(max_mac)
        except (TypeError, ValueError):
            raise ValueError(f"Invalid max MAC count {max_mac!r}: must be an integer 1-8192")
        if not 1 <= mm <= 8192:
            raise ValueError(f"Invalid max MAC count {mm}: must be 1-8192")
    for i in ifs:
        out.append(f"interface {i}")
        if not enabled:
            out.append("no switchport port-security")
            continue
        out += ["switchport mode access", "switchport port-security",
                f"switchport port-security maximum {mm}",
                f"switchport port-security violation {violation}",
                "switchport port-security mac-address sticky" if sticky else "no switchport port-security mac-address sticky"]
    return out
