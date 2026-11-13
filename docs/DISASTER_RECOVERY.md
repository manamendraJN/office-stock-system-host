# Disaster Recovery Plan — Office Stock System (OCI Always Free, $0)

**Goal:** if the server, the database or the OCI account is lost, the website and its data come back, and nothing in this plan costs money.

| Target | Value | How it is met |
|---|---|---|
| Max data loss (RPO) | 6 hours | backup every 6 h, copied off the server daily |
| Time to recover (RTO) | 1–2 hours | rebuild from GitHub + latest backup (Section 5) |
| Monthly cost | Rs. 0 | only Always Free resources, no upgrade to Pay As You Go |

Labels: **[PC]** PowerShell on your Windows computer · **[SERVER]** SSH session on Ubuntu · **[CONSOLE]** OCI website.
Things marked ✅ were checked against this repository. Things marked ⚠ depend on your live server or Oracle's current rules.

## Connect to OCI (used by every step below)

**[PC]**
```powershell
cd "D:\Office Works\Heritage_Crops\Office_Stock\OCI"
ssh -i .\ssh-key-2026-10-27.key ubuntu@130.210.8.169
```
**[SERVER]**
```bash
cd ~/inventory-system
```
If SSH says `Bad permissions` / `UNPROTECTED PRIVATE KEY FILE` (happens after moving or copying the key), **[PC]**:
```powershell
cd "D:\Office Works\Heritage_Crops\Office_Stock\OCI"
icacls.exe .\ssh-key-2026-10-27.key /inheritance:r
icacls.exe .\ssh-key-2026-10-27.key /grant:r "$($env:USERNAME):(R)"
icacls.exe .\ssh-key-2026-10-27.key /remove "NT AUTHORITY\Authenticated Users" /remove "BUILTIN\Users"
icacls.exe .\ssh-key-2026-10-27.key
```
The last command should list only your user, Administrators and SYSTEM. After a rebuild on a new instance, replace the IP (and the key file name if you created a new key pair).

---

## 1. What must be protected

| Asset | Where it lives | Protected today? | Action |
|---|---|---|---|
| Database (all stock, purchases, users) | SQLite in Docker volume `app_data` → `/srv/app/data/db.sqlite3` ✅ | Yes: automatic backup every 6 h (Step 2) | Copy off the server (Steps 3–4) |
| **Company logo upload** | `/srv/app/media/company/` **inside the container** ✅ | **No.** Not in a volume and not in the DB backup. Lost on every `docker compose up -d --build`. | **Fix first (Section 2, step 1)** |
| `.env` (secret key, admin password) | Server only; git-ignored ✅ | No | Encrypted copy on your PC |
| Application code | GitHub | Yes | Keep `main` pushed |
| TLS certificate | Docker volume `caddy_data` | Not needed | Caddy re-issues automatically |
| SSH private key (`*.key`) | Your PC | **Single copy** | Keep a second copy (USB or password manager) |
| Domain / DNS | Your DNS provider | Outside this system | Know the login; keep the TTL low (300 s) |

---

## 2. One-time setup

### Step 1 — Put the logo inside the database volume (do this first)
[SERVER] Add one line to `.env` (no code change needed, `MEDIA_ROOT` is already read by `config/settings.py`):

```bash
cd ~/inventory-system
echo 'MEDIA_ROOT=/srv/app/data/media' >> .env
docker compose up -d
```

Then re-upload the logo in **Settings → Company logo** (the old file was most likely lost when the container was last rebuilt). It now sits in the `app_data` volume, which survives rebuilds.

### Step 2 — Automatic 6-hourly backup (already running; this is how it fits recovery)
Seen working on the live server (installed 27 Oct 2026, last run checked 13 Nov 06:00 UTC).

| Piece | Location | Role in recovery |
|---|---|---|
| Schedule | `/var/spool/cron/crontabs/ubuntu` on the server only (edit with `crontab -e`). Not in GitHub, so it must be re-created after a rebuild. | Starts the backup every 6 h (00, 06, 12, 18 UTC = 05:30, 11:30, 17:30, 23:30 Colombo) |
| Script | `scripts/backup.sh` ✅ (in GitHub) | Runs `docker compose exec -T web python manage.py backup_db --dest /srv/app/backups --keep-days 30` |
| Backup code | `core/management/commands/backup_db.py` ✅ (in GitHub) | Makes a safe, compressed copy of the SQLite database |
| Output | `~/inventory-system/backups/db_backup_YYYYMMDD_HHMMSS.sqlite3.gz` (name is Colombo time) | **The file every recovery in Sections 4 and 5 starts from** |
| Log | `~/inventory-system/backups/backup.log` | Proof each run succeeded |
| Restore code | `core/management/commands/restore_db.py` ✅ | Puts a backup file back |

The existing cron line:
```cron
0 */6 * * * /home/ubuntu/inventory-system/scripts/backup.sh >> /home/ubuntu/inventory-system/backups/backup.log 2>&1
```

**Your retention choice:** each run deletes the previous backup, so the server holds **one** backup, at most 6 hours old. The recovery plan therefore depends on the PC/OneDrive copies (Steps 3–4) for anything older. Do not rely on the server alone.

**Keep the repo in step with the server.** The server prints `Deleted old backup: …`, which the repo's `backup_db.py` does not (the repo keeps 30 days). Before any rebuild, save the server's version so the same behaviour comes back:
```bash
cd ~/inventory-system
git diff core/management/commands/backup_db.py scripts/backup.sh
```
Commit those changes to GitHub, or accept the 30-day default after a rebuild.

**Add the logo archive** to the same crontab (only after Step 1), through `crontab -e`:
```cron
5 */6 * * * cd /home/ubuntu/inventory-system && docker compose exec -T web sh -c 'tar -C /srv/app/data -czf /srv/app/backups/media_latest.tar.gz media' >> backups/backup.log 2>&1
```

**Check it any time:**
```bash
crontab -l
ls -lt ~/inventory-system/backups
tail -5 ~/inventory-system/backups/backup.log
```
`./backups` is owned by UID 10001 (the app user) ✅. Do not change its ownership.

### Step 3 — Pull backups to your PC every day (off-server copy #1)
[PC] Save as `C:\MyBackups\pull-backup.ps1` (adjust the key path and IP):

```powershell
$key  = "D:\Office Works\Heritage_Crops\Office_Stock\OCI\ssh-key-2026-10-27.key"
$srv  = "ubuntu@130.210.8.169"
$dest = "C:\MyBackups\pull"
New-Item -ItemType Directory -Force $dest | Out-Null
scp -i $key "${srv}:~/inventory-system/backups/*.gz" $dest\
if ($LASTEXITCODE -ne 0) { Write-Host "BACKUP PULL FAILED"; exit 1 }
# keep 60 days locally
Get-ChildItem $dest -Filter db_backup_*.gz | Where-Object LastWriteTime -lt (Get-Date).AddDays(-60) | Remove-Item
```

Schedule it with Windows **Task Scheduler** → Create Basic Task → Daily → *Start a program* → `powershell.exe -ExecutionPolicy Bypass -File C:\MyBackups\pull-backup.ps1`. Tick *Run task as soon as possible after a scheduled start is missed* (your PC is not always on).

### Step 4 — A second off-server copy that is not in your Oracle account (copy #2)
Pick one, both free:
- Put `C:\MyBackups` inside your **OneDrive** folder so it syncs automatically, or
- copy the folder to a USB drive once a month.

The backups contain real business data and password hashes. Keep them private. Never commit them to GitHub (`.gitignore` already blocks `*.sqlite3.gz`).

### Step 5 — Keep the secrets recoverable
- Once, and after any change: `scp` the server `.env` to `C:\MyBackups\private\env.new`, then store that file only in a password manager or an encrypted/7-Zip-AES archive.
- Keep two copies of the SSH key.
- Keep a note of: OCI login, GitHub login, domain/DNS login, and where the key and `.env` backups are.

### Step 6 (optional) — OCI Object Storage copy #3
Always Free allows 20 GB of Object Storage (Standard + Infrequent + Archive combined) once your account is in the Always Free-only state ([Oracle docs](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm)). The whole backup set is about 6 MB, so space is no issue. It protects against losing the *instance*, but not against losing the *account*, so it does not replace Steps 3–4. Use a Standard-tier bucket and stay well under 20 GB.

---

## 3. Failure scenarios and what to do

| # | What happened | First check | Go to |
|---|---|---|---|
| 1 | Site down, server still reachable | `docker compose ps`, `docker compose logs --tail=60 web` | 4.1 |
| 2 | A bad deploy broke the site | Last `git pull`/build; the logs | 4.2 |
| 3 | Wrong or deleted data, or a corrupt database | When did it start? Which backup predates it? | 4.3 |
| 4 | Instance stopped, reclaimed, terminated, or SSH dead | OCI Console → Instances; Oracle emails | 5 |
| 5 | OCI account or region lost | Cannot log in to OCI | 5 on a **new** account, using the PC copies |
| 6 | Your PC is lost | — | OneDrive/USB copy (Step 4) + password manager (Step 5) |

⚠ Oracle states idle Always Free instances **may be reclaimed**: for 7 days CPU p95 < 20 % and network < 20 % (and memory < 20 % on A1) ([Oracle docs](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm)). A lightly used office app can look idle. Nothing here prevents that reliably, which is why the backups live **off** the instance. Do not rely on a boot-volume backup either: it is limited and reports exist of backups that could not be restored from a disabled instance ([thread](https://community.oracle.com/customerconnect/discussion/968982/cannot-restore-boot-volume-backup-from-disabled-always-free-instance)).

---

## 4. Recovery on the existing server

### 4.1 App is down
```bash
cd ~/inventory-system
docker compose ps
docker compose logs --tail=60 web      # read the FIRST real error
docker compose up -d                   # restart policy is `always`
```

### 4.2 Bad deploy
```bash
git log --oneline -5
git checkout <last-good-commit>        # or: git revert <bad-commit> on the PC and push
docker compose up -d --build
```
Always run `./scripts/backup.sh` **before** every deploy.

### 4.3 Restore the database from a backup
```bash
cd ~/inventory-system
./scripts/backup.sh                    # keep the current state first, even if it is bad
ls -lt backups | head                  # the server keeps only the newest backup; for an older one use your PC copy (Step 3, upload it with scp)
docker compose exec web python manage.py restore_db --file /srv/app/backups/db_backup_YYYYMMDD_HHMMSS.sqlite3.gz
docker compose exec -T web python manage.py shell -c "from catalog.models import Item; print(Item.objects.count())"
```
`restore_db` exists and asks for confirmation (`--yes` skips it) ✅. It overwrites the whole database, so users lose everything entered after that backup. Verify counts and open a few screens afterwards. Logo: `docker compose exec -T web tar -C /srv/app/data -xzf /srv/app/backups/media_latest.tar.gz`.

⚠ **Never** run `docker compose down -v` or `docker volume prune`: they delete the database volume.

---

## 5. Rebuild on a new Always Free instance

Use this for scenarios 4 and 5. Have ready: the latest `.gz` from `C:\MyBackups\pull`, `media_latest.tar.gz`, the saved `.env`, and the SSH key.

1. **[CONSOLE]** Create an instance: Ubuntu 22.04/24.04, **a shape labelled "Always Free-eligible"**, public IPv4, default boot volume (~47–50 GB). Open TCP 80 and 443 in the subnet's Security List.
   - Prefer **AMD Micro (1 GB)** for a simple rebuild; add the 2 GB swap from runbook B5. ⚠ A1 (Arm) capacity is sometimes unavailable ("out of host capacity"). If that happens, retry later or use Micro.
   - If you lost the OCI account, create a new one and rebuild there. Choose Always Free resources only.
2. **[SERVER]** Install Docker/Git and open the Ubuntu firewall ports (runbook **B5**).
3. **[SERVER]** Clone into a folder named exactly `inventory-system` (this fixes the volume name):
   ```bash
   cd ~ && git clone https://github.com/manamendraJN/office-stock-system-host.git inventory-system && cd inventory-system
   ```
4. **[PC → SERVER]** Create `.env`: take the saved copy and change `DJANGO_ALLOWED_HOSTS`/`DJANGO_CSRF_TRUSTED_ORIGINS` for the new IP or domain. A new `DJANGO_SECRET_KEY` is fine; it only logs users out. Keep `MEDIA_ROOT=/srv/app/data/media`.
5. **[SERVER]** Prepare permissions (UID 10001 ✅; volume `inventory-system_app_data` ✅):
   ```bash
   docker volume create inventory-system_app_data
   docker run --rm -v inventory-system_app_data:/data alpine chown -R 10001:10001 /data
   mkdir -p backups && sudo chown -R 10001:10001 backups && chmod +x scripts/backup.sh
   ```
6. **[PC]** Upload the backups: `scp -i KEY db_backup_….sqlite3.gz media_latest.tar.gz ubuntu@NEW_IP:~/inventory-system/backups/`
7. **[SERVER]** `docker compose up -d --build`, wait about 60 s, check `docker compose ps` is `healthy`.
8. **[SERVER]** Restore as in 4.3, and the logo with the `tar -xzf` line there.
9. **[SERVER]** Verify: `curl -s -o /dev/null -w "%{http_code}\n" http://localhost/login/` returns 200; log in with an **old** account; check items, stock and a recent purchase.
10. Point DNS (A record) at the new IP; Caddy will fetch a new certificate itself. Re-create the cron line from Step 2 with `crontab -e`, and update the IP in `pull-backup.ps1`.

---

## 6. Free-tier guardrails

- Stay in the **Always Free-only** account state. Do **not** click "Upgrade". Check Billing → Cost Analysis shows 0.
- Create only resources marked *Always Free* (instance shape, boot volume, 20 GB Object Storage, Always Free IP options). Total block storage across boot+block volumes is 200 GB; volume backups are limited to 5 ([Oracle docs](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm)).
- After terminating an instance, delete its leftover boot volume (unattached volumes still use quota).
- Do not rely on a boot-volume backup as a recovery method; use the SQLite backups.
- ⚠ Check current limits and the ones for your region on Oracle's page before relying on any number above.

## 7. Monthly checklist (10 minutes)

- [ ] `ls -lh ~/inventory-system/backups`: files from the last 6 h exist; `media_latest.tar.gz` is recent.
- [ ] `C:\MyBackups\pull` has yesterday's files; the OneDrive/USB copy is current.
- [ ] Open the newest `.gz`'s database in DB Browser for SQLite, or run `restore_db` on your PC, and confirm the item count.
- [ ] `docker compose ps` healthy; `df -h /` has space; `free -h` OK.
- [ ] `.env` and the SSH key are stored in two places.
- [ ] No Oracle email about idle reclamation or billing.
- [ ] **Every quarter:** do a real drill (Section 5) on a throwaway instance, then terminate it and delete its boot volume.

## 8. Verification notes (what was actually tested)

- `backup_db` → `restore_db` round trip, run locally on a copy of your database: the backup was 46 KB; after deleting every item (44 → 0), the restore returned 44 items and `integrity_check` returned `ok`.
- Confirmed in the code: `restore_db` takes `--file` and `--yes`; `backup_db` takes `--dest` and `--keep-days` (default 30); the app runs as UID 10001; the SQLite database is at `/srv/app/data/db.sqlite3` in volume `app_data`; the company logo is saved to `MEDIA_ROOT` (default `/srv/app/media`, not a volume).
- Seen in your server output: the cron line, a successful run on 13 Nov, and one-backup retention. The repo code and the server differ on retention (Step 2).
- Not tested here: the cron entries, the Task Scheduler job, anything on the live OCI server or Oracle's current free-tier limits.
