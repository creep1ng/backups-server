# Docker/compose path discovery

This document describes the implementation and public API for the path discovery logic implemented in [`docker_introspect.py`](docker_introspect.py:1).

Purpose
- Find host-side filesystem paths that should be included in a backup for a given service. Discovery combines:
  - the configured `compose_file` (the compose YAML itself),
  - any `env_files` referenced by the service config,
  - explicit `extra_paths` listed in the service config,
  - host-side bind mounts expressed in `services.*.volumes` entries of the compose YAML.

Public API
- `discover_paths(service_config: dict) -> List[str]`
  - `service_config` keys used: `compose_file` (required), optional `env_files` (list[str]), `extra_paths` (list[str]).
  - Returns a deduplicated list of absolute host paths (List[str]). Relative paths in compose YAML are resolved relative to the compose file directory.
  - Behavior: missing or unreadable candidate paths are logged and skipped. If the compose YAML fails to parse, a `ConfigValidationError` is raised.

Compose volume forms handled
- Short form strings like `./data:/app/data` or `/abs/path:/container/path:ro` — the left-hand side (host path) is extracted and resolved.
- Long-form entries with `type: bind` and `source: /host/path` — `source` is included.
- Named volumes (e.g., `myvolume:/container/path`) are skipped by default (no host path to include). Resolving named volumes via `docker volume inspect` is out of scope for Phase 2.

Examples

```python
from docker_introspect import discover_paths

svc = {
    'name': 'web',
    'compose_file': './docker-compose.yml',
    'env_files': ['./.env'],
    'extra_paths': ['/var/lib/web/data']
}

paths = discover_paths(svc)
print(paths)
```

Testing guidance
- Unit tests should provide a small compose YAML fixture (see `tests/fixtures/docker-compose.yml`) and verify the returned list includes expected host paths and excludes named volumes.

Operational notes
- Discovery is intentionally conservative: it prefers explicit host paths and logs unresolved or missing paths rather than failing a run.

