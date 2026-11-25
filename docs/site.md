# The website (GitHub Pages)

The home page is published as a static site. It has the token-bucket simulation, the
install steps, the measured numbers and the privacy and terms pages. It does **not**
have the dashboard: the dashboard needs Django, Redis and the `tokenguard_feed`
process behind it, and a public copy would also expose a staff login. To see the
dashboard, run it yourself (`docker compose up`, see the README) or watch the demo video.

## One-time setup

1. Push `.github/workflows/pages.yml` to `main`.
2. On GitHub: **Settings > Pages > Build and deployment > Source: GitHub Actions**.
3. Run the **Pages** workflow once from the **Actions** tab (**Run workflow**), or push a
   change under `dashboard/`.

The site is then at `https://<your-github-username>.github.io/tokenguard/`.
The deploy job prints the exact address.

## How it differs from the normal build

The workflow builds with two environment variables:

| Variable | Value | Effect |
|---|---|---|
| `VITE_SITE_ONLY` | `1` | No dashboard page (`#/dashboard` shows the home page). The dashboard buttons become "Run the dashboard locally" and link to the README steps. Source maps are not published. |
| `VITE_BASE` | `./` | Relative asset paths, so it works under `/tokenguard/` or any other path. |

Without them (`npm run dev`, `npm run build`, Docker) nothing changes: the dashboard
works as before. Pages use `#/` addresses, so no server setup or 404 page is needed.

## Check it

Locally: `cd dashboard`, then on PowerShell
`$env:VITE_SITE_ONLY="1"; $env:VITE_BASE="./"; npm run build; npm run preview`
and open the address it prints. The home page should load, the buttons should say
"Run the dashboard locally", and `#/dashboard` should show the home page.
After deploying, `python scripts/check_site_links.py` checks that every link on the
home page answers.
