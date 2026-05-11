#!/data/data/com.termux/files/usr/bin/bash

BASE="https://bismillah-super-trading-terminal-production.up.railway.app"

echo "START:"
curl -s -X POST "$BASE/api/monitoring/start" \
  -H "Content-Type: application/json" \
  -d '{"ticker":"BBCA","entry_price":9450,"stop_loss":9200,"take_profit":9700,"mode":"daytrading"}'

echo
echo "STATUS:"
curl -s "$BASE/api/monitoring/status/BBCA_daytrading_9450"

echo
