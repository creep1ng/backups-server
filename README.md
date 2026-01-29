# Backups Tool (Phase 0 & Phase 1)

This repository contains the initial phases (Preparation and Config + Base CLI)
of a backup tool. Phase 0 establishes the repository layout and Phase 1 adds
configuration loading/validation and a base CLI.

Installation
------------

Create a virtualenv and install requirements:

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

Usage
-----

Validate a configuration file:

python backup_tool.py validate --config tests/fixtures/valid_config.yaml

Example output on success:

Configuration is valid

