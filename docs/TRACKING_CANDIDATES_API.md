# `/api/v1/tracking-candidates` (issue #6)

Authenticated replacement for the public `data/tracking-candidates.json`, the
upstream feed of NexusDashboard. Same body, served from the private `radar`
schema by a Vercel Function. The public JSON must stay available until
NexusDashboard has switched over and been verified (then Pages can be retired).

## Data path

```
update_theme_radar.py (hourly GitHub Actions run)
  ├─ writes data/tracking-candidates.json          (unchanged, still committed)
  └─ radar dual-write, one transaction per run:
       radar.pipeline_run  ──FK──  radar.tracking_candidates_snapshot
                                   (generated_at PK, run_id, item_count, payload jsonb)

NexusDashboard ──GET /api/v1/tracking-candidates──▶ api/v1/tracking-candidates.js
   Authorization: Bearer <key>          │ 1. key check (constant time) ─▶ 401
                                        │ 2. RADAR_API_DATABASE_URL (radar_reader only)
                                        ▼
                  select payload from radar.tracking_candidates_snapshot
                  order by generated_at desc limit 1
                                        │ 3. contract + staleness check ─▶ 503
                                        ▼
                                  200, body = stored payload
```

The snapshot is the exact dict written to the JSON file, validated before the
transaction opens (`map_tracking_candidates_snapshot`). A payload missing a
contract key fails the run's whole DB mirror (`radar_dual_write_failed`) while
the JSON still publishes: a break NexusDashboard would feel is caught loudly at
write time, not served.

## Responses

| Status | When | Body |
|---|---|---|
| 200 | valid key, newest snapshot passes the contract, ≤ `RADAR_TRACKING_API_MAX_AGE_MINUTES` old (default 720) | the payload; headers `X-Radar-Source: db`, `X-Radar-Generated-At` |
| 401 | header missing, not `Bearer`, wrong key, **or no key configured on the server** | `{"error":"unauthorized"}` + `WWW-Authenticate: Bearer realm="radar"` |
| 503 | `not_configured`, `db_error`, `no_snapshot`, `contract_violation`, `stale` | `{"error":"tracking_candidates_unavailable","reason":…}` |
| 405 | any method other than GET (Vercel default for named exports) | — |

All responses: `Cache-Control: private, no-store`, `Vary: Authorization`.
The key check runs before any DB access. Bodies and logs never contain the
presented key, driver messages, hosts or DSNs (logs carry e.g.
`error(42501)` only).

**Contract.** `api/_lib/trackingCandidatesContract.js` and
`TRACKING_CANDIDATES_REQUIRED_KEYS` in `scripts/radar_store.py` (kept equal by
a test) list the 20 top-level keys of today's JSON. Additional keys pass;
a missing key, `items` not an array, `items.length != total_items`, or an item
missing `id/title_zh/url/source_id/published_at/market_id/matched_themes/primary_theme_id/related_symbols/decision/cluster_id`
fails. Equality is semantic: `jsonb` does not preserve key order, so consumers
must deserialize by name (any JSON library does).

Why 720 min: the "hourly" schedule actually lands every 4-8 h because GitHub
drops scheduled runs; 12 h is the first point where stale means broken.

## One-time setup (manual, per environment)

1. **DB** — after `20261118080000_create_radar_schema.sql`, apply
   `supabase/migrations/20261118100000_create_radar_tracking_candidates_snapshot.sql`
   (re-runnable). The API login is the same `radar_api` role as `/api/pre-market`
   (#5); if it does not exist yet:

   ```sql
   create role radar_api login password '<generated>';   -- store only in Vercel
   grant radar_reader to radar_api;                       -- SELECT only
   ```

   The pipeline login already has `radar_writer`, and the migration grants it
   insert/update on the new table. No new GitHub secret.
2. **Generate the key** (≥ 32 chars; shorter entries are ignored):

   ```bash
   openssl rand -base64 48 | tr -d '\n/+=' | cut -c1-48
   ```

   Store it in exactly two places: Vercel env `RADAR_TRACKING_API_KEYS`, and
   NexusDashboard's secret store. Never in git, never `VITE_`-prefixed.
3. **Vercel environment variables** (Production; Preview only if needed):

   | Name | Value |
   |---|---|
   | `RADAR_TRACKING_API_KEYS` | the key (comma-separated during rotation) |
   | `RADAR_API_DATABASE_URL` | `postgresql://radar_api.<project-ref>:<pw>@<region>.pooler.supabase.com:6543/postgres` |
   | `RADAR_API_DATABASE_CA` | Supabase root CA PEM — set in Production |
   | `RADAR_TRACKING_API_MAX_AGE_MINUTES` | optional, default `720` |

4. **Deployment Protection** — if Vercel Authentication covers Production
   (the #5 runbook recommends it), a server-to-server caller is stopped before
   the function runs. Enable *Protection Bypass for Automation* and have
   NexusDashboard send `x-vercel-protection-bypass: <secret>` in addition to the
   bearer key. Verify that the bypass is available on the Hobby plan when
   setting it up; the alternative is protecting Preview only.

## NexusDashboard switch-over (consumer side)

Keep the old URL as a configured fallback until Pages is retired:

```jsonc
// appsettings.json (secrets via user-secrets / env, not this file)
"RadarUpstream": {
  "PrimaryUrl":  "https://<vercel-domain>/api/v1/tracking-candidates",
  "FallbackUrl": "https://<pages-domain>/data/tracking-candidates.json",
  "ApiKey": "",                 // env: RadarUpstream__ApiKey
  "VercelBypass": "",           // env: RadarUpstream__VercelBypass (if protection on)
  "UseFallbackOnly": false      // kill switch: true = old behaviour
}
```

```csharp
public async Task<JsonDocument> GetTrackingCandidatesAsync(CancellationToken ct)
{
    if (!_opt.UseFallbackOnly)
    {
        using var req = new HttpRequestMessage(HttpMethod.Get, _opt.PrimaryUrl);
        req.Headers.Authorization = new AuthenticationHeaderValue("Bearer", _opt.ApiKey);
        if (!string.IsNullOrEmpty(_opt.VercelBypass))
            req.Headers.Add("x-vercel-protection-bypass", _opt.VercelBypass);
        try
        {
            using var res = await _http.SendAsync(req, ct);   // HttpClient.Timeout ~10 s
            if (res.IsSuccessStatusCode)
                return await JsonDocument.ParseAsync(await res.Content.ReadAsStreamAsync(ct), cancellationToken: ct);
            // 401 = key mismatch: alert, do not just fall back silently.
            _log.LogWarning("radar_api_failed status={Status} reason={Body}",
                (int)res.StatusCode, await res.Content.ReadAsStringAsync(ct));
        }
        catch (Exception ex) when (ex is HttpRequestException or TaskCanceledException)
        {
            _log.LogWarning(ex, "radar_api_unreachable");
        }
    }
    return await JsonDocument.ParseAsync(await _http.GetStreamAsync(_opt.FallbackUrl, ct), cancellationToken: ct);
}
```

Evidence for the PR (acceptance item 4): one NexusDashboard log line showing a
200 from `PrimaryUrl` with the `X-Radar-Generated-At` value, plus the matching
`radar.tracking_candidates_snapshot.generated_at`.

## Key rotation

1. Generate a new key; set `RADAR_TRACKING_API_KEYS=<old>,<new>`; redeploy.
2. Switch NexusDashboard to `<new>`; confirm 200s.
3. Set `RADAR_TRACKING_API_KEYS=<new>`; redeploy. `<old>` now gets 401.

## Rollback

- Instant, no deploy: `revoke radar_reader from radar_api;` → API 503
  `db_error` → NexusDashboard reads `FallbackUrl`. (Also stops `/api/pre-market`,
  which shares the role and falls back to its JSON.)
- Consumer only: `RadarUpstream:UseFallbackOnly=true`.
- Writes: `revoke radar_writer from <pipeline login>` stops the whole dual-write;
  JSON publishing is unaffected.

## Verification

```bash
npm run test:api                                     # contract + auth (node:test)
.venv/bin/python -m pytest tests/test_radar_store.py -q
curl -s -o /dev/null -w '%{http_code}\n' https://<deployment>/api/v1/tracking-candidates          # 401
curl -s -H "Authorization: Bearer $KEY" https://<deployment>/api/v1/tracking-candidates | jq .generated_at
```

```sql
select generated_at, run_id, item_count
from radar.tracking_candidates_snapshot order by generated_at desc limit 5;
```
