@echo off
REM Project Shimmer -- operator setup launcher.
REM
REM This file is intentionally TRIVIAL: it only launches the Python bootstrap and
REM pauses so the operator can read the readiness report. ALL real logic lives in
REM scripts\preflight.py. No secrets and no machine-specific paths belong here.
REM (A future setup.sh / setup.command should be just as thin: launch preflight,
REM then wait for a keypress.)

cd /d "%~dp0"

py -3.9 -X utf8 scripts\preflight.py

echo.
echo ----------------------------------------------------------------------
echo Preflight finished. Review the bill of health above.
pause
