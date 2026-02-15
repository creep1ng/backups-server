# Storage box setup

This guide explains how to prepare a remote host to act as a Borg storage box and how to initialize a Borg repository for both interactive and unattended backups. All example commands use concrete hosts and paths (replace these only where noted).

## Prerequisites

- SSH access to the storage host (example: `backup@storage.example.com`).
- `borg` installed on both the client (backup server) and the storage host. Use the same Borg version on both sides where possible to avoid compatibility issues.
- A dedicated Unix user for backups on the storage host (we use `backup` in examples).

## 1) Create a dedicated backup user and SSH keys

On the storage host (as a user with sudo privileges):

```bash
sudo useradd -m -s /bin/bash backup
sudo passwd -l backup   # optional: lock account password-based login
```

On the backup server (client), generate an SSH ed25519 key for the backup user:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/backup_borg_key -N ""
```

Copy the public key to the storage host. We recommend restricting the key to running `borg serve` only (see below) to improve security.

Example (simple copy using ssh-copy-id):

```bash
ssh-copy-id -i ~/.ssh/backup_borg_key.pub backup@storage.example.com
```

Or use `scp` and then append the allowed command entry manually on the storage host.

Secure `authorized_keys` entry (recommended)

On the storage host, edit `/home/backup/.ssh/authorized_keys` and add a single line that restricts the key to run `borg serve` only:

```text
command="borg serve --restrict-to-repository /srv/backups/repo",no-pty,no-agent-forwarding,no-X11-forwarding ssh-ed25519 AAAA...rest-of-key... comment
```

### Why restrict to `borg serve`?
> Restricting the key to `borg serve` ensures that the exposed credential can only be used to access the Borg repository and cannot be used as a general login shell or to run arbitrary commands on the storage host. This reduces the blast radius if the key is compromised.

## 2) Create server-side directories and set permissions

On the storage host (as sudo):

```bash
sudo mkdir -p /srv/backups/repo
sudo chown -R backup:backup /srv/backups
sudo chmod 700 /srv/backups
```

If the storage host enforces SELinux or AppArmor, ensure policies allow `borg` access to `/srv/backups`. You may need to label the path (SELinux) or adjust AppArmor profiles.

## 3) Initialize a Borg repository (encryption choices)

Borg supports multiple encryption modes. Two common choices:

- `repokey-blake2` (recommended for convenience): borg stores the encryption key inside the repo protected by a passphrase. You can recover with the passphrase.
- `keyfile` (keyfile stored outside the repo): you manage the keyfile separately — useful for stricter separation but requires secure distribution of the keyfile to each client.

### Example: initialize with passphrase (repokey-blake2)

```bash
# On your backup server (client) or via remote borg init over ssh
BORG_PASSPHRASE="your-strong-passphrase" borg init --encryption=repokey-blake2 backup@storage.example.com:/srv/backups/repo
```

Notes:
- The above command creates the repo and stores the key material in the repo protected by the passphrase. Keep the passphrase safe.

### Example: initialize with keyfile encryption and export the key

```bash
# On the storage host, as backup user (example)
ssh backup@storage.example.com 'sudo -u backup borg init --encryption=keyfile /srv/backups/repo'

# On the storage host, find the generated keyfile and copy it securely to the client
# Example (on storage host):
sudo -u backup borg key export /srv/backups/repo /tmp/repo-key
scp /tmp/repo-key backup@backup-server:/etc/backup/repo-key
sudo chown backup:backup /etc/backup/repo-key && sudo chmod 600 /etc/backup/repo-key
```

Key management and passphrase change

- Export and import keys:
  - `borg key export /path/to/repo /tmp/keyfile`
  - `borg key import /path/to/repo /tmp/keyfile`

- Change a repo passphrase:

```bash
borg key change-passphrase backup@storage.example.com:/srv/backups/repo
```

Warning: losing key material or passphrase will make the repository unreadable. Keep backups of keyfiles/passphrases in secure vaults.

## 4) Verify the repository and perform a test backup

List repo contents and metadata to verify connectivity:

```bash
borg list backup@storage.example.com:/srv/backups/repo
borg info backup@storage.example.com:/srv/backups/repo
```

Create a quick test archive (client side):

```bash
BORG_PASSPHRASE="your-strong-passphrase" borg create backup@storage.example.com:/srv/backups/repo::test-archive /etc/hosts
```

Extract or dry-run an extract to verify contents (dry-run example):

```bash
borg extract --dry-run backup@storage.example.com:/srv/backups/repo::test-archive /etc/hosts
```

## 5) Pruning and maintenance

Run prune on a schedule to remove old archives according to your retention policy:

```bash
borg prune --keep-daily 7 --keep-weekly 4 --keep-monthly 12 backup@storage.example.com:/srv/backups/repo
```

Run repository checks regularly (verify-data is more expensive):

```bash
borg check --verify-data backup@storage.example.com:/srv/backups/repo
```

## 6) Troubleshooting tips

- SSH connection issues: run `ssh -vv backup@storage.example.com` to debug the SSH handshake and authorized_keys restrictions.
- Borg connectivity: `borg list` and `borg info` will surface repo-level errors.
- Permissions: ensure `/srv/backups` and its children are owned by `backup:backup` and have mode `700` or similar restrictive settings.
- Systemd logs: `journalctl -u <service-name>` to inspect backup service failures.

## Security considerations

- Restrict the backup SSH key in `authorized_keys` to `borg serve` to limit the key's capabilities.
- Protect keyfiles and passphrases with strict filesystem permissions and, where possible, store them in a secure vault.
- Test key rotation and recovery procedures (borg key export/import) before relying on them in production.

