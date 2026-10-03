#!/bin/sh
cd /opt/chiller-monitor
export CHILLER_INSTALLED=1
export CHILLER_WINDOW=1
export PYTHONUTF8=1
export PYTHONPATH="/opt/chiller-monitor/lib${PYTHONPATH:+:$PYTHONPATH}"
exec /usr/bin/python3 -m app
