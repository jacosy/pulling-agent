# Distributed Control for Multi-Agent Clusters

This document describes the distributed control system for coordinating multiple pulling agent instances running in a Kubernetes cluster.

## Overview

When multiple pulling agents run simultaneously in a K8s cluster, you need a way to control all of them at once. The distributed control system provides:

- **Cluster-wide pause/resume/shutdown** - Control all agents with a single command
- **Two watch modes** - MongoDB Change Streams (real-time) or polling (fallback)
- **Automatic mode detection** - System chooses the best available method
- **Audit trail** - Track who changed what and when
- **Persistent state** - Commands survive pod restarts

## Architecture

```
┌─────────────────────────────────────────────────────┐
│           Kubernetes Cluster                         │
│                                                      │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐          │
│  │ Agent 1  │  │ Agent 2  │  │ Agent N  │          │
│  │  Pod     │  │  Pod     │  │  Pod     │          │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘          │
│       │             │             │                  │
│       └─────────────┴─────────────┘                  │
│                     │                                │
│          Watch for control changes                   │
│          (Change Streams OR Polling)                │
└─────────────────────┼────────────────────────────────┘
                      ↓
            ┌─────────────────────┐
            │   MongoDB Database  │
            ├─────────────────────┤
            │ agent_control       │
            │ {                   │
            │   _id: "global",    │
            │   command: "pause", │
            │   version: 42,      │
            │   timestamp: ...,   │
            │   reason: "...",    │
            │   updated_by: "..." │
            │ }                   │
            └─────────────────────┘
                      ↑
            POST /api/cluster/pause
         (Control command from any pod)
```

## Configuration

Distributed control is **enabled by default**. Configure via environment variables:

```bash
# Enable/disable distributed control
ENABLE_DISTRIBUTED_CONTROL=true  # Default: true

# Enable Change Streams (requires MongoDB replica set)
ENABLE_CHANGE_STREAMS=true       # Default: true

# Polling interval (used if Change Streams unavailable)
CONTROL_POLLING_INTERVAL=10      # Default: 10 seconds
```

## Watch Modes

### Mode 1: MongoDB Change Streams (Recommended)

**How it works:**
- Agents open a persistent connection to MongoDB
- MongoDB **pushes** events when control document changes
- Sub-second latency for command propagation
- **Zero polling overhead**

**Requirements:**
- MongoDB 3.6+
- **Replica Set deployment** (NOT single-node)

**When to use:**
- Production deployments (Atlas, managed MongoDB)
- When you need real-time control (< 1 second)
- When minimizing database load is important

### Mode 2: Polling (Fallback)

**How it works:**
- Agents periodically query MongoDB for version changes
- Default interval: 10 seconds (configurable)
- Only queries when document version changes

**Requirements:**
- Any MongoDB deployment (even single-node)
- No special MongoDB features needed

**When to use:**
- Development with single-node MongoDB
- When Change Streams aren't available
- When 5-10 second latency is acceptable

### Automatic Detection

The system automatically detects which mode to use:

1. If `ENABLE_CHANGE_STREAMS=true`:
   - Try to create a Change Stream
   - If successful → use Change Streams mode ✓
   - If fails (e.g., single-node) → fallback to polling
2. If `ENABLE_CHANGE_STREAMS=false`:
   - Use polling mode directly

You'll see log messages indicating which mode was selected:

```
[INFO] Using MongoDB Change Streams (event-driven, real-time)
# OR
[INFO] Using polling fallback (interval: 10s)
```

## API Endpoints

All cluster control endpoints are available at `/api/cluster/*`:

### Pause All Agents

```bash
curl -X POST "http://any-agent:8000/api/cluster/pause?reason=Maintenance+window&updated_by=ops_team"
```

**Response:**
```json
{
  "status": "success",
  "message": "Pause command issued to all agents in the cluster",
  "command": "pause",
  "version": 42,
  "timestamp": "2026-01-11T10:30:00.123456",
  "reason": "Maintenance window",
  "propagation": "Agents will pause within seconds (event-driven via Change Streams)"
}
```

**What happens:**
1. Command written to MongoDB `agent_control` collection
2. All agents receive notification (via Change Streams or polling)
3. Each agent completes current batch, then pauses
4. Readiness probes fail (K8s removes pods from service)

### Resume All Agents

```bash
curl -X POST "http://any-agent:8000/api/cluster/resume?reason=Maintenance+complete&updated_by=ops_team"
```

**Response:**
```json
{
  "status": "success",
  "message": "Resume command issued to all agents in the cluster",
  "command": "running",
  "version": 43,
  "timestamp": "2026-01-11T12:00:00.123456",
  "reason": "Maintenance complete",
  "propagation": "Agents will resume within seconds (event-driven via Change Streams)"
}
```

**What happens:**
1. Command written to MongoDB
2. All agents receive notification
3. Each agent immediately resumes processing
4. Readiness probes succeed (K8s adds pods to service)

### Shutdown All Agents

```bash
curl -X POST "http://any-agent:8000/api/cluster/shutdown?reason=Emergency+stop&updated_by=admin"
```

**Response:**
```json
{
  "status": "success",
  "message": "Shutdown command issued to all agents in the cluster",
  "command": "shutdown",
  "version": 44,
  "timestamp": "2026-01-11T15:00:00.123456",
  "reason": "Emergency stop",
  "propagation": "Agents will shutdown gracefully within seconds (event-driven via Change Streams)"
}
```

**Warning:** This shuts down **ALL** agents in the cluster. Use with caution!

### Check Cluster State

```bash
curl http://any-agent:8000/api/cluster/control-state
```

**Response:**
```json
{
  "command": "pause",
  "version": 42,
  "timestamp": "2026-01-11T10:30:00.123456",
  "reason": "Maintenance window",
  "updated_by": "ops_team",
  "watch_mode": "change_streams",
  "note": "All agents in the cluster are subscribed to this state"
}
```

### Get Cluster Statistics

```bash
curl http://any-agent:8000/api/cluster/stats
```

**Response:**
```json
{
  "watch_mode": "change_streams",
  "polling_interval": null,
  "current_command": "pause",
  "current_version": 42,
  "last_updated": "2026-01-11T10:30:00.123456",
  "updated_by": "ops_team",
  "reason": "Maintenance window"
}
```

## Usage Examples

### Example 1: Scheduled Maintenance

```bash
#!/bin/bash
# maintenance.sh - Pause agents before deployment

# Pause all agents
echo "Pausing all agents for maintenance..."
curl -X POST "http://agent-service:8000/api/cluster/pause?reason=Deploying+new+version&updated_by=deploy_script"

# Wait for all pods to pause
sleep 15

# Deploy new version
kubectl rollout restart deployment/pulling-agent

# Wait for rollout
kubectl rollout status deployment/pulling-agent

# Resume all agents
echo "Resuming all agents..."
curl -X POST "http://agent-service:8000/api/cluster/resume?reason=Deployment+complete&updated_by=deploy_script"

echo "Maintenance complete!"
```

### Example 2: Emergency Pause

```bash
# Immediately pause all agents (e.g., detected data issue)
curl -X POST "http://agent-service:8000/api/cluster/pause?reason=Data+integrity+issue+detected&updated_by=monitoring_system"

# Check current state
curl http://agent-service:8000/api/cluster/control-state

# Resume after issue resolved
curl -X POST "http://agent-service:8000/api/cluster/resume?reason=Issue+resolved&updated_by=admin"
```

### Example 3: Kubernetes CronJob Control

```yaml
# k8s/cronjobs/scheduled-pause.yaml
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
          - name: pause-agents
            image: curlimages/curl:latest
            command:
            - sh
            - -c
            - |
              curl -X POST "http://pulling-agent-service:8000/api/cluster/pause?reason=Nightly+maintenance+window&updated_by=cronjob"
          restartPolicy: OnFailure
---
apiVersion: batch/v1
kind: CronJob
metadata:
  name: nightly-resume
spec:
  schedule: "0 4 * * *"  # 4 AM daily
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: resume-agents
            image: curlimages/curl:latest
            command:
            - sh
            - -c
            - |
              curl -X POST "http://pulling-agent-service:8000/api/cluster/resume?reason=Maintenance+window+complete&updated_by=cronjob"
          restartPolicy: OnFailure
```

### Example 4: Monitoring with Prometheus

```python
# monitoring/cluster_status_exporter.py
import time
import requests
from prometheus_client import start_http_server, Gauge

# Metrics
cluster_state = Gauge('agent_cluster_state', 'Current cluster control state', ['command'])
cluster_version = Gauge('agent_cluster_version', 'Current cluster control version')

def collect_metrics():
    """Collect cluster state metrics"""
    try:
        response = requests.get('http://agent-service:8000/api/cluster/control-state')
        data = response.json()

        # Update metrics
        command = data['command']
        cluster_state.labels(command=command).set(1)
        cluster_version.set(data['version'])

    except Exception as e:
        print(f"Error collecting metrics: {e}")

if __name__ == '__main__':
    start_http_server(9090)
    while True:
        collect_metrics()
        time.sleep(30)
```

## State Synchronization

### New Agents Join the Cluster

When a new agent pod starts:

1. Agent connects to MongoDB
2. Reads current global control state
3. **Syncs to that state immediately**
4. Starts watching for future changes

Example:
- Cluster is in "pause" state (version 42)
- New pod starts
- Pod reads state, sees "pause"
- Pod immediately pauses itself
- Pod waits for resume command

### Agents Restart

When an agent restarts:

1. On startup, agent queries current state
2. Applies that state before starting main loop
3. Example: If cluster is paused, restarted agent stays paused

### Network Partitions

**Change Streams mode:**
- Connection loss triggers exponential backoff retry
- Reconnects automatically when network restored
- Catches up on missed events

**Polling mode:**
- Continues polling with retry logic
- Exponential backoff on errors
- Eventually consistent when network restored

## Comparison with Other Control Methods

| Method | Scope | Latency | Persistence | Audit Trail |
|--------|-------|---------|-------------|-------------|
| **Distributed Control** | **All agents** | **< 1s** | **✓ Survives restarts** | **✓ Full audit** |
| HTTP API (`/api/agent/*`) | Single pod | Immediate | ✗ Lost on restart | ✗ Logs only |
| ConfigMap | All agents | 2s poll | ✓ Survives restarts | ✗ Limited |
| Unix Signals | Single pod | < 1s | ✗ Lost on restart | ✗ Logs only |
| Kubernetes Jobs | All agents | Variable | ✗ One-time | ✓ Job logs |

**When to use distributed control:**
- ✅ Need to control **multiple agents** at once
- ✅ Need **persistent state** (survives restarts)
- ✅ Need **audit trail** (who/what/when/why)
- ✅ Want **automatic propagation** to all pods
- ✅ Operating in production with multiple replicas

**When to use single-agent API:**
- ✅ Testing/debugging a specific pod
- ✅ Need to pause just **one** agent
- ✅ Troubleshooting individual pod issues

## Troubleshooting

### Check Which Mode is Active

```bash
curl http://any-agent:8000/api/cluster/stats
```

Look for `watch_mode`:
- `"change_streams"` = Real-time mode
- `"polling"` = Fallback mode
- `null` = Watch not started yet

### Check Logs for Mode Selection

```bash
kubectl logs -l app=pulling-agent | grep "Distributed Control"
```

Expected output:
```
[INFO] [Distributed Control] Initializing cluster coordination
[INFO] ✓ MongoDB Change Streams are supported
[INFO] Using MongoDB Change Streams (event-driven, real-time)
```

Or for polling mode:
```
[INFO] [Distributed Control] Initializing cluster coordination
[WARNING] MongoDB Change Streams not available: Replica set required. Using polling fallback.
[INFO] Using polling fallback (interval: 10s)
```

### Verify Control Document Exists

```bash
# Connect to MongoDB
kubectl exec -it mongo-pod -- mongosh

# Check control document
use your_database
db.agent_control.findOne({_id: "global_control"})
```

Expected output:
```javascript
{
  _id: 'global_control',
  command: 'running',
  version: 42,
  timestamp: ISODate("2026-01-11T10:30:00.123Z"),
  reason: 'Normal operation',
  updated_by: 'system'
}
```

### Agents Not Responding to Commands

**Check 1:** Verify distributed control is enabled
```bash
kubectl exec -it agent-pod -- env | grep ENABLE_DISTRIBUTED_CONTROL
# Should output: ENABLE_DISTRIBUTED_CONTROL=true
```

**Check 2:** Check agent logs for errors
```bash
kubectl logs -l app=pulling-agent --tail=100 | grep -i error
```

**Check 3:** Verify MongoDB connectivity
```bash
curl http://agent-pod:8000/api/mongo/status
```

**Check 4:** Manually increment version to trigger update
```javascript
// In MongoDB shell
db.agent_control.updateOne(
  {_id: "global_control"},
  {$inc: {version: 1}, $set: {timestamp: new Date()}}
)
```

### Change Streams Not Available

If you see:
```
[WARNING] MongoDB Change Streams not available: Replica set required. Using polling fallback.
```

**Solution:** Deploy MongoDB as a replica set. For development:

```bash
# Docker Compose with replica set
docker-compose -f docker-compose-replicaset.yml up -d
```

Or use MongoDB Atlas (already configured as replica set).

## Performance Considerations

### Change Streams Mode

**Pros:**
- Minimal database load (persistent connection)
- No polling overhead
- Sub-second latency

**Cons:**
- Requires replica set (more resources)
- One connection per agent pod

**Recommendation:** Use for production with 2+ agents.

### Polling Mode

**Pros:**
- Works with any MongoDB deployment
- Simple and predictable
- Low resource usage

**Cons:**
- Polling overhead (1 query every 10s per agent)
- Higher latency (up to poll interval)

**Recommendation:** Use for development or when Change Streams unavailable.

### Database Load Estimation

**Change Streams:**
- Initial connection: 1 per agent
- Ongoing: 0 queries (push-based)
- Example: 10 agents = 10 connections, 0 QPS

**Polling (10s interval):**
- Queries per second: `agents / interval`
- Example: 10 agents = 1 QPS
- Example: 100 agents = 10 QPS

## Security Considerations

### Audit Trail

Every command change includes:
- **who**: `updated_by` field (user/system)
- **what**: `command` field (pause/resume/shutdown)
- **when**: `timestamp` field (ISO 8601)
- **why**: `reason` field (human-readable)

Query audit history:
```javascript
// MongoDB shell
db.agent_control.find().sort({version: -1}).limit(10)
```

### Access Control

Distributed control respects MongoDB authentication:
- Agents need read/write access to `agent_control` collection
- Recommend: Separate MongoDB role for agent control

```javascript
// Create dedicated role
db.createRole({
  role: "agentControl",
  privileges: [{
    resource: { db: "your_db", collection: "agent_control" },
    actions: ["find", "insert", "update"]
  }],
  roles: []
})
```

### Network Security

API endpoints should be protected:
- Use Kubernetes NetworkPolicies to restrict access
- Enable TLS for MongoDB connections
- Consider API authentication for production

## FAQ

**Q: Can I mix Change Streams and polling agents?**
A: Yes! Each agent independently detects the best mode. Some may use Change Streams, others polling - all work together.

**Q: What happens if MongoDB is down?**
A: Agents retry with exponential backoff. They continue processing (if already running) or stay paused (if already paused) until MongoDB recovers.

**Q: Can I force polling mode even with replica set?**
A: Yes! Set `ENABLE_CHANGE_STREAMS=false` to always use polling.

**Q: How do I know which agents received the command?**
A: Check individual pod states via `/api/agent/state` on each pod, or use centralized logging to aggregate status.

**Q: Can I rollback to a previous command?**
A: The `version` field tracks changes, but there's no built-in rollback. You can manually issue the previous command with a new version.

**Q: Does this work with StatefulSets?**
A: Yes! Works with Deployments, StatefulSets, DaemonSets - any pod-based workload.

## See Also

- [API Reference](API-REFERENCE.md) - Complete API documentation
- [Control Methods Summary](CONTROL-METHODS-SUMMARY.md) - All control options
- [Deployment Guide](../k8s/README.md) - Kubernetes setup
