import os

os.environ.setdefault("DSA_MOCK", "1")  # keep device.py from importing netmiko

import pytest
from app import commands as c
from app.main import _b


def test_hostname():
    assert c.hostname("R1") == ["hostname R1"]
    with pytest.raises(ValueError):
        c.hostname("bad name!")


def test_enable_secret_min_len():
    with pytest.raises(ValueError):
        c.enable_secret("short")
    assert c.enable_secret("longenough1") == ["enable secret longenough1"]


def test_ssh_setup():
    out = c.ssh_setup("lab.local", "admin", "Passw0rd!!")
    assert "ip ssh version 2" in out and "transport input ssh" in out


def test_banner():
    assert c.banner(motd="Authorized only") == ["banner motd ^Authorized only^"]
    with pytest.raises(ValueError):
        c.banner(motd="bad^")
    with pytest.raises(ValueError):
        c.banner()


def test_vlan_bounds():
    assert c.vlan(20, "Sales") == ["vlan 20", "name Sales"]
    for bad in (0, 4095):
        with pytest.raises(ValueError):
            c.vlan(bad)


def test_trunk():
    out = c.trunk("Gi0/1", "10,20", 99)
    assert "switchport trunk allowed vlan 10,20" in out and "switchport trunk native vlan 99" in out


def test_static_route_normalises_network():
    assert c.static_route("10.1.1.5", "255.255.255.0", "10.0.0.1") == ["ip route 10.1.1.0 255.255.255.0 10.0.0.1"]
    with pytest.raises(ValueError):
        c.static_route("10.1.1.0", "255.255.255.0", "999.0.0.1")


def test_interface_ip():
    out = c.interface_ip("Gi0/0", "192.168.1.1", "255.255.255.0")
    assert "ip address 192.168.1.1 255.255.255.0" in out and out[-1] == "no shutdown"








def test_show_whitelist():
    assert c.show("show ip interface brief") == "show ip interface brief"
    with pytest.raises(ValueError):
        c.show("configure terminal")


def test_dhcp():
    out = c.dhcp_pool("LAN", "10.50.0.0", "255.255.252.0", "10.50.0.1", "8.8.8.8, 8.8.4.4", "10.50.0.100", 0, 23, 0)
    assert out[0] == "ip dhcp excluded-address 10.50.0.1 10.50.0.99"
    assert "network 10.50.0.0 255.255.252.0" in out and out[-1] == "lease 0 23 0"


def test_port_security():
    out = c.port_security(["Gi0/1", "Gi0/2"], True, 2, "restrict", True)
    assert out.count("switchport port-security") >= 2 and "switchport port-security violation restrict" in out
    assert c.port_security(["Gi0/1"], False)[-1] == "no switchport port-security"
    with pytest.raises(ValueError):
        c.port_security([], True)


def test_etherchannel():
    out = c.etherchannel(1, "lacp", ["Gi0/1", "Gi0/2"], description="Uplink")
    assert "channel-group 1 mode active" in out and "description Uplink" in out
    with pytest.raises(ValueError):
        c.etherchannel(1, "lacp", ["Gi0/1"])
    with pytest.raises(ValueError):
        c.etherchannel(1, "pagp", ["Gi0/1", "Gi0/2"], "active")


def test_dynamic_routing():
    assert c.dynamic_routing("ospf", 100, "10.0.0.0/24", 0) == ["router ospf 100", "network 10.0.0.0 0.0.0.255 area 0"]
    assert "network 10.0.0.0" in c.dynamic_routing("rip", None, "10.1.2.0/24")


def test_interface_config():
    out = c.interface_config("Gi0/1", "static", "10.0.1.1", "255.255.255.252", "Uplink", None, True, True)
    assert "ip address 10.0.1.1 255.255.255.252" in out and "switchport mode trunk" in out and out[-1] == "no shutdown"


# ---- protocol accuracy: interface names ---------------------------------
def test_interface_name_forms():
    for good in ("Gi0/1", "GigabitEthernet0/1", "FastEthernet0/0", "TenGigabitEthernet1/1",
                 "Po1", "Port-channel1", "Vlan10", "Gi0/1.100"):
        assert c.interface_ip(good, "10.0.0.1", "24")[0] == f"interface {good}"


def test_interface_name_rejects_garbage():
    for bad in ("Banana0/1", "Gi", "0/1", "GigabitEthernet", "switchport"):
        with pytest.raises(ValueError):
            c.interface_ip(bad, "10.0.0.1", "24")


# ---- protocol accuracy: VLAN --------------------------------------------
def test_vlan_rejects_non_numeric():
    with pytest.raises(ValueError):
        c.vlan("ten")
    assert c.vlan(4094) == ["vlan 4094"]


def test_vlan_name_length_limit():
    with pytest.raises(ValueError):
        c.vlan(20, "x" * 33)
    assert c.vlan(20, "x" * 32) == ["vlan 20", "name " + "x" * 32]


def test_trunk_vlan_ranges():
    assert "switchport trunk allowed vlan 10,20-30" in c.trunk("Gi0/1", "10, 20-30")
    with pytest.raises(ValueError):
        c.trunk("Gi0/1", "30-20")
    with pytest.raises(ValueError):
        c.trunk("Gi0/1", "abc")


# ---- protocol accuracy: masks / addresses -------------------------------
def test_static_route_rejects_noncontiguous_mask():
    with pytest.raises(ValueError):
        c.static_route("10.1.1.0", "255.255.0.255", "10.0.0.1")


def test_mask_accepts_prefix_length():
    out = c.interface_ip("Gi0/0", "192.168.1.1", "24")
    assert "ip address 192.168.1.1 255.255.255.0" in out


def test_ip_error_names_field():
    with pytest.raises(ValueError, match="next hop"):
        c.static_route("10.1.1.0", "255.255.255.0", "999.0.0.1")


# ---- protocol accuracy: dynamic routing ---------------------------------
def test_ospf_area_dotted_and_bounds():
    out = c.dynamic_routing("ospf", 1, "10.0.0.0/24", "0.0.0.1")
    assert out[-1] == "network 10.0.0.0 0.0.0.255 area 1"
    assert c.dynamic_routing("ospf", 1, "10.0.0.0/24", 4294967295)[-1].endswith("area 4294967295")
    for bad in (4294967296, "1.2.3", "256.0.0.0"):
        with pytest.raises(ValueError):
            c.dynamic_routing("ospf", 1, "10.0.0.0/24", bad)


def test_process_id_bounds():
    for bad in (0, 65536, "abc"):
        with pytest.raises(ValueError):
            c.dynamic_routing("eigrp", bad, "10.0.0.0/24")
    assert c.dynamic_routing("eigrp", 65535, "10.0.0.0/24")[0] == "router eigrp 65535"


# ---- protocol accuracy: etherchannel / port-security --------------------
def test_etherchannel_group_bounds():
    assert "channel-group 48 mode on" in c.etherchannel(48, "static", ["Gi0/1", "Gi0/2"])
    for bad in (0, 49, "x"):
        with pytest.raises(ValueError):
            c.etherchannel(bad, "lacp", ["Gi0/1", "Gi0/2"])


def test_port_security_max_bounds():
    out = c.port_security(["Gi0/1"], True, 8192)
    assert "switchport port-security maximum 8192" in out
    for bad in (0, 8193, "x"):
        with pytest.raises(ValueError):
            c.port_security(["Gi0/1"], True, bad)


# ---- removal / reset generators -----------------------------------------
def test_vlan_remove():
    assert c.vlan_remove(20) == ["no vlan 20"]
    with pytest.raises(ValueError):
        c.vlan_remove(0)


def test_interface_reset():
    assert c.interface_reset("Gi0/1") == ["default interface Gi0/1"]
    with pytest.raises(ValueError):
        c.interface_reset("Banana0/1")


def test_dhcp_remove():
    assert c.dhcp_remove("LAN") == ["no ip dhcp pool LAN"]
    with pytest.raises(ValueError):
        c.dhcp_remove("bad name!")


def test_static_route_remove():
    assert c.static_route_remove("10.1.1.5", "255.255.255.0", "10.0.0.1") == \
        ["no ip route 10.1.1.0 255.255.255.0 10.0.0.1"]
    assert c.static_route_remove("10.1.1.0", "24", "10.0.0.1") == \
        ["no ip route 10.1.1.0 255.255.255.0 10.0.0.1"]
    with pytest.raises(ValueError):
        c.static_route_remove("10.1.1.0", "255.255.0.255", "10.0.0.1")


def test_etherchannel_remove():
    assert c.etherchannel_remove(1) == ["no interface Port-channel 1"]
    with pytest.raises(ValueError):
        c.etherchannel_remove(49)


def test_portsec_remove():
    assert c.portsec_remove("Gi0/1") == ["interface Gi0/1", "no switchport port-security"]
    with pytest.raises(ValueError):
        c.portsec_remove("switchport")


def test_routing_remove():
    assert c.routing_remove("ospf", 100) == ["no router ospf 100"]
    assert c.routing_remove("eigrp", 65535) == ["no router eigrp 65535"]
    assert c.routing_remove("RIP", None) == ["no router rip"]
    with pytest.raises(ValueError):
        c.routing_remove("bgp", 1)
    with pytest.raises(ValueError):
        c.routing_remove("ospf", 0)


# ---- _b: remove dispatch + unchanged default path ------------------------
def test_b_remove_dispatch():
    assert _b({"kind": "vlan", "action": "remove", "vlan_id": 10}) == ["no vlan 10"]
    assert _b({"kind": "interface", "action": "remove", "iface": "Gi0/1"}) == ["default interface Gi0/1"]
    assert _b({"kind": "dhcp", "action": "remove", "name": "LAN"}) == ["no ip dhcp pool LAN"]
    assert _b({"kind": "static_route", "action": "remove", "network": "10.1.1.0",
               "mask": "255.255.255.0", "next_hop": "10.0.0.1"}) == \
        ["no ip route 10.1.1.0 255.255.255.0 10.0.0.1"]
    assert _b({"kind": "etherchannel", "action": "remove", "group": 1}) == ["no interface Port-channel 1"]
    assert _b({"kind": "portsec", "action": "remove", "iface": "Gi0/1"}) == \
        ["interface Gi0/1", "no switchport port-security"]
    assert _b({"kind": "dynamic_route", "action": "remove", "protocol": "ospf", "process": 100}) == \
        ["no router ospf 100"]


def test_b_remove_unknown_kind():
    with pytest.raises(ValueError, match="Unknown configuration type"):
        _b({"kind": "nope", "action": "remove"})


def test_b_default_path_unchanged():
    assert _b({"kind": "vlan", "vlan_id": 10, "name": "Sales"}) == ["vlan 10", "name Sales"]
    assert _b({"kind": "vlan", "action": "set", "vlan_id": 10}) == ["vlan 10"]
    assert _b({"kind": "static_route", "network": "10.1.1.5", "mask": "24", "next_hop": "10.0.0.1"}) == \
        ["ip route 10.1.1.0 255.255.255.0 10.0.0.1"]
    with pytest.raises(ValueError, match="Unknown configuration type"):
        _b({"kind": "nope"})
