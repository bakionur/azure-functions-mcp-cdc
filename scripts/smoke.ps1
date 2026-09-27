# Smoke test (logic lives in smoke.py so the laptop and CI run the same thing)
python "$PSScriptRoot/smoke.py"
exit $LASTEXITCODE
