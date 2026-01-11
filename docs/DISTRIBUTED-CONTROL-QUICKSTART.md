# Distributed Control - Quick Start Guide

Quick reference for controlling multiple pulling agents in a Kubernetes cluster.

## TL;DR

```bash
# Pause all agents in the cluster
curl -X POST "http://agent-service:8000/api/cluster/pause"

# Resume all agents
curl -X POST "http://agent-service:8000/api/cluster/resume"

# Check cluster state
curl http://agent-service:8000/api/cluster/control-state
```

## How It Works

```
┌─────────────────────────┐
│ POST /api/cluster/pause │
└───────────┬─────────────┘
            ↓
    ┌───────────────┐
    │   MongoDB     │ ← Single control document
    │ agent_control │
    └───────┬───────┘
            ↓
    ┌───────┴───────┬───────┬───────┐
    ↓       ↓       ↓       ↓       ↓
 Agent1  Agent2  Agent3  Agent4  AgentN
(All agents watch for changes automatically)
```

## Configuration

Environment variables (already set by default):

```bash
ENABLE_DISTRIBUTED_CONTROL=true    # Enable cluster control
ENABLE_CHANGE_STREAMS=true         # Use real-time mode if available
CONTROL_POLLING_INTERVAL=10        # Fallback polling interval (seconds)
```

## Watch Modes

| Mode | Latency | Requirements | Auto-Selected When |
|------|---------|--------------|-------------------|
| **Change Streams** | < 1 second | MongoDB replica set | Available |
| **Polling** | ~10 seconds | Any MongoDB | Change Streams unavailable |

The system **automatically chooses** the best mode. No manual configuration needed!

## API Endpoints

### Pause All Agents

```bash
curl -X POST "http://agent-service:8000/api/cluster/pause?reason=Maintenance&updated_by=admin"
```

**What happens:**
- All agents complete current batch
- All agents pause
- Readiness probes fail (K8s removes from service)

### Resume All Agents

```bash
curl -X POST "http://agent-service:8000/api/cluster/resume?reason=Maintenance+complete&updated_by=admin"
```

**What happens:**
- All agents resume processing
- Readiness probes pass (K8s adds to service)

### Shutdown All Agents ⚠️

```bash
curl -X POST "http://agent-service:8000/api/cluster/shutdown?reason=Emergency&updated_by=admin"
```

**Warning:** Shuts down ALL agents. Use with caution!

### Check Cluster State

```bash
curl http://agent-service:8000/api/cluster/control-state
```

**Response:**
```json
{
  "command": "pause",
  "version": 42,
  "watch_mode": "change_streams",
  "timestamp": "2026-01-11T10:30:00Z",
  "reason": "Maintenance",
  "updated_by": "admin"
}
```

## Common Use Cases

### 1. Deploy New Version

```bash
# Pause all agents
curl -X POST "http://agent-service:8000/api/cluster/pause?reason=Deploying+v2.0&updated_by=deploy_script"

# Deploy
kubectl rollout restart deployment/pulling-agent
kubectl rollout status deployment/pulling-agent

# Resume
curl -X POST "http://agent-service:8000/api/cluster/resume?reason=Deploy+complete&updated_by=deploy_script"
```

### 2. Emergency Stop

```bash
# Immediately pause all agents
curl -X POST "http://agent-service:8000/api/cluster/pause?reason=Data+issue+detected&updated_by=monitoring"

# Check state
curl http://agent-service:8000/api/cluster/control-state

# Resume when ready
curl -X POST "http://agent-service:8000/api/cluster/resume?reason=Issue+fixed&updated_by=admin"
```

### 3. Scheduled Maintenance (CronJob)

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: nightly-pause
spec:
  schedule: "0 2 * * *"  # 2 AM daily
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: pause
            image: curlimages/curl
            command:
            - curl
            - -X
            - POST
            - http://pulling-agent-service:8000/api/cluster/pause?reason=Nightly+maintenance&updated_by=cronjob
          restartPolicy: OnFailure
```

## Verification

### Check Which Mode is Active

```bash
curl http://agent-service:8000/api/cluster/stats | jq '.watch_mode'
```

Output:
- `"change_streams"` = Real-time mode ✓ (best)
- `"polling"` = Fallback mode (acceptable)

### Check Logs

```bash
kubectl logs -l app=pulling-agent | grep "Distributed Control"
```

Expected:
```
[INFO] [Distributed Control] Initializing cluster coordination
[INFO] Using MongoDB Change Streams (event-driven, real-time)
```

Or:
```
[INFO] Using polling fallback (interval: 10s)
```

### Verify All Agents Paused

```bash
# Check each agent's state
for pod in $(kubectl get pods -l app=pulling-agent -o name); do
  kubectl exec $pod -- curl -s localhost:8000/api/agent/state | jq .state
done
```

Expected output (all should show "paused"):
```
"paused"
"paused"
"paused"
```

## Troubleshooting

### Agents Not Responding

**1. Check MongoDB connection:**
```bash
curl http://agent-service:8000/api/mongo/status
```

**2. Check distributed control is enabled:**
```bash
kubectl exec -it agent-pod -- env | grep ENABLE_DISTRIBUTED_CONTROL
```

**3. Manually trigger update:**
```bash
# Force version increment to wake up agents
kubectl exec -it mongo-pod -- mongosh your_database --eval \
  'db.agent_control.updateOne({_id:"global_control"}, {$inc:{version:1}})'
```

### Change Streams Not Available

If using single-node MongoDB, you'll see:
```
[WARNING] MongoDB Change Streams not available: Replica set required. Using polling fallback.
```

**This is fine!** Polling mode works perfectly, just with 5-10 second delay instead of sub-second.

**To enable Change Streams:** Use MongoDB Atlas or deploy as replica set.

## Performance

### Change Streams Mode

- **Latency:** < 1 second
- **Database load:** 1 connection per agent, 0 queries
- **Best for:** Production, 2+ agents

### Polling Mode

- **Latency:** ~10 seconds (configurable)
- **Database load:** 1 query per agent per interval
- **Best for:** Development, single-node MongoDB

## Comparison with Other Methods

| Method | Controls | Latency | Survives Restart |
|--------|----------|---------|------------------|
| **`/api/cluster/*`** | **All agents** | **< 1s** | **✓** |
| `/api/agent/*` | Single agent | Immediate | ✗ |
| ConfigMap | All agents | 2s | ✓ |
| Unix signals | Single agent | < 1s | ✗ |

Use `/api/cluster/*` for production cluster control.

## Security

Every command includes audit trail:
- **Who:** `updated_by` parameter
- **What:** `command` (pause/resume/shutdown)
- **When:** `timestamp` (automatic)
- **Why:** `reason` parameter

View history:
```bash
kubectl exec -it mongo-pod -- mongosh your_database --eval \
  'db.agent_control.find().sort({version:-1}).limit(10).pretty()'
```

## Next Steps

- [Full Documentation](DISTRIBUTED-CONTROL.md) - Complete guide
- [API Reference](API-REFERENCE.md) - All endpoints
- [Examples](../examples/) - More use cases

## Summary

**Key Points:**
1. ✅ **Zero configuration** - Works out of the box
2. ✅ **Automatic mode selection** - Uses best available method
3. ✅ **One command controls all** - Single API call affects all agents
4. ✅ **Survives restarts** - State persists in MongoDB
5. ✅ **Audit trail** - Track all changes
6. ✅ **Backward compatible** - Old control methods still work

**Most Common Commands:**
```bash
# Pause cluster
curl -X POST "http://agent-service:8000/api/cluster/pause"

# Resume cluster
curl -X POST "http://agent-service:8000/api/cluster/resume"

# Check status
curl http://agent-service:8000/api/cluster/control-state
```

That's it! 🎉
