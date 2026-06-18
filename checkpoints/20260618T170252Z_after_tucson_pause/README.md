# Calendar Ingest Checkpoint: after Tucson pause

Created UTC: 2026-06-18T17:02:52+00:00

## Status

- Scope: cities with population >= 50,000
- Completed cities: 59
- Pending cities: 896
- Processing cities: 0
- Failed cities: 0
- Last completed city: Tucson, AZ
- Next pending city: El Paso, TX

## Saved Files

- Master XLSX snapshot: `checkpoints/20260618T170252Z_after_tucson_pause/master_music_calendar_sources.xlsx`
- SQLite state snapshot: `checkpoints/20260618T170252Z_after_tucson_pause/music_calendar_finder.sqlite`
- Machine-readable status: `status.json`
- Completed city list: `completed_cities.csv`
- Pending queue head: `pending_queue_head.csv`
- Run/checkpoint log: `run.log`

## Resume

```bash
.venv/bin/python -m music_calendar_finder run --min-population 50000 --sleep-seconds-between-cities 10 --yes --force
```

The live runner was stopped after Tucson completed, leaving no city in `processing` state.
