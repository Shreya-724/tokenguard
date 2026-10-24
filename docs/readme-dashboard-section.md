## Dashboard

A React dashboard (`dashboard/`) shows live traffic over the WebSocket: an
allowed-vs-blocked chart, top consumers, per-key bucket levels, and a rule
editor that changes limits live and shows the before/after. Run it with
`npm install && npm run dev` in `dashboard/`, next to the Django server and
`manage.py tokenguard_feed`. Details: [docs/dashboard.md](docs/dashboard.md).
