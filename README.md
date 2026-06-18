# Music Calendar Source Finder

Local Python automation for discovering music, arts, culture, tourism, and event-calendar source pages for cities. This is a source discovery system only. It searches for calendar/source pages, scores their music and calendar signal, and exports XLSX workbooks. It does not ingest individual events, artist rows, ticket prices, or full calendar listings.

## What It Finds

- Local music calendars
- Arts and culture calendars
- Tourism bureau event calendars
- City, chamber, and downtown event calendars
- Newspaper, magazine, and alt-weekly arts/music sections
- Radio station calendars
- Venue and promoter calendars
- University and community calendars
- Festival calendar hubs

## Setup

Use Python 3.11 or newer.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
cp .env.example .env
```

Windows PowerShell:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
py -m pip install --upgrade pip
py -m pip install -e '.[dev]'
copy .env.example .env
```

Set `SERPAPI_API_KEY` in `.env` for live search. Use `--dry-run` to test without external API calls. Dry-run rows are isolated with `run_mode=dry_run` and are excluded from the live master workbook unless you explicitly pass `--export-dry-run`, which writes to `exports/dry_run/`.

## Local Commands

```bash
python -m music_calendar_finder --help
python -m music_calendar_finder init-db
python -m music_calendar_finder import-cities --file imports/uscities.xlsx
python -m music_calendar_finder run --limit 10 --dry-run
python -m music_calendar_finder run-city --city "Austin" --state "TX" --dry-run
python -m music_calendar_finder status
python -m music_calendar_finder report
python -m music_calendar_finder export
python -m music_calendar_finder qa-workbook
python -m music_calendar_finder clean-dry-run-data
python -m music_calendar_finder validate-urls --city "Austin" --state "TX"
```

For live SerpAPI batch runs, pass `--yes` after reviewing the estimated usage:

```bash
python -m music_calendar_finder run --limit 5 --max-serpapi-queries-per-city 10 --yes
```

Quality check one city:

```bash
.venv/bin/python -m music_calendar_finder clean-dry-run-data
.venv/bin/python -m music_calendar_finder run-city --city "Austin" --state "TX" --yes --quality-report --force
.venv/bin/python -m music_calendar_finder validate-urls --city "Austin" --state "TX"
.venv/bin/python -m music_calendar_finder export
```

For live `run-city`, `--force` replaces that city's previous live run data before creating the new run. Dry-run data stays isolated.

Refresh and maintenance examples:

```bash
python -m music_calendar_finder run --limit 1 --refresh-stale-after-days 90
python -m music_calendar_finder reset-city --city "Austin" --state "TX"
python -m music_calendar_finder reset-failed --dry-run
python -m music_calendar_finder mark-stale --older-than-days 90
python -m music_calendar_finder run --failed-only --limit 10 --dry-run
```

## Import XLSX

The importer requires a `city` column. It also supports `state`, `state_name`, `country`, `metro_name`, `county`, `population`, `priority`, and `enabled`, plus common aliases such as `City`, `State`, `ST`, `metro`, and `pop`.

Rows with no city are skipped. Cities are deduplicated by city, state, country, and metro name. The source row number and import batch id are preserved in SQLite.

The US Cities workbook defaults are:

- `--city-column city`
- `--state-column state_id`
- `--population-column population`
- `--lat-column lat`
- `--lng-column lng`

Import examples:

```bash
.venv/bin/python -m music_calendar_finder import-cities --file imports/uscities.xlsx
.venv/bin/python -m music_calendar_finder import-cities --file imports/uscities.xlsx --state CA --min-population 50000
.venv/bin/python -m music_calendar_finder import-cities --file imports/uscities.xlsx --limit 100
```

Imported city metadata includes population, latitude, longitude, original row id when the workbook has an `id` column, and a `city_tier` label:

- `mega`: population >= 1000000
- `large`: population >= 250000
- `mid`: population >= 100000
- `small_major`: population >= 50000
- `small`: population >= 25000
- `tiny`: population < 25000

## Staged Runs

Priority cities are configured in `config/priority_cities.yml` with `city`, `state`, `reason`, and `priority_level`. Use `--include-priority-cities` to include those cities even when they fall below the current population band, or `--priority-only` to run only configured priority cities.

Initial validation:

```bash
.venv/bin/python -m music_calendar_finder run --min-population 50000 --limit 10
```

Phase 1:

```bash
.venv/bin/python -m music_calendar_finder run --min-population 50000 --sleep-seconds-between-cities 10
```

Phase 2:

```bash
.venv/bin/python -m music_calendar_finder run --min-population 25000 --max-population 49999 --include-priority-cities
```

Phase 3:

```bash
.venv/bin/python -m music_calendar_finder run --min-population 10000 --max-population 24999 --include-priority-cities
```

State-specific examples:

```bash
.venv/bin/python -m music_calendar_finder run --state CA --min-population 50000
.venv/bin/python -m music_calendar_finder run --state CA --min-population 50000 --limit 25
```

This remains source discovery only. Do not scrape actual events.

## URL Verification

The live master workbook exports only real, validated source URLs. A source can appear in `Top Sources` or `Verified Sources` only when:

- `run_mode` is `live`
- `url_origin` is not `dry_run_fixture`
- `url_validation_status` is `valid`, `redirect_valid`, or `forbidden_but_real`
- the source has local and music, arts, culture, tourism, or calendar relevance
- the URL is not synthetic, dead, spam, or rejected
- the source is not a national aggregator, ticketing platform, affiliate/redirect URL, login URL, real-estate/blog-style page, or individual Google Calendar event URL

Exported source rows include `source_quality_tier`, `content_quality_status`, `challenge_page_detected`, plus per-field URL quality columns for `website_url`, `best_calendar_url`, `music_url`, `events_url`, and `arts_url`. Bad calendar URLs are not force-filled into `best_calendar_url`; if the discovered calendar URL is an event template, ticketing URL, login/redirect, affiliate URL, Google Calendar render/embed URL, or unrelated external ticket page, the export leaves it blank unless a standing source page is available.

Challenge/interstitial page titles such as `Just a moment...`, `Checking your browser`, `Access denied`, and JavaScript/human-verification messages are not used as display names or ranking content. Top Sources also enforces post-classification caps: venue calendars max 40% of a city's Top Sources, regional references max 20%, and weak articles/blog posts, ticketing platforms, national aggregators, individual event pages, real-estate/commercial blogs, and challenge/blocked sources are excluded from Top Sources.

The system rejects obvious synthetic domains such as `austin-tx-altmusic.org`, `austin-tx-chamberarts.org`, and `visitaustin-tx-newspaper.com`. Dry-run fixtures and unresolved URLs stay out of live verified sheets.

## Output

The master workbook is written to:

```text
exports/master_music_calendar_sources.xlsx
```

Workbook sheets:

- Top Sources
- Verified Sources
- Candidates Unverified
- Rejected
- City Summary
- Search API Usage

City Summary count columns are:

- `raw_candidates_count`
- `verified_sources_count`
- `candidates_unverified_count`
- `rejected_count`
- `top_sources_count`
- `search_api_queries_count`

By default, export uses only the latest completed live run for each city. Historical rows are not mixed into the live working sheets. To audit older runs separately, use:

```bash
.venv/bin/python -m music_calendar_finder export --include-history
```

That adds separate `Run History`, `Historical Sources`, `Historical Rejections`, and `Historical Search API Usage` sheets. Optional city workbooks can be enabled with `--write-city-workbooks`.

Run workbook QA after export:

```bash
.venv/bin/python -m music_calendar_finder qa-workbook
```

The QA command fails on Top Sources challenge titles, generic source names, weak article/blog tiers, venue/regional cap violations, count mismatches, and other batch-blocking workbook quality regressions.

## Codex App Development

Open this folder, `music-calendar-source-finder`, in Codex App. Recommended local actions:

```bash
pytest -q
python -m music_calendar_finder --help
python -m music_calendar_finder run-city --city "Austin" --state "TX" --dry-run
python -m music_calendar_finder export
```

Useful git checkpoints:

- Commit after scaffold.
- Commit after importer works.
- Commit after SerpAPI integration works.
- Commit after exporter works.
- Commit after full dry-run pipeline works.

The project intentionally uses plain `sqlite3` and small service modules so each stage can be tested or replaced independently. Search provider code is adapter-based so SerpAPI can later be swapped for Brave Search, Tavily, Google Custom Search, or another provider.
