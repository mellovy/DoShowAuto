# DoShowAuto (DSA) - Sprint 2: Human-in-the-Loop Safety Mechanism

CherryPy + Netmiko (SSHv2) + PostgreSQL, run with Docker.

    cp .env.example .env   # set SECRET_KEY, ADMIN_PASSWORD
    docker compose up --build   # http://localhost:8080

Pages follow SRS 3.1: Login, General (profile, basic config, SSH connect, AI mode), Configure (interfaces, DHCP, VLAN, routing, EtherChannel, port security), Devices, Logs (audit). Persistent console, subnet calculator and maintenance sidebar.
Tests: `pip install -r requirements.txt && pytest` (command generators are pure and need no device).

Sprint 2 notes (SRS 4.2): every deployment is previewed first — `POST /api/preview` returns the exact CLI commands plus a `preview_id`; `POST /api/apply` then requires `confirm: true` and a matching `preview_id` (else 409), automatically saves a pre-change running-config backup before pushing (aborts with 502 if the backup fails), and records the commands, user, device and CLI response in the audit log. Backups are stored in `tbl_backups` (SRS 5.2 / DRP-6.4-1). The UI shows a confirmation modal listing the exact commands; cancel sends nothing.
Sprint 1 notes: `write memory` always takes a backup first (SRS 5.2).
Test only against GNS3 / the isolated lab, never production.
Dev without devices or PostgreSQL: DATABASE_URL=sqlite:////tmp/dsa.db DSA_MOCK=1 ADMIN_USER=admin ADMIN_PASSWORD=Passw0rd1 python -m app.main
