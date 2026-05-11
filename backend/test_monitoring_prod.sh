#!/data/data/com.termux/files/usr/bin/bash

BASE="https://bismillah-super-trading-terminal-production.up.railway.app"

echo "START MONITOR:"
curl -s -X POST "$BASE/api/monitoring/start" \
  -H "Content-Type: application/json" \
  -d '{"ticker":"BBCA","entry_price":9500,"stop_loss":9300,"take_profit":9900,"mode":"swing"}'

echo
echo "STATUS MONITOR:"
curl -s "$BASE/api/monitoring/status/BBCA_swing_9500"

echo
