#!/bin/bash
cd "$(dirname "$0")"
while true; do
  ./start_worker.sh
  echo "[$(date)] worker stopped; restarting in 10s (close this window to quit)"
  sleep 10
done
