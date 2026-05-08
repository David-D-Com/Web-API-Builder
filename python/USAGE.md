# Solis Web API Usage Guide

This package is an unofficial Python client for the SolisCloud web application API.

It is intended for:
- scripting and reporting
- integration tests
- reverse-engineering follow-up work from captured browser traffic
- repeatable data pulls without copying browser request code into every script

It is not intended to be a perfect mirror of every Solis frontend behavior. The goal is a stable, practical client.

## What It Does

The client reproduces the Solis web app flow:

1. Open the login page to establish cookies.
2. Hash the password client-side.
3. Sign each request with the Solis web HMAC scheme.
4. Reuse the returned session token.
5. Optionally clean noisy payloads.
6. Optionally cache stable and historical responses.

## Install

```powershell
py -m pip install -e .\python
```

Optional Windows-only helpers used by local test scripts:

```powershell
py -m pip install -e .\python[windows-credentials]
```

## Credentials

The reusable package is platform-agnostic.

Recommended options:
- pass credentials directly with `SolisSession.from_credentials(...)`
- use environment variables with `SolisSession.from_env()`

Environment variables:

```powershell
$env:SOLIS_USERNAME="you@example.com"
$env:SOLIS_PASSWORD="your-password"
```

## Basic Python Example

```python
from soliscloud_web_api import SolisSession, SolisWebApiClient

session = SolisSession.from_env()
client = SolisWebApiClient(session)

sites = client.list_all_sites()
first_site = sites[0]
detail = client.station_detail(first_site["id"])
print(first_site["stationName"])
print(detail["success"])
```

## Recommended Session Settings

For most analysis/reporting scripts:

```python
session = SolisSession.from_env(
    filter_results=True,
    preferred_language="en",
    cache_enabled=True,
    cache_policy="smart",
)
client = SolisWebApiClient(session)
```

Why:
- `filter_results=True` removes a lot of frontend/UI noise
- `preferred_language="en"` collapses `*En` / `*Cn` pairs into cleaner English keys
- `cache_policy="smart"` avoids refetching stable historical data

## Filtering

Filtering is optional and happens in the client layer.

With filtering enabled:
- some large UI-only fields are removed
- paired language fields like `defaultParamCn` / `defaultParamEn` are normalized
- the returned payload shape is cleaner for downstream scripts

This is useful when:
- you are analyzing data
- you want stable downstream structures

This is less useful when:
- you are trying to reproduce the frontend response exactly
- you are doing capture-to-client implementation work

## Caching

Caching is a core feature of the package.

Default behavior:
- `cache_policy="smart"`
- historical/chart-style calls are cached
- stable detail/config calls are cached
- obviously live endpoints are not cached

Examples of endpoints that are usually cached:
- inverter day/month/year/all charts
- inverter all-energy
- station day/month/year/all charts
- station all-energy
- stable detail/config endpoints

Examples of endpoints that are usually not cached:
- login
- profile
- station list
- alarms and warnings

Cache location:
- `~/.soliscloud_web_api/cache`

Clear cache:

```python
removed = client.clear_cache()
print(f"Removed {removed} cached files")
```

Disable cache entirely:

```python
session = SolisSession.from_env(cache_policy="off")
```

## Endpoint Groups

The client is organized roughly by feature area.

Site and station:
- `list_sites`
- `list_all_sites`
- `station_detail`
- `station_all_energy`
- `station_chart_day`
- `station_chart_month`
- `station_chart_year`
- `station_chart_all`
- `station_config_detail`
- `station_device_count`
- `station_user`
- `station_visitor`

Alarms and warnings:
- `alarm_list`
- `alarm_detail`
- `alarm_read_all`
- `warning_list`
- `warning_correction_records`

Inverters:
- `inverter_list`
- `inverter_index_list`
- `inverter_detail`
- `inverter_all_energy`
- `inverter_chart_day`
- `inverter_chart_month`
- `inverter_chart_year`
- `inverter_chart_all`
- `inverter_at_check`
- `inverter_config`
- `inverter_dispersion_list`
- `inverter_iv_info`
- `inverter_list_search_temp`

Collectors and related devices:
- `collector_list`
- `collector_detail`
- `collector_day`
- `collector_packet_loss_rate`
- `ammeter_list`
- `epm_list`
- `weather_list`

Optimizers:
- `opt_config_list`
- `opt_panel_list`
- `opt_station_detail`

Bootstrap / notices / message center:
- `profile`
- `message_list`
- `gly_message_record_list`
- `gly_message_record_realtime`
- `system_right_check`
- `system_config_global_v2`
- `devup_notice`
- `devup_upgrade_fail_notice`
- `devup_user_notice_count`

## CLI

Minimal examples:

```powershell
soliscloud-web-api --login
soliscloud-web-api --profile
soliscloud-web-api --list-sites
```

With filtering:

```powershell
soliscloud-web-api --list-sites --filter-results --display-language en
```

## Local Test Helpers

The repo contains local helper scripts under `tests/` and `scripts/`.

Important distinction:
- package code in `python/src/soliscloud_web_api` should stay reusable and platform-agnostic
- Windows Credential Manager support belongs in helper scripts, not in the reusable client

## When Adding New Endpoints

Recommended process:

1. Capture the request from the browser flow.
2. Confirm method, path, payload shape, and whether it is GET or POST.
3. Add a thin high-level client method.
4. Decide whether it should be cached in `smart` mode.
5. Add or update a test/helper script that exercises it.
6. Prefer reusing an existing library/tool if the task is not Solis-specific.

## Notes For Future Maintenance

- The request signer is the critical piece. If Solis changes signing behavior, login may still work while later requests fail.
- GET endpoints in this package use the Solis query-signing behavior captured from the web app.
- If you see repeated historical refetches, check cache policy before changing analysis scripts.
- If a payload looks huge and UI-heavy, try `filter_results=True` first before writing custom cleanup code.
