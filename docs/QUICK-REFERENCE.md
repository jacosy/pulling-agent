# Quick Reference Card

## Common Commands

### Deployment
```bash
# Deploy everything
kubectl apply -f k8s/

# Check status
kubectl get pods -l app=pulling-agent

# View logs
kubectl logs -f deployment/pulling-agent
```

### Control
```bash
# Using control script (recommended)
./scripts/control-agent.sh pause
./scripts/control-agent.sh resume
./scripts/control-agent.sh status
./scripts/control-agent.sh restart

# Using ConfigMap
kubectl create configmap agent-control --from-literal=state=pause -o yaml --dry-run=client | kubectl apply -f -
kubectl create configmap agent-control --from-literal=state=resume -o yaml --dry-run=client | kubectl apply -f -

# Using Makefile
make k8s-pause
make k8s-resume
make k8s-control-status

# Using signals (immediate)
POD=$(kubectl get pod -l app=pulling-agent -o jsonpath='{.items[0].metadata.name}')
kubectl exec $POD -- kill -USR1 1  # Pause
kubectl exec $POD -- kill -USR2 1  # Resume

# Regular restart
kubectl rollout restart deployment/pulling-agent
```

### Health Checks
```bash
# Pod name
POD=$(kubectl get pod -l app=pulling-agent -o jsonpath='{.items[0].metadata.name}')

# Liveness
kubectl exec $POD -- cat /tmp/health/liveness

# Readiness
kubectl exec $POD -- test -f /tmp/health/readiness && echo "Ready" || echo "Not ready"

# Resources
kubectl top pod -l app=pulling-agent
```

### Troubleshooting
```bash
# Recent errors
kubectl logs --tail=50 deployment/pulling-agent | grep ERROR

# Pod events
kubectl describe pod -l app=pulling-agent

# Test MongoDB connection
kubectl exec $POD -- python3 -c "from motor.motor_asyncio import AsyncIOMotorClient; import asyncio; asyncio.run(AsyncIOMotorClient('$MONGODB_URI').admin.command('ping'))"
```

## File Locations

| File | Purpose |
|------|---------|
| `/tmp/health/liveness` | Heartbeat file (updated every 5s) |
| `/tmp/health/readiness` | Exists when ready to process |
| `/tmp/control/state` | Control file (pause/resume/shutdown) |

## Agent States

| State | Description | Readiness File |
|-------|-------------|----------------|
| RUNNING | Processing batches | Exists |
| PAUSED | Waiting, not processing | Absent |
| STOPPING | Shutting down | Absent |
| STOPPED | Terminated | Absent |

## Signals

| Signal | Action | Command |
|--------|--------|---------|
| SIGTERM | Graceful shutdown | `kubectl delete pod $POD` |
| SIGINT | Graceful shutdown | (Not applicable in K8s) |
| SIGUSR1 | Pause | `kubectl exec $POD -- kill -USR1 1` |
| SIGUSR2 | Resume | `kubectl exec $POD -- kill -USR2 1` |

## Configuration

### Environment Variables
- `MONGODB_URI` - Connection string (from secret)
- `MONGODB_DATABASE` - Database name
- `MONGODB_COLLECTION` - Collection name
- `POLL_INTERVAL` - Seconds between polls (default: 5)
- `BATCH_SIZE` - Documents per batch (default: 100)
- `LOG_LEVEL` - Logging level (default: INFO)

### Resource Defaults
- Memory request: 256Mi
- Memory limit: 512Mi
- CPU request: 100m
- CPU limit: 500m

## Useful One-Liners

```bash
# Watch pod status
watch kubectl get pods -l app=pulling-agent

# Follow logs with timestamp
kubectl logs -f deployment/pulling-agent --timestamps

# Get processing stats
kubectl exec $POD -- cat /tmp/health/liveness | grep -E "batches|documents|errors"

# Check if processing
kubectl logs --tail=10 deployment/pulling-agent | grep "Processing batch"

# Force pod recreation
kubectl delete pod -l app=pulling-agent

# Edit live config
kubectl edit configmap agent-config

# View all agent resources
kubectl get all,cm,secret -l app=pulling-agent
```
