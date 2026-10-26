"""Turn raw IOS output into the inventories shown on the Configure screens."""
import ipaddress
import re

SHORT = [("TenGigabitEthernet", "Te"), ("GigabitEthernet", "Gi"), ("FastEthernet", "Fa"), ("Port-channel", "Po")]


def blocks(cfg):
    out, cur = [], None
    for line in cfg.splitlines():
        if not line.strip() or line.startswith("!"):
            cur = None
            continue
        if line[0] != " ":
            cur = {"head": line.strip(), "body": []}
            out.append(cur)
        elif cur is not None:
            cur["body"].append(line.strip())
    return out


def brief_status(brief):
    res = {}
    for l in (brief or "").splitlines():
        m = re.match(r"^(\S+)\s+(\S+)\s+\w+\s+\w+\s+(administratively down|up|down|\S+)\s+(up|down)\s*$", l)
        if m:
            res[m.group(1)] = {"ip": m.group(2), "up": m.group(3) == "up"}
    return res


def interfaces(cfg, brief=""):
    st = brief_status(brief)
    res = []
    for b in blocks(cfg):
        m = re.match(r"interface (\S+)$", b["head"])
        if not m:
            continue
        d = {"name": m.group(1), "description": "", "ip": "", "mask": "", "assignment": "Static", "vlan": "",
             "up": st.get(m.group(1), {}).get("up", True), "channel": None,
             "portsec": {"enabled": False, "max": 1, "violation": "shutdown", "sticky": False}}
        for l in b["body"]:
            if l.startswith("description "):
                d["description"] = l[12:]
            elif l == "ip address dhcp":
                d["assignment"] = "DHCP"
            elif re.match(r"ip address \S+ \S+$", l):
                _, _, d["ip"], d["mask"] = l.split()
            elif l == "shutdown":
                d["up"] = False
            elif l == "switchport mode trunk":
                d["vlan"] = "Trunk"
            elif l.startswith("switchport access vlan "):
                d["vlan"] = l.split()[-1]
            elif l == "switchport port-security":
                d["portsec"]["enabled"] = True
            elif l.startswith("switchport port-security maximum "):
                d["portsec"]["max"] = int(l.split()[-1])
            elif l.startswith("switchport port-security violation "):
                d["portsec"]["violation"] = l.split()[-1]
            elif l == "switchport port-security mac-address sticky":
                d["portsec"]["sticky"] = True
            elif (c := re.match(r"channel-group (\d+) mode (\S+)", l)):
                d["channel"] = {"group": int(c.group(1)), "mode": c.group(2)}
        if d["assignment"] == "DHCP" or d["ip"]:
            pass
        elif st.get(d["name"], {}).get("ip", "unassigned") not in ("unassigned", ""):
            d["ip"] = st[d["name"]]["ip"]
        res.append(d)
    return res


def vlans(show_vlan_brief):
    out = []
    for l in (show_vlan_brief or "").splitlines():
        m = re.match(r"^(\d+)\s+(\S+)\s+(active|act/unsup|suspended|act/lshut)\s*(.*)$", l)
        if m:
            out.append({"id": int(m.group(1)), "name": m.group(2), "ports": m.group(4).strip()})
        elif out and l.startswith(" ") and l.strip():
            out[-1]["ports"] += " " + l.strip()
    for v in out:
        v["active"] = bool(v["ports"]) or v["id"] == 1
    return out


def dhcp_pools(cfg, pool_out=""):
    leases = {}
    for m in re.finditer(r"Pool (\S+) :(.*?)(?=\nPool |\Z)", pool_out or "", re.S):
        t = re.search(r"Total addresses\s*:\s*(\d+)", m.group(2))
        u = re.search(r"Leased addresses\s*:\s*(\d+)", m.group(2))
        leases[m.group(1)] = (int(u.group(1)) if u else 0, int(t.group(1)) if t else 0)
    excl = []
    for b in blocks(cfg):
        m = re.match(r"ip dhcp excluded-address (\S+)(?: (\S+))?$", b["head"])
        if m:
            excl.append((ipaddress.IPv4Address(m.group(1)), ipaddress.IPv4Address(m.group(2) or m.group(1))))
    out = []
    for b in blocks(cfg):
        m = re.match(r"ip dhcp pool (\S+)$", b["head"])
        if not m:
            continue
        p = {"name": m.group(1), "network": "", "mask": "", "gateway": "", "dns": "", "lease": ""}
        for l in b["body"]:
            if l.startswith("network "):
                _, p["network"], p["mask"] = l.split()[:3]
            elif l.startswith("default-router "):
                p["gateway"] = l.split()[1]
            elif l.startswith("dns-server "):
                p["dns"] = " ".join(l.split()[1:])
            elif l.startswith("lease "):
                p["lease"] = " ".join(l.split()[1:])
        if p["network"]:
            n = ipaddress.IPv4Network(f"{p['network']}/{p['mask']}", strict=False)
            hosts = list(n.hosts())
            usable = [h for h in hosts if not any(a <= h <= b2 for a, b2 in excl)] if len(hosts) <= 4096 else hosts
            p["prefix"] = n.prefixlen
            p["range"] = f".{str(usable[0]).split('.')[-1]} - .{str(usable[-1]).split('.')[-1]}" if usable else "-"
            p["total"] = len(usable)
        used, total = leases.get(p["name"], (0, p.get("total", 0)))
        p["leased"], p["total"] = used, total or p.get("total", 0)
        p["status"] = "Near Capacity" if p["total"] and used / p["total"] >= 0.9 else "Active"
        out.append(p)
    return out


def routes(cfg):
    static, dynamic = [], []
    for b in blocks(cfg):
        h = b["head"]
        m = re.match(r"ip route (\S+) (\S+) (\S+)", h)
        if m:
            static.append({"network": m.group(1), "mask": m.group(2), "next_hop": m.group(3)})
        m = re.match(r"router (ospf|eigrp|rip)(?: (\d+))?$", h)
        if m:
            d = {"protocol": m.group(1).upper(), "process": m.group(2) or "1", "area": "-", "router_id": "-", "networks": []}
            for l in b["body"]:
                if l.startswith("router-id "):
                    d["router_id"] = l.split()[1]
                elif l.startswith("network "):
                    p = l.split()
                    if "area" in p:
                        d["area"] = f"Area {p[p.index('area') + 1]}"
                    try:
                        net = ipaddress.IPv4Network(f"{p[1]}/{p[2]}") if len(p) > 2 and p[2] != "area" else ipaddress.IPv4Network(p[1] + "/24")
                        d["networks"].append(str(net.with_prefixlen))
                    except ValueError:
                        d["networks"].append(p[1])
            dynamic.append(d)
    return {"static": static, "dynamic": dynamic}


def _hostmask_to_net(addr, wild):
    return ipaddress.IPv4Network(f"{addr}/{ipaddress.IPv4Address(int(ipaddress.IPv4Address(wild)) ^ 0xFFFFFFFF)}")


def etherchannels(summary, ifaces):
    modes = {}
    for i in ifaces:
        if i["channel"]:
            modes.setdefault(i["channel"]["group"], i["channel"]["mode"])
    out = []
    for l in (summary or "").splitlines():
        m = re.match(r"^(\d+)\s+(Po\d+)\((\w+)\)\s+(\w+|-)\s*(.*)$", l)
        if m:
            g = int(m.group(1))
            out.append({"group": g, "po": m.group(2), "protocol": "Static" if m.group(4) == "-" else m.group(4),
                        "interfaces": re.findall(r"([A-Za-z]+\d+(?:/\d+)*)\(", m.group(5)),
                        "mode": modes.get(g, "on").capitalize(), "up": "U" in m.group(3)})
    return out


def portsec_counts(show_ps):
    res = {}
    for l in (show_ps or "").splitlines():
        m = re.match(r"^(\S+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\w+)\s*$", l)
        if m:
            res[m.group(1)] = int(m.group(4))
    return res


def short(name):
    for a, b in SHORT:
        if name.startswith(a):
            return b + name[len(a):]
    return name
