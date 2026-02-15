# Remote archive listing (`remote_listing.py`)

Purpose
- Normalize, filter, sort, group, and render remote Borg archive listings for the `list-remote` CLI command.

Public API
- `process_remote_archives(raw_archives, config, services=None, group_by=None) -> List[RemoteArchiveRecord]`
  - Main entry point for processing raw archive data from `borg list`. Normalizes records, applies optional service filtering, and sorts deterministically.

- `render_tsv(records: List[RemoteArchiveRecord]) -> str`
  - Renders archives as TSV (Tab-Separated Values). Output format: `<archive>\t<time_utc>\t<hostname>\t<service>\t<id_short>`. No headers.

- `render_json(records, group_by=None, service_filter=None) -> str`
  - Renders archives as JSON with schema version 1. Includes `generated_at`, `group_by`, `service_filter`, `archives` array, and optional `groups` object when `group_by="hostname"`.

Data model
- `RemoteArchiveRecord`: Frozen dataclass with fields:
  - `archive`: Archive name
  - `time_utc`: ISO 8601 UTC timestamp
  - `hostname`: Host where archive was created
  - `service`: Service name derived from archive name
  - `id`: Full archive ID (when available from JSON)
  - `id_short`: First 12 characters of ID

Sorting and ordering
- Records are sorted deterministically: service → hostname → time_utc → archive name.
- Empty values sort after non-empty values (using `\xff` as sort key).

Service name extraction
- First attempts extraction from the configured `archive_name_template` (if it contains `{service}`).
- Falls back to matching configured service names as archive name prefixes.

JSON output schema (version 1)
```json
{
  "schema_version": 1,
  "generated_at": "2026-02-15T10:30:00Z",
  "group_by": "hostname" | null,
  "service_filter": ["service1"] | null,
  "archives": [
    {
      "archive": "nextcloud-2026-02-15T10:30:00",
      "time_utc": "2026-02-15T10:30:00",
      "hostname": "server1",
      "service": "nextcloud",
      "id": "abc123...",
      "id_short": "abc123def456"
    }
  ],
  "groups": {
    "server1": [...]
  }
}
```

Testing guidance
- Tests are in [`tests/test_remote_listing.py`](tests/test_remote_listing.py).
- Key test cases: time normalization, service extraction from templates, TSV rendering, JSON schema validation, filtering behavior, sorting determinism.
