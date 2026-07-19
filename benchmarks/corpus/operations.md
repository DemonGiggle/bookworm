# Backup operations

Create a backup before deployment. Run `sha256sum release.tar` and record the digest. If deployment fails, restore the previous archive and restart the service.

| Check | Expected |
| --- | --- |
| Free disk | At least 2 GB |
| Health endpoint | HTTP 200 |

The backup requirement is intentionally repeated: create a backup before deployment. This tests topic deduplication.

## Long troubleshooting section

Inspect logs, confirm permissions, compare the recorded checksum, verify the health endpoint, and roll back only when the new service cannot pass its checks. Do not erase the previous archive during diagnosis. Repeat these checks for each affected host while keeping the recorded evidence attached to that host.
