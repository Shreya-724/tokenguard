## Dashboard backend

Staff-only REST endpoints (`/tokenguard/stats/`, `consumers/`, `buckets/<key>/`,
`rules/`) and a WebSocket (`/ws/tokenguard/stats/`) that pushes a stats snapshot
every second through Django Channels. Rules can be changed live over the API.
Setup, endpoints and limits: [docs/dashboard-backend.md](docs/dashboard-backend.md).
