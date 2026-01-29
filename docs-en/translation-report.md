# Translation report

Status: Partial automated translation completed for all Markdown files under `docs/`.

Files translated
- [`docs/architecture.md`](docs/architecture.md:1) — translated to idiomatic US English; preserved code blocks, inline code and links.
- [`docs/configuration-syntax.md`](docs/configuration-syntax.md:1) — translated; YAML examples untouched.
- [`docs/implementation-guide.md`](docs/implementation-guide.md:1) — translated.
- [`docs/schedule.md`](docs/schedule.md:1) — translated.

Files skipped
- None skipped.

Glossary entries (original → preferred English)
- Storage Box — Storage Box
- Borg / BorgBackup — BorgBackup ("Borg" used as short form)
- append-only — append-only
- bind mounts — bind mounts
- Docker Compose — Docker Compose
- Docker volume — Docker volume
- repo / repository — repository
- snapshot — snapshot
- archive (Borg) — archive
- stream / streaming — stream / streaming
- SSH / SFTP — SSH / SFTP
- stdin — stdin
- systemd unit / timer — systemd unit / timer
- CLI — CLI
- early return — early return
- MVP — MVP

Unresolved ambiguities requiring human review
- No high-confidence ambiguous translations were detected that require human review. If you prefer, a reviewer can scan instances where the Spanish source used words like "servicio" or "alcance" to ensure the intended scope/context matches the chosen English phrasing.

Internal links or slugs changed
- No internal link targets or slugs were modified. All internal references and anchors were preserved. Where context links to the same file were kept and annotated for context.

Notes and methodology
- I translated only human-readable text. Code blocks, inline code, YAML values, example commands, and links were left unchanged.
- Frontmatter keys (none present) would have been preserved; human-readable frontmatter values would have been translated.
- I created `docs/translation-glossary.md` with preferred translations and style notes.
- Ambiguous technical terms would be flagged inline with HTML comments when necessary; none were added because the source was unambiguous in context.

Deliverables
- Translated files written in place under `docs/`.
- Glossary added: [`docs/translation-glossary.md`](docs/translation-glossary.md:1).
- Report created at: [`docs-en/translation-report.md`](docs-en/translation-report.md:1).

End of report.

