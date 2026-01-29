# Componentes principales

## Servidor

Es el dispositivo que contiene los archivos valiosos a respaldar, así como el responsable de ejecutar el servicio de backup. Los diferentes servicios que serán respaldados estarán desplegados mediante contenedores Docker, siempre orquestrados mediante Docker Compose.

## Datos

Son los componentes a respaldar. Al momento de hoy, se considera que un backup completo consta de:

1. Archivos de docker compose.
2. Archivos `.env` de cada servicio
3. Volúmenes Docker.
4. Bind mounts.

## Storage Box

Es el servidor destino que preservará los datos. La idea es emplear una sub-cuenta de la Storage Box dedicada a cada alcance (es decir, una para backups de empresa 1, otra para backups personales, y así). El aplicativo debe recibir a qué sub-cuenta subir cada respaldo.

Para preservar la integridad se configurarán en todas las sub-accounts borg en modo [append-only](https://docs.hetzner.com/storage/storage-box/access/access-ssh-rsync-borg/#append-only-mode), garantizando así que aún en entornos donde el servidor está comprometido no puedan eliminarse los respaldos.

La subida deberá hacerse a través de un protocolo que opere sobre SSH, como SFTP o Rsync. La Storage Box no tiene password configurada, así que la única forma de acceder es a través de llaves SSH.

## Aplicativo

Es el componente encargado de reconocer los volúmenes, bind mounts, archivos de configuación para subirlos a Storage Box. Gestiona la configuración de la compresión, la subida mediante el protocolo sobre SFTP, parámetros de borg, entre otros.

# Necesidades

1. El servicio es configurable a través de un archivo, para indicar:
    1. Algoritmos y niveles de compresión.
    2. Credenciales de acceso a la Storage Box.
    3. Servicio de docker, especificando sus datos.
        1. En caso de que el servicio tenga componentes cuyos datos puedan ser invalidados (por ejemplo, bases de datos que tengan scripts personalizados para backup), debe permitir ejecutar comandos personalizados para cada servicio del archivo Compose, tanto como para la fase de backup como para la fase de restore.
2. El servicio ofrece una funcionalidad para respaldar de manera incremental los datos especificados en el archivo de configuración, siguiendo los comandos personalizados de respaldo.
3. El servicio ofrece una funcionalidad para restablecer los datos especificados en el archivo de configuración, siguiendo los comandos personalizados de restore.
4. El usuario puede lanzar trabajos de respaldo manualmente.
5. El servicio puede ejecutarse a través de unidad systemd, y ofrece tanto unidad como timer.
6. El servicio hace logs sobre el status de la carga, informando en caso de error o de trabajo de subida terminado.
7. El servicio, en caso de ser interrumpido, permite restablecer un trabajo desde el último paso ejecutado.
8. El servicio, en caso de emplear compresión, permite limitar la cantidad de CPUs empleadas a la hora de realizar la compresión.

# Alcance y objetivos

El servidor origen ejecuta el servicio de backups y aloja los datos a respaldar; los servicios están desplegados con contenedores Docker orquestados con Docker Compose. [file:1]

Un “backup completo” incluye: archivos de Docker Compose, archivos `.env`, volúmenes Docker y bind mounts. [file:1]

El destino es una Storage Box accesible por SSH (sin password, usando llaves), y los repositorios Borg se configuran en modo append-only para mitigar borrados incluso si el servidor origen está comprometido. [file:1]

# Tecnologías

- Lenguaje: Python 3.x (script/CLI), estilo idiomático y dependencias mínimas (stdlib + parser YAML).
- Backup incremental/deduplicación/compresión/cifrado: BorgBackup como motor único (no se soporta rsync/sftp). [page:0]
- Transporte: SSH (el propio Borg opera sobre repositorios remotos vía SSH). [page:0]
- Orquestación de servicios: Docker Compose (para descubrir volúmenes/binds y para ejecutar hooks pre/post). [file:1]
- Scheduling: systemd service + systemd timer (unidad y timer provistos por el proyecto). [file:1]

# Componentes y responsabilidades

- CLI (Python):
    - `validate`: valida sintaxis/semántica del YAML y termina en early return si hay errores.
    - `backup`: ejecuta respaldo incremental por servicio, respetando hooks y estado.
    - `restore`: restaura desde un snapshot remoto.
    - `list-remote`: lista snapshots remotos del repo (y puede agrupar/filtrar).
- Descubrimiento de datos:
    - Parseo del `compose_file` para encontrar bind mounts y/o rutas relevantes; además incluye `.env` y archivos compose como parte del backup. [file:1]
- Hooks por servicio:
    - Permite comandos personalizados para backup y restore (p.ej. dumps de DB antes de respaldar, y restore después). [file:1]

# Decisiones clave (on-the-fly y naming)

El backup **no** genera un archivo `.tar` intermedio: se invoca `borg create ... [PATH...]`, y Borg recorre los paths y crea el archive directamente (con compresión/deduplicación), evitando el riesgo de out-of-space por artefactos temporales grandes. [page:0]

Para datos que se generan por comando (p.ej. dumps), el diseño usa `--content-from-command` o entrada por `stdin` (path `-`) para que el contenido se “streamée” al archive sin persistirlo completo en disco. [page:0]

El nombre del snapshot sigue un formato estable para soportar filtros: `"{service}-{now:%Y-%m-%dT%H:%M:%S}"`, aprovechando placeholders soportados por Borg. [page:0]

# Patrones y convenciones

- Early return: si el YAML no parsea o no valida, la ejecución aborta antes de tocar datos.
- SSH:
    - Uso de llave privada con permisos restrictivos.
    - Invocaciones con `subprocess.run([...], shell=False)` para reducir riesgo de inyección.
- Append-only remoto (Borg): defensa ante borrados maliciosos desde origen. [file:1]
- Reintentos:
    - Reintento con backoff solo para operaciones de red/IO (por ejemplo `borg create`, `borg list`), con límites conservadores.
- Reanudación:
    - Estado local mínimo por servicio (último paso completado) para reiniciar tras interrupciones. [file:1]