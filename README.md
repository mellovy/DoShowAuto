# DoShowAuto (DSA) - Sprint 1: Device Configuration Automation

CherryPy + Netmiko (SSHv2) + PostgreSQL, run with Docker.

    cp .env.example .env   # set SECRET_KEY, ADMIN_PASSWORD
    docker compose up --build   # http://localhost:8080

Pages follow SRS 3.1: Login, General (profile, basic config, SSH connect, AI mode), Configure (interfaces, DHCP, VLAN, routing, EtherChannel, port security), Devices, Logs (audit). Persistent console, subnet calculator and maintenance sidebar.
Tests: `pip install -r requirements.txt && pytest` (command generators are pure and need no device).

Sprint 1 notes: no HITL preview yet (Sprint 2). `write memory` always takes a backup first (SRS 5.2).
Test only against GNS3 / the isolated lab, never production.
Dev without devices or PostgreSQL: DATABASE_URL=sqlite:////tmp/dsa.db DSA_MOCK=1 ADMIN_USER=admin ADMIN_PASSWORD=Passw0rd1 python -m app.main
