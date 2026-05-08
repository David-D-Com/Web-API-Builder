# `soliscloud_web_api`

Unofficial Python client for the SolisCloud web API derived from the live SolisCloud web application.

Additional docs:
- Human usage guide: [USAGE.md](./USAGE.md)
- Model/operator cheat sheet: [MODEL_CHEATSHEET.yml](./MODEL_CHEATSHEET.yml)

## Install

```powershell
py -m pip install -e .\python
```

Optional Windows credential helper support:

```powershell
py -m pip install -e .\python[windows-credentials]
```

CLI and local test output use `rich` for colored JSON rendering.

## CLI usage

```powershell
$env:SOLIS_USERNAME="you@example.com"
$env:SOLIS_PASSWORD="your-password"
soliscloud-web-api --list-sites
```

## Python usage

```python
from soliscloud_web_api import SolisSession, SolisWebApiClient

session = SolisSession.from_credentials("you@example.com", "your-password")
client = SolisWebApiClient(session)
sites = client.list_all_sites()
detail = client.station_detail(sites[0]["id"])
```

Filtered results example:

```python
session = SolisSession.from_credentials(
    "you@example.com",
    "your-password",
    filter_results=True,
    preferred_language="en",
)
client = SolisWebApiClient(session)
profile = client.profile()
```

Caching example:

```python
session = SolisSession.from_credentials(
    "you@example.com",
    "your-password",
    cache_enabled=True,
    cache_policy="smart",
)
client = SolisWebApiClient(session)

# Historical/chart-style calls are cached automatically in smart mode.
day_1 = client.inverter_chart_day("123", day="2026-05-02", time_zone=-6)
day_2 = client.inverter_chart_day("123", day="2026-05-02", time_zone=-6)
assert day_1 == day_2
```

## Notes

- The core package is platform-agnostic.
- Windows Credential Manager integration is intentionally kept outside the package core.
- A stable non-secret device id is stored in the user profile.
- With `filter_results=True`, the client trims some large UI-metadata fields and normalizes `*En`/`*Cn` language pairs.
- Request caching is built into the client.
- Default `cache_policy="smart"` caches historical and stable endpoints, but skips obviously live endpoints like login, profile, site list, alarms, and warnings.
- Cache files are stored under `~/.soliscloud_web_api/cache`.
- Use `cache_policy="off"` to disable caching, or `client.clear_cache()` to remove cached responses.
- For a fuller walkthrough of patterns and endpoint groups, see `USAGE.md`.
