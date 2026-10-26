import pytest
from app import commands as c


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
