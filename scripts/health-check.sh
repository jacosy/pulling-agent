#!/bin/sh
# Health check script for liveness probe
# Can be used as an alternative to inline shell commands in K8s probes

LIVENESS_FILE=/tmp/health/liveness
MAX_AGE=30

if [ ! -f "$LIVENESS_FILE" ]; then
    echo "ERROR: Liveness file not found"
    exit 1
fi

# Get file age in seconds
FILE_TIMESTAMP=$(stat -c %Y "$LIVENESS_FILE" 2>/dev/null)
CURRENT_TIMESTAMP=$(date +%s)
AGE=$((CURRENT_TIMESTAMP - FILE_TIMESTAMP))

if [ $AGE -gt $MAX_AGE ]; then
    echo "ERROR: Liveness file too old (${AGE}s > ${MAX_AGE}s)"
    exit 1
fi

echo "OK: Healthy (heartbeat age: ${AGE}s)"
exit 0
