# Deployment & Maintenance Commands

**PS** = Windows PowerShell on your PC. **SRV** = Ubuntu on OCI (after SSH).
Placeholders: `YOUR_DOMAIN`, `BACKUP_FILE`, `COMMIT_ID`.
Never run `docker compose down -v` or `docker volume prune`.

---

## 1. Connect to OCI via SSH (PS)
```powershell
cd "D:\Office Works\Heritage_Crops\Office_Stock\OCI"
ssh -i .\ssh-key-2026-10-27.key ubuntu@130.210.8.169
```

## 2. Check current directory and go to the project (SRV)
```bash
pwd
cd ~/inventory-system
pwd
ls
```

## 3. Check Git status before updating (SRV)
```bash
git status
git log --oneline -3
git rev-parse --short HEAD
```
Write down the commit id from the last line. It is your rollback point.

## 4. Check disk space and memory (SRV)
```bash
df -h /
free -h
docker system df
```

## 5. Verify environment configuration (SRV)
```bash
grep -E '^(DOMAIN_NAME|DJANGO_ALLOWED_HOSTS|DJANGO_CSRF_TRUSTED_ORIGINS|DJANGO_DEBUG|DB_ENGINE|DB_PATH|MEDIA_ROOT)=' .env
awk -F= '/^DJANGO_SECRET_KEY=/{print "secret key length:", length($2)}' .env
```

## 6. Create a database backup on OCI (SRV)
```bash
./scripts/backup.sh
ls -lt backups | head -5
```
Logo/media archive:
```bash
docker compose exec -T web sh -c 'tar -C /srv/app/data -czf /srv/app/backups/media_latest.tar.gz media'
```

## 7. Download the backup to your Windows PC (PS)
Find the newest backup name:
```powershell
ssh -i "D:\Office Works\Heritage_Crops\Office_Stock\OCI\ssh-key-2026-10-27.key" ubuntu@130.210.8.169 "ls -t ~/inventory-system/backups/db_backup_*.gz | head -1"
```
Download it:
```powershell
mkdir C:\MyBackups\migrate -Force
scp -i "D:\Office Works\Heritage_Crops\Office_Stock\OCI\ssh-key-2026-10-27.key" ubuntu@130.210.8.169:~/inventory-system/backups/BACKUP_FILE C:\MyBackups\migrate\
```
Download every backup and the logo archive:
```powershell
scp -i "D:\Office Works\Heritage_Crops\Office_Stock\OCI\ssh-key-2026-10-27.key" "ubuntu@130.210.8.169:~/inventory-system/backups/*.gz" C:\MyBackups\migrate\
```

## 8. Verify the local backup (PS)
```powershell
dir C:\MyBackups\migrate
python -c "import gzip,shutil,sqlite3,os; src=r'C:\MyBackups\migrate\BACKUP_FILE'; tmp=os.path.join(os.environ['TEMP'],'verify.sqlite3'); shutil.copyfileobj(gzip.open(src,'rb'),open(tmp,'wb')); c=sqlite3.connect(tmp); print(c.execute('pragma integrity_check').fetchone(), c.execute('select count(*) from catalog_item').fetchone()); c.close(); os.remove(tmp)"
```
Expected output starts with `('ok',)`.

## 9. Pull the latest changes from GitHub (SRV)
```bash
cd ~/inventory-system
git pull
git log --oneline -3
```

## 10. Dependencies, migrations and static files (SRV)
These run automatically in the build and start-up: `pip install` and `collectstatic` in the Dockerfile, `migrate` in `docker/entrypoint.sh`. One command covers all three:
```bash
docker compose up -d --build
```

## 11. Restart services (SRV)
Apply `.env` changes:
```bash
docker compose up -d
```
Restart the web app only:
```bash
docker compose restart web
```
Restart Caddy only:
```bash
docker compose restart caddy
```

## 12. Verify service status (SRV)
```bash
docker compose ps
docker inspect -f '{{.Name}} restarts={{.RestartCount}} health={{if .State.Health}}{{.State.Health.Status}}{{end}}' $(docker compose ps -q)
```

## 13. Check logs (SRV)
```bash
docker compose logs --tail=60 web
docker compose logs --tail=40 caddy
docker compose logs --since 1h web | grep -i -E "error|traceback" | tail
sudo journalctl -u docker --since "1 hour ago" --no-pager | tail -30
```

## 14. Check database connectivity and migrations (SRV)
```bash
docker compose exec -T web python manage.py check --database default
docker compose exec -T web python manage.py showmigrations --plan | tail -5
docker compose exec -T web python -c "import sqlite3; print(sqlite3.connect('/srv/app/data/db.sqlite3').execute('pragma integrity_check').fetchone())"
```

## 15. Verify the website is accessible
From the server (SRV):
```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost/login/
curl -s -o /dev/null -w "%{http_code}\n" https://YOUR_DOMAIN/login/
```
From your PC (PS):
```powershell
curl.exe -s -o NUL -w "%{http_code}\n" http://130.210.8.169/login/
curl.exe -s -o NUL -w "%{http_code}\n" https://YOUR_DOMAIN/login/
```
`200` is healthy. `301`/`308` is the HTTP-to-HTTPS redirect.

## 16. Roll back to the previous working version if deployment fails (SRV)
```bash
cd ~/inventory-system
git log --oneline -10
git checkout COMMIT_ID
docker compose up -d --build
docker compose ps
docker compose logs --tail=60 web
```
Return to the latest code later:
```bash
git checkout main
git pull
```
If the failed deploy also changed the database, restore the pre-deploy backup (section 17).

## 17. Restore the database from a backup (SRV)
Back up the current state first:
```bash
cd ~/inventory-system
./scripts/backup.sh
ls -lt backups | head
```
Restore (asks for confirmation):
```bash
docker compose exec web python manage.py restore_db --file /srv/app/backups/BACKUP_FILE
```
Verify:
```bash
docker compose exec -T web python -c "import sqlite3; print(sqlite3.connect('/srv/app/data/db.sqlite3').execute('pragma integrity_check').fetchone())"
docker compose restart web
```
Restore the logo, if needed:
```bash
docker compose exec -T web tar -C /srv/app/data -xzf /srv/app/backups/media_latest.tar.gz
```

### 17a. Upload a backup from your PC to the server first (PS)
```powershell
scp -i "D:\Office Works\Heritage_Crops\Office_Stock\OCI\ssh-key-2026-10-27.key" C:\MyBackups\migrate\BACKUP_FILE ubuntu@130.210.8.169:~/inventory-system/backups/
```

## 18. Clean up old backups safely
Backup files belong to the app user (UID 10001), so delete them through the container, not with plain `rm` as `ubuntu`.

List what would be deleted (everything except the newest 20), without deleting (SRV):
```bash
cd ~/inventory-system
docker compose exec -T web sh -c 'ls -1t /srv/app/backups/db_backup_*.gz | tail -n +21'
```
Delete everything except the newest 20 (SRV):
```bash
docker compose exec -T web sh -c 'ls -1t /srv/app/backups/db_backup_*.gz | tail -n +21 | xargs -r rm --'
ls -lt backups | head -25
```
The built-in 30-day rotation:
```bash
docker compose exec -T web python manage.py backup_db --dest /srv/app/backups --keep-days 30
```
Keep only the newest 60 on your PC (PS):
```powershell
Get-ChildItem C:\MyBackups\migrate -Filter db_backup_*.gz | Sort-Object LastWriteTime -Descending | Select-Object -Skip 60 | Remove-Item -WhatIf
```
Remove `-WhatIf` to delete for real.

---

## Extra: schedule and check automatic backups (SRV)
```bash
crontab -e
```
Add:
```cron
0 */6 * * * cd /home/ubuntu/inventory-system && ./scripts/backup.sh >> backups/backup.log 2>&1
```
Check:
```bash
crontab -l
tail -20 ~/inventory-system/backups/backup.log
```

## Extra: standard deploy sequence (PC, then SRV)
Commit and push from the PC (PS):
```powershell
cd D:\Github-Projects\office-stock-system-host
git status
git add .
git commit -m "Describe the update"
git push
```
Then on the server (SRV):
```bash
cd ~/inventory-system
git rev-parse --short HEAD
./scripts/backup.sh
git pull
docker compose up -d --build
sleep 60
docker compose ps
docker compose logs --tail=60 web
curl -s -o /dev/null -w "%{http_code}\n" http://localhost/login/
```

## Extra: stop and start without deleting data (SRV)
```bash
docker compose stop
docker compose start
```

## Extra: update Ubuntu packages (SRV)
```bash
sudo apt update && sudo apt upgrade -y
```
Reboot if required, then check again:
```bash
sudo reboot
```
```bash
cd ~/inventory-system && docker compose ps
```
