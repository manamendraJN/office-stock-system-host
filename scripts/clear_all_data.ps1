# Deletes ALL data except the Super Admin account(s), the main office, roles and settings.
# Run from the project folder in PowerShell:   .\scripts\clear_all_data.ps1
# It asks you to type the database file name before anything is deleted. Needs DJANGO_DEBUG=true in .env.
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
$python = if (Test-Path '.\.venv\Scripts\python.exe') { '.\.venv\Scripts\python.exe' } else { 'python' }
& $python manage.py clear_all_data
