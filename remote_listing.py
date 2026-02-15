"""Remote archive listing module.

Provides normalization, filtering, sorting, grouping, and rendering
for remote Borg archive listings.
"""

from __future__ import annotations

import datetime
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# Schema version for JSON output
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class RemoteArchiveRecord:
    """Represents a remote archive record with normalized fields.

    Fields:
        archive: Archive name
        time_utc: Archive creation time in ISO 8601 UTC format
        hostname: Host where archive was created
        service: Service name derived from archive name
        id: Full archive ID (if available)
        id_short: Short archive ID (first 12 characters, if id available)
    """

    archive: str
    time_utc: str = ""
    hostname: str = ""
    service: str = ""
    id: str = ""
    id_short: str = ""


def compute_id_short(id_value: str) -> str:
    """Compute short ID from full archive ID.

    Args:
        id_value: Full archive ID (hex string)

    Returns:
        First 12 characters of the ID, or empty string if invalid
    """
    if not id_value:
        return ""
    # Archive IDs are typically 64-character hex strings
    # Take first 12 characters for short ID
    return id_value[:12]


def normalize_time(time_value: Any) -> str:
    """Normalize time value to ISO 8601 UTC format.

    Args:
        time_value: Time value from Borg (could be string, int timestamp, etc.)

    Returns:
        ISO 8601 formatted time string, or empty string if unavailable
    """
    if not time_value:
        return ""

    if isinstance(time_value, str):
        # Already a string - try to parse and reformat
        # Common formats from Borg: "2023-01-15T10:30:00.000000"
        # or Unix timestamp as string
        try:
            # Try parsing as ISO format first
            dt = datetime.datetime.fromisoformat(time_value.replace("Z", "+00:00"))
            return dt.strftime("%Y-%m-%dT%H:%M:%S")
        except (ValueError, AttributeError):
            pass

        # Try parsing as Unix timestamp
        try:
            ts = float(time_value)
            dt = datetime.datetime.utcfromtimestamp(ts)
            return dt.strftime("%Y-%m-%dT%H:%M:%S")
        except (ValueError, TypeError):
            pass

        # Return as-is if we can't parse it
        return time_value

    if isinstance(time_value, (int, float)):
        # Unix timestamp
        try:
            dt = datetime.datetime.utcfromtimestamp(float(time_value))
            return dt.strftime("%Y-%m-%dT%H:%M:%S")
        except (ValueError, OSError):
            return ""

    return str(time_value)


def extract_service_from_template(
    archive_name: str,
    template: str,
) -> Optional[str]:
    """Extract service name from archive name when template contains {service}."""
    pattern_parts: list[str] = []
    i = 0
    has_service = False

    while i < len(template):
        if template.startswith("{service}", i):
            pattern_parts.append(r"(?P<service>.+?)")
            has_service = True
            i += len("{service}")
            continue
        if template.startswith("{timestamp}", i):
            pattern_parts.append(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
            i += len("{timestamp}")
            continue
        if template.startswith("{now:", i):
            end = template.find("}", i)
            if end == -1:
                end = len(template) - 1
            pattern_parts.append(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
            i = end + 1
            continue
        if template[i] == "{":
            end = template.find("}", i)
            if end == -1:
                end = i
            pattern_parts.append(r".+?")
            i = end + 1
            continue
        pattern_parts.append(re.escape(template[i]))
        i += 1

    if not has_service:
        return None

    pattern = "^" + "".join(pattern_parts) + "$"
    match = re.match(pattern, archive_name)
    if not match:
        return None

    return match.groupdict().get("service")


def extract_service_from_config(
    archive_name: str,
    service_names: List[str],
) -> Optional[str]:
    """Extract service name by matching configured service names as prefix.

    This is a fallback when the template doesn't contain {service}.

    Args:
        archive_name: The archive name
        service_names: List of configured service names

    Returns:
        Matching service name, or None if no match
    """
    # Sort service names by length (longest first) to match most specific first
    # This prevents "myservice" from matching before "myservice-specific"
    sorted_services = sorted(service_names, key=len, reverse=True)

    for service in sorted_services:
        if archive_name.startswith(service + "-") or archive_name == service:
            return service

    return None


def normalize_archive_record(
    raw_record: Dict[str, Any],
    config: Dict[str, Any],
) -> RemoteArchiveRecord:
    """Normalize a Borg archive record to RemoteArchiveRecord.

    Handles both JSON format and TSV fallback format records.
    Tolerates missing keys and provides best-effort mapping.

    Args:
        raw_record: Raw record from borg list (JSON or parsed TSV)
        config: Configuration dictionary (to get template and service names)

    Returns:
        Normalized RemoteArchiveRecord
    """
    # Extract basic fields
    archive = raw_record.get("name", raw_record.get("archive", ""))

    # Time - handle various formats
    time_value = raw_record.get("time", raw_record.get("time_utc", ""))
    time_utc = normalize_time(time_value)

    # Hostname
    hostname = raw_record.get("hostname", "")

    # Archive ID - handle both 'id' and 'id' fields
    archive_id = raw_record.get("id", "")
    if not archive_id:
        # Some Borg versions use 'archive_id' or other fields
        archive_id = raw_record.get("archive_id", "")
    id_short = compute_id_short(archive_id)

    # Extract service name
    borg_cfg = config.get("borg", {})
    template = borg_cfg.get("archive_name_template", "{service}-{timestamp}")

    service = ""

    # First try: extract from template
    service = extract_service_from_template(archive, template) or ""

    # Second try: match against configured service names
    if not service:
        services_list = config.get("services", [])
        service_names = [s.get("name", "") for s in services_list if s.get("name")]
        service = extract_service_from_config(archive, service_names) or ""

    return RemoteArchiveRecord(
        archive=archive,
        time_utc=time_utc,
        hostname=hostname,
        service=service,
        id=archive_id,
        id_short=id_short,
    )


def filter_by_services(
    records: List[RemoteArchiveRecord],
    services: Optional[List[str]],
) -> List[RemoteArchiveRecord]:
    """Filter archives by service names.

    If services is None or empty, returns all records.
    If services is provided, excludes records where service is unknown.

    Args:
        records: List of archive records
        services: Optional list of service names to filter by

    Returns:
        Filtered list of records
    """
    if not services:
        return records

    # Convert to set for O(1) lookup
    service_set = set(services)

    filtered = []
    for record in records:
        # Exclude records where service is unknown when filter is active
        if not record.service and service_set:
            continue
        if record.service in service_set:
            filtered.append(record)

    return filtered


def sort_records(
    records: List[RemoteArchiveRecord],
    group_by: Optional[str] = None,
) -> List[RemoteArchiveRecord]:
    """Sort records deterministically.

    Default sort order: service ASC, time_utc DESC, archive ASC.
    When group_by='hostname': hostname ASC, service ASC, time_utc DESC, archive ASC.
    Empty values sort after non-empty values.

    Args:
        records: List of archive records
        group_by: Optional grouping key ("hostname" or None)

    Returns:
        Sorted list of records
    """

    def sort_key(record: RemoteArchiveRecord) -> tuple:
        # For descending time, we invert by using a prefix that sorts in reverse
        # Empty strings sort last using high unicode character
        service_key = record.service or "\xff"
        hostname_key = record.hostname or "\xff"
        time_key = record.time_utc or "\xff"
        archive_key = record.archive

        # For descending time, we need to invert the string comparison
        # We do this by mapping each character to its inverse
        # A simpler approach: use a tuple (is_empty, inverted_time)
        if record.time_utc:
            # Invert time string for descending order
            # This works because ISO 8601 timestamps have fixed-width numeric chars
            inverted_time = "".join(
                chr(0x10FFFF - ord(c)) if c.isdigit() else c for c in record.time_utc
            )
            time_sort = (0, inverted_time)
        else:
            time_sort = (1, "")  # Empty times sort last

        if group_by == "hostname":
            return (hostname_key, service_key, time_sort, archive_key)
        else:
            return (service_key, time_sort, archive_key)

    return sorted(records, key=sort_key)


def group_by_hostname(
    records: List[RemoteArchiveRecord],
) -> Dict[str, List[RemoteArchiveRecord]]:
    """Group records by hostname.

    Args:
        records: List of archive records (should be pre-sorted)

    Returns:
        Dictionary mapping hostname to list of records
    """
    groups: Dict[str, List[RemoteArchiveRecord]] = {}

    for record in records:
        hostname = record.hostname or ""
        if hostname not in groups:
            groups[hostname] = []
        groups[hostname].append(record)

    return groups


def sanitize_field(value: str) -> str:
    """Sanitize a field value for TSV output.

    Replaces tabs and newlines with spaces to ensure proper TSV formatting.

    Args:
        value: Field value to sanitize

    Returns:
        Sanitized field value
    """
    if not value:
        return ""
    # Replace tabs and newlines with spaces
    return value.replace("\t", " ").replace("\n", " ").replace("\r", " ")


def render_tsv(records: List[RemoteArchiveRecord]) -> str:
    """Render archives as TSV (Tab-Separated Values).

    Output format (no header):
    <archive>\t<time_utc>\t<hostname>\t<service>\t<id_short>

    Args:
        records: List of archive records

    Returns:
        TSV formatted string
    """
    lines = []
    for record in records:
        fields = [
            sanitize_field(record.archive),
            sanitize_field(record.time_utc),
            sanitize_field(record.hostname),
            sanitize_field(record.service),
            sanitize_field(record.id_short),
        ]
        lines.append("\t".join(fields))

    return "\n".join(lines)


def render_json(
    records: List[RemoteArchiveRecord],
    group_by: Optional[str] = None,
    service_filter: Optional[List[str]] = None,
) -> str:
    """Render archives as JSON.

    JSON output schema:
    {
        "schema_version": 1,
        "generated_at": "ISO timestamp",
        "group_by": "hostname" | null,
        "service_filter": ["service1", ...] | null,
        "archives": [
            {
                "archive": "...",
                "time_utc": "...",
                "hostname": "...",
                "service": "...",
                "id": "...",
                "id_short": "..."
            },
            ...
        ],
        "groups": {  // present only when group_by == "hostname"
            "hostname1": [...],
            "hostname2": [...],
            ...
        }
    }

    Args:
        records: List of archive records
        group_by: Optional grouping key ("hostname" or None)
        service_filter: Optional list of services that were filtered

    Returns:
        JSON formatted string
    """
    # Generate output timestamp
    generated_at = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    # Build archive list
    archives_list = []
    for record in records:
        archives_list.append(
            {
                "archive": record.archive,
                "time_utc": record.time_utc,
                "hostname": record.hostname,
                "service": record.service,
                "id": record.id,
                "id_short": record.id_short,
            }
        )

    # Build output
    output: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "group_by": group_by,
        "service_filter": service_filter,
        "archives": archives_list,
    }

    # Add groups if grouping by hostname
    if group_by == "hostname":
        groups = group_by_hostname(records)
        # Convert groups to same format as archives
        formatted_groups: Dict[str, List[Dict[str, str]]] = {}
        for hostname, group_records in groups.items():
            formatted_groups[hostname] = [
                {
                    "archive": r.archive,
                    "time_utc": r.time_utc,
                    "hostname": r.hostname,
                    "service": r.service,
                    "id": r.id,
                    "id_short": r.id_short,
                }
                for r in group_records
            ]
        output["groups"] = formatted_groups

    return json.dumps(output, indent=2)


def process_remote_archives(
    raw_archives: List[Dict[str, Any]],
    config: Dict[str, Any],
    services: Optional[List[str]] = None,
    group_by: Optional[str] = None,
) -> List[RemoteArchiveRecord]:
    """Process raw archive data into normalized records.

    This is the main entry point for processing remote archives.

    Args:
        raw_archives: Raw archive data from borg list
        config: Configuration dictionary
        services: Optional service filter
        group_by: Optional grouping key ("hostname" or None)

    Returns:
        List of processed RemoteArchiveRecord
    """
    # Normalize all records
    normalized = [normalize_archive_record(raw, config) for raw in raw_archives]

    # Filter by services
    filtered = filter_by_services(normalized, services)

    # Sort deterministically (pass group_by for proper ordering)
    sorted_records = sort_records(filtered, group_by=group_by)

    return sorted_records
