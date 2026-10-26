# Loads 5 sample records of every kind (branches, users, items, purchases, requests, dispatches, issues, petty cash).
# Run from the project folder in PowerShell:   .\scripts\load_sample_data.ps1
# Needs DJANGO_DEBUG=true in .env and a Super Admin (python manage.py seed).
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
$python = if (Test-Path '.\.venv\Scripts\python.exe') { '.\.venv\Scripts\python.exe' } else { 'python' }
& $python manage.py migrate
& $python manage.py seed_sample_data
