@echo off
cd /d "%~dp0"
python sync_nf_status.py >> sync_nf_status.log 2>&1
