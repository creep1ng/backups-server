> Asumo iteración semanal con entregables pequeños y testeables.

## Fase 0 — Preparación (0.5–1 día)

- Definir repositorio, packaging mínimo (script ejecutable + requirements).
- Acordar convención de naming de snapshots (por servicio) usando placeholders o timestamp fijo. [page:0]

## Fase 1 — Config + CLI base (1–2 días)

- Implementar `validate` con parseo YAML y validación estricta (early return).
- Implementar CLI con `backup`, `restore` (stub), `list-remote` (stub).
- Tests manuales: YAML inválido, campos faltantes, paths inexistentes.

## Fase 2 — Backup funcional (2–4 días)

- Implementar descubrimiento mínimo de rutas (compose + env + extra_paths).
- Implementar hooks `backup_commands.pre/post`. [file:1]
- Implementar `borg create` para snapshots incrementales sin tar intermedio. [page:0]
- Guardar `last_success_archive` en estado local.

## Fase 3 — Listado remoto (1–2 días)

- Implementar `list-remote` usando `borg list --json` o `-format`. [page:1]
- Implementar filtros `-service` y agrupación `-group-by hostname` usando el metadato `hostname`. [page:1]
- Ajustar salida para ser “script-friendly” (una línea por snapshot o JSON).

## Fase 4 — Restore usable (2–4 días)

- Implementar `borg extract` (restore a staging dir).
- Implementar hooks `restore_commands.pre/post`. [file:1]
- Añadir opción `-latest` (usa estado local y/o `borg list` para resolver snapshot).

## Fase 5 — Robustez y hardening (2–3 días)

- Señales SIGINT/SIGTERM: guardar `last_step` y salir con códigos adecuados.
- Reintentos con backoff para operaciones Borg/SSH.
- Validaciones de permisos (ssh key, rutas sensibles).
- Entrega de unit/timer systemd y documentación de despliegue. [file:1]