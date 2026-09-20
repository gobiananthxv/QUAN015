#!/usr/bin/env bash
# Run every phase gate. Exits non-zero if anything fails.
set -uo pipefail
cd "$(dirname "$0")/backend"

# bin/ on Unix, Scripts/ on Windows.
if   [ -x .venv/bin/python ];         then PY=.venv/bin/python
elif [ -x .venv/Scripts/python.exe ]; then PY=.venv/Scripts/python.exe
else
  echo "error: no virtualenv found. Run ./run.sh once to create it." >&2
  exit 1
fi

fail=0
echo "── test suite ─────────────────────────────────────────"
"$PY" -m pytest tests/ -q || fail=1
echo
for s in bootstrap_data analytics_report backtest_report strategy_report robustness_report security_report; do
  printf '── %-20s ' "$s"
  if "$PY" "scripts/$s.py" > /dev/null 2>&1; then echo "PASS"; else echo "FAIL"; fail=1; fi
done
echo
[ $fail -eq 0 ] && echo "ALL GATES PASSED" || echo "SOME GATES FAILED"
exit $fail
