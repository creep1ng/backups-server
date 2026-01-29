## Estructura recomendada (lean)

- `backup_tool.py` (entrypoint CLI)
- `config_loader.py` (load + validate YAML, early return)
- `backup_flow.py` (orquestación backup/restore/list)
- `docker_introspect.py` (descubrimiento de rutas desde compose)
- `commands.py` (hooks pre/post, con subprocess seguro)
- `borg.py` (wrapper de invocaciones Borg: create/list/extract)
- `state_store.py` (estado local mínimo por servicio, JSON)
- `retry.py` (reintentos simples con backoff)
- `errors.py` (excepciones propias)

## CLI (argparse)

Comandos:

- `backup --service <name>|--all`
- `restore --service <name> --snapshot <archive_name>|--latest`
- `list-remote [--service <name>] [--format text|json] [--group-by service|hostname]`
- `validate`

Para “listar servicios por servidor”:

- `list-remote --group-by hostname` agrupa por `hostname` expuesto por `borg list` (metadato del archive). [page:1]
- Alternativa (si prefieres no depender de hostname): agrupar por prefijo del nombre del archive, pero esta guía recomienda hostname porque Borg lo expone directamente. [page:1]

## Borg wrapper (subprocess seguro)

### Crear snapshot incremental

Invocación base: `borg create [options] ARCHIVE [PATH...]`. [page:0]

Recomendación: construir `ARCHIVE` como `ssh://USER@HOST:PORT/ABS_REPO_PATH::{service}-{timestamp}` (o el formato equivalente soportado por tu repo remoto). [page:0]

### Streaming para dumps (sin out-of-space)

Dos rutas admitidas por Borg:

- Pasar  como PATH para leer de `stdin` y crear el archivo `stdin` dentro del archive. [page:0]
- Preferible: `-content-from-command` para que Borg gestione el comando y falle sin crear archive si el comando falla (evita “archives truncados”). [page:0]

Implementación práctica:

- En YAML, define `backup_commands.pre` para operaciones ligeras (p.ej. pausar escritura, flush).
- Para dumps grandes, define `streams:` (ver spec de YAML) y en `backup_flow` agrega esas “entradas” como `-content-from-command` en la invocación de `borg create`. [page:0]

### Listado remoto de snapshots

`borg list` lista contenidos de repo o de un archive. [page:1]

Para frontends/parseo estable:

- `borg list --json <REPO>` (solo válido listando repositorio) para obtener salida JSON. [page:1]
- O `borg list --format ... <REPO>` para salida de texto estable; por defecto, al listar archives se puede formatear como `"{archive} {time} [{id}]"`. [page:1]

Además, `borg list` expone claves como `archive`, `id`, `time`, `hostname` y `username` cuando listás archives de un repositorio, lo que habilita `--group-by hostname`. [page:1]

## Descubrimiento de rutas (compose + env)

El backup debe incluir compose files, `.env`, volúmenes y bind mounts. [file:1]

Implementación mínima:

- Parsear YAML del compose y extraer `services.*.volumes`.
- Identificar binds (tienen forma `host_path:container_path[:mode]`) y agregarlos a la lista de `PATH...`.
- Los volúmenes Docker “named volumes” no siempre tienen un path estable directo; en la primera versión puedes requerir `bind mounts` para datos críticos o resolver rutas vía `docker volume inspect` (con subprocess).

## Estado local y reanudación

Requisito: si se interrumpe, debe poder restablecer un trabajo desde el último paso ejecutado. [file:1]

Implementación lean:

- Un JSON por servicio en `/var/lib/backup_tool/state/<service>.json` con:
    - `last_success_archive`
    - `last_step` (enum simple: `pre_hooks`, `borg_create`, `post_hooks`)
    - `updated_at`

## systemd (service + timer)

Requisito: ejecutable por unidad systemd y timer. [file:1]

Entrega mínima:

- `backup_tool.service`: ejecuta `backup_tool.py backup --all`.
- `backup_tool.timer`: periodicidad (ej. diario), con `Persistent=true` para que corra tras downtime.