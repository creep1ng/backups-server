## Reglas generales

- YAML debe parsear correctamente; ante error de sintaxis se aborta la ejecución (early return).
- Tipos: solo built-ins (dict/list/str/int/bool).
- No se soportan múltiples Storage Boxes: una sola sección `storage_box`.

## Top-level

```yaml
version: 1

storage_box: <storage_box>

borg: <borg_global>

compression: <compression>

services:
  - <service>
  - <service>

```

## `storage_box`

```yaml
storage_box:
  host: "u12345.your-storagebox.de"
  port: 22
  user: "u12345"
  ssh_key_path: "/home/backup/.ssh/id_ed25519"
  repo_path: "/home/u12345/borg-repo"

```

Validaciones:

- `host` (str) requerido
- `port` (int) opcional, default 22
- `user` (str) requerido
- `ssh_key_path` (str) requerido, debe existir y ser legible
- `repo_path` (str) requerido, path remoto del repo Borg (único)

## `borg` (global)

```yaml
borg:
  # nombre de archive: se recomienda incluir service + timestamp
  archive_name_template: "{service}-{now:%Y-%m-%dT%H:%M:%S}"
  extra_args: ["--stats"]
  # opcional: flags de seguridad/rendimiento
  files_cache: "ctime,size,inode"

```

Notas:

- Borg soporta placeholders en el nombre del archive como `{now}`, `{hostname}`, `{user}`, etc., así que el template puede apoyarse en eso. [page:0]

## `compression`

```yaml
compression:
  algorithm: "zstd"   # borg lo recibe como --compression zstd,<level>
  level: 5

```

Validaciones:

- `algorithm` en {"zstd","lz4","zlib","lzma","none","auto"} (según lo que soporta tu instalación Borg; en el MVP limitar a {"zstd","none"}).
- `level` int (rango sugerido 1–19 para zstd, pero la validación puede ser laxa y dejar que Borg falle).

## `services[]`

```yaml
services:
  - name: "nextcloud"
    compose_file: "/srv/nextcloud/docker-compose.yml"
    env_files:
      - "/srv/nextcloud/.env"
    extra_paths:
      - "/srv/nextcloud/data"

    backup_commands:
      pre:
        - "docker compose -f /srv/nextcloud/docker-compose.yml exec -T db sh -lc 'echo prehook'"
      post: []

    restore_commands:
      pre: []
      post:
        - "docker compose -f /srv/nextcloud/docker-compose.yml exec -T db sh -lc 'echo posthook'"

    # Streams: para datos grandes generados por comando (sin archivo temporal).
    streams:
      - name: "db.sql"
        command: ["docker", "compose", "-f", "/srv/nextcloud/docker-compose.yml", "exec", "-T", "db", "pg_dumpall", "-U", "user"]

```

Validaciones:

- `name` (str) requerido, único.
- `compose_file` (str) requerido, debe existir.
- `env_files` (list[str]) opcional.
- `extra_paths` (list[str]) opcional.
- `backup_commands` / `restore_commands` opcional:
    - `pre` y `post` son list[str], comandos ejecutados con subprocess (sin shell).
- `streams` opcional:
    - Cada stream define `name` (str) y `command` (list[str]).
    - La implementación debe mapear cada stream a `borg create --content-from-command` para evitar dumps truncados y evitar out-of-space por archivos temporales. [page:0]

## Ejemplo completo mínimo

```yaml
version: 1

storage_box:
  host: "u12345.your-storagebox.de"
  port: 22
  user: "u12345"
  ssh_key_path: "/home/backup/.ssh/id_ed25519"
  repo_path: "/home/u12345/borg-repo"

borg:
  archive_name_template: "{service}-{now:%Y-%m-%dT%H:%M:%S}"
  extra_args: ["--stats"]

compression:
  algorithm: "zstd"
  level: 5

services:
  - name: "nextcloud"
    compose_file: "/srv/nextcloud/docker-compose.yml"
    env_files: ["/srv/nextcloud/.env"]
    extra_paths: []
    backup_commands: { pre: [], post: [] }
    restore_commands: { pre: [], post: [] }
    streams: []

```