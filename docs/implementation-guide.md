# Implementation guide — Phase 2 (split reference)

This document is an index that points to focused developer guides for each Phase 2 domain. Each domain document explains the implemented module(s), public APIs, examples, and testing guidance.

Refer to the following detailed guides (implementation details):

| Document | Short description | Link |
|---|---|---|
| Docker/compose path discovery — implementation details | Host-side path discovery for containerized services and compose mappings. | ./implementation-details/docker-introspect.md |
| Borg wrapper and connection semantics — implementation details | Implementation details for the borg wrapper, repository URL construction, and connection semantics. | ./implementation-details/borg.md |
| Local state persistence — implementation details | Implementation details for the per-service state store and state file schema. | ./implementation-details/state-store.md |
| Backup orchestration — implementation details | Implementation details for the backup orchestration flow, hooks, and state updates. | ./implementation-details/backup-flow.md |
| Storage box setup — operator guide | Step-by-step instructions to prepare a remote host as a Borg storage box and manage repo keys and passphrases. | ./storage-setup.md |

Use these guides when making changes to the corresponding modules or when writing tests that need to stub or mock behaviors.
