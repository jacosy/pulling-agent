# Pause/Unpause Operations Guide

## Overview

The pulling agent supports multiple methods for pausing and resuming operations. This allows operators to temporarily stop processing for maintenance, troubleshooting, or resource management.

## Quick Reference

```bash
# Using the control script (recommended)
./scripts/control-agent.sh pause
./scripts/control-agent.sh resume
./scripts/control-agent.sh status

# Using kubectl directly
kubectl create configmap agent-control --from-literal=state=pause -o yaml --dry-run=client | kubectl apply -f -
kubectl create configmap agent-control --from-literal=state=resume -o yaml --dry-run=client | kubectl apply -f -

# Using signals
POD=$(kubectl get pod -l app=pulling-agent -o jsonpath='{.items[0].metadata.name}')
kubectl exec $POD -- kill -USR1 1  # Pause
kubectl exec $POD -- kill -USR2 1  # Resume

# Using Makefile
make k8s-pause
make k8s-resume
```

## Control Methods

### Method 1: Control Script (Recommended)

The `control-agent.sh` script provides a user-friendly interface with automatic verification.

**Features:**
- Colored output for clarity
- Automatic state verification
- Dual-method approach (ConfigMap + signal)
- Status checking with health file inspection
- Namespace support

**Usage:**

```bash
# Make sure script is executable
chmod +x scripts/control-agent.sh

# Pause the agent
./scripts/control-agent.sh pause
# Output:
# Pausing agent...
# ConfigMap updated to 'pause'
# SIGUSR1 signal sent to pod
# Waiting for agent to pause..
# ✓ Agent successfully paused

# Resume the agent
./scripts/control-agent.sh resume
# Output:
# Resuming agent...
# ConfigMap updated to 'resume'
# SIGUSR2 signal sent to pod
# Waiting for agent to resume..
# ✓ Agent successfully resumed

# Check status
./scripts/control-agent.sh status
# Output shows:
# - Current state (RUNNING/PAUSED/UNHEALTHY)
# - Health file contents
# - ConfigMap state
# - Recent logs

# Use different namespace
NAMESPACE=production ./scripts/control-agent.sh pause
```

### Method 2: Kubernetes ConfigMap

The agent monitors `/tmp/control/state` which is mounted from a ConfigMap.

**Advantages:**
- Declarative
- Survives pod restarts
- Can be version controlled
- Auditable via K8s events

**Usage:**

```bash
# Pause
kubectl create configmap agent-control \
  --from-literal=state=pause \
  -o yaml --dry-run=client | kubectl apply -f -

# Resume
kubectl create configmap agent-control \
  --from-literal=state=resume \
  -o yaml --dry-run=client | kubectl apply -f -

# Or set to "running" (equivalent to resume)
kubectl create configmap agent-control \
  --from-literal=state=running \
  -o yaml --dry-run=client | kubectl apply -f -

# Check current ConfigMap state
kubectl get configmap agent-control -o jsonpath='{.data.state}'

# Watch for changes
kubectl get configmap agent-control -o jsonpath='{.data.state}' -w
```

**How it works:**
1. ConfigMap is mounted at `/tmp/control/`
2. Agent's control monitor task reads `/tmp/control/state` every 2 seconds
3. Agent updates its state based on the file content
4. State change is logged and reflected in health files

**Response time:** ~2-4 seconds (depends on polling interval)

### Method 3: Unix Signals

Send signals directly to the agent process for immediate response.

**Advantages:**
- Immediate (no polling delay)
- Works even if ConfigMap is unavailable
- Useful for emergency situations

**Disadvantages:**
- Doesn't persist across pod restarts
- Requires direct pod access

**Usage:**

```bash
# Get pod name
POD=$(kubectl get pod -l app=pulling-agent -o jsonpath='{.items[0].metadata.name}')

# Pause (SIGUSR1)
kubectl exec $POD -- kill -USR1 1

# Resume (SIGUSR2)
kubectl exec $POD -- kill -USR2 1

# Verify in logs
kubectl logs $POD --tail=20 | grep -i pause
```

**Signal reference:**
- `SIGUSR1` → Pause
- `SIGUSR2` → Resume
- `SIGTERM` → Graceful shutdown
- `SIGINT` → Graceful shutdown

### Method 4: Kubernetes Jobs

For one-time operations or integration with CI/CD pipelines.

**Usage:**

```bash
# Deploy RBAC (one-time setup)
kubectl apply -f k8s/jobs/control-jobs.yaml

# Run pause job
kubectl create job pause-now --from=cronjob/pause-pulling-agent

# Run resume job
kubectl create job resume-now --from=cronjob/resume-pulling-agent

# Check job status
kubectl get jobs -l app=pulling-agent-control

# View job logs
kubectl logs job/pause-now
```

### Method 5: CronJobs (Scheduled Operations)

For automated pause/resume based on schedule.

**Common use cases:**
- Maintenance windows
- Off-hours processing only
- Resource management (pause during peak hours)
- Database backup coordination

**Setup:**

```bash
# Deploy RBAC first
kubectl apply -f k8s/jobs/control-jobs.yaml

# Deploy CronJobs
kubectl apply -f k8s/jobs/cronjobs-example.yaml

# View scheduled jobs
kubectl get cronjobs

# Manually trigger a CronJob
kubectl create job manual-pause --from=cronjob/pause-agent-maintenance

# Disable a CronJob (without deleting)
kubectl patch cronjob pause-agent-maintenance -p '{"spec":{"suspend":true}}'

# Re-enable
kubectl patch cronjob pause-agent-maintenance -p '{"spec":{"suspend":false}}'
```

**Example schedules:**

```yaml
# Daily maintenance: Pause at 2 AM, resume at 4 AM
Pause:  "0 2 * * *"
Resume: "0 4 * * *"

# Weekday business hours only: Pause at 6 PM, resume at 9 AM
Pause:  "0 18 * * 1-5"
Resume: "0 9 * * 1-5"

# Weekend processing only: Pause Friday 6 PM, resume Sunday 6 PM
Pause:  "0 18 * * 5"
Resume: "0 18 * * 0"
```

## Verification

### Check Current State

```bash
# Using control script
./scripts/control-agent.sh status

# Or manually
POD=$(kubectl get pod -l app=pulling-agent -o jsonpath='{.items[0].metadata.name}')

# Check readiness file (exists = RUNNING, absent = PAUSED)
kubectl exec $POD -- test -f /tmp/health/readiness && echo "RUNNING" || echo "PAUSED"

# Check liveness file content
kubectl exec $POD -- cat /tmp/health/liveness

# Check logs
kubectl logs $POD --tail=20 | grep -i -E "paus|resum"
```

### Expected Behavior

**When pausing:**
1. Agent completes current batch processing
2. State changes to `PAUSED`
3. Readiness file (`/tmp/health/readiness`) is removed
4. Liveness file shows `paused` state
5. Log message: `"Pausing agent"`
6. Agent waits at pause event

**When resuming:**
1. State changes to `RUNNING`
2. Readiness file is created
3. Liveness file shows `running` state
4. Log message: `"Resuming agent"`
5. Agent continues processing next batch

**Response times:**
- Signal method: Immediate (< 1 second)
- ConfigMap method: 2-4 seconds
- After batch completion: Up to batch processing time + response time

## Troubleshooting

### Agent Not Pausing

**Check ConfigMap:**
```bash
kubectl get configmap agent-control -o yaml
# Should show: state: pause
```

**Check control file in pod:**
```bash
POD=$(kubectl get pod -l app=pulling-agent -o jsonpath='{.items[0].metadata.name}')
kubectl exec $POD -- cat /tmp/control/state
# Should show: pause
```

**Check logs:**
```bash
kubectl logs $POD --tail=50 | grep -i pause
# Look for: "Control file command detected: pause"
# Look for: "Pausing agent"
```

**Common issues:**
1. **ConfigMap not mounted** - Check deployment volumeMounts
2. **Control monitor task crashed** - Check for exceptions in logs
3. **Still processing batch** - Wait for current batch to complete
4. **Wrong state** - Can't pause from PAUSED or STOPPING state

### Agent Not Resuming

**Check state:**
```bash
kubectl exec $POD -- cat /tmp/health/liveness | head -1
# Should transition from 'paused' to 'running'
```

**Force resume with both methods:**
```bash
# Update ConfigMap
kubectl create configmap agent-control --from-literal=state=resume -o yaml --dry-run=client | kubectl apply -f -

# Send signal
kubectl exec $POD -- kill -USR2 1

# Check logs
kubectl logs $POD -f
```

### State Mismatch

If ConfigMap says "pause" but agent is running:

```bash
# Force consistency by restarting pod
kubectl delete pod $POD

# Or update ConfigMap to match actual state
kubectl create configmap agent-control --from-literal=state=running -o yaml --dry-run=client | kubectl apply -f -
```

## Best Practices

### 1. Always Verify State After Operations

```bash
# Don't just pause and assume it worked
./scripts/control-agent.sh pause
./scripts/control-agent.sh status
# Or check readiness explicitly
```

### 2. Document Pause Reasons

```bash
# Add annotation when pausing for operations
kubectl annotate pod $POD \
  paused-reason="Database maintenance" \
  paused-by="ops-team" \
  paused-at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# View annotations later
kubectl get pod $POD -o jsonpath='{.metadata.annotations}'
```

### 3. Set Alerts

Monitor for unexpected pause states:

```yaml
# Prometheus alert example
- alert: PullingAgentUnexpectedlyPaused
  expr: pulling_agent_state == "paused" AND pulling_agent_expected_state == "running"
  for: 5m
  annotations:
    summary: "Pulling agent is paused but should be running"
```

### 4. Use CronJobs for Scheduled Operations

Instead of manual pause/resume for regular maintenance:
- Create CronJobs for predictable windows
- Monitor CronJob execution
- Keep history for audit trail

### 5. Test in Staging First

```bash
# Test pause/resume in staging
NAMESPACE=staging ./scripts/control-agent.sh pause
# Verify behavior
# Then apply to production
NAMESPACE=production ./scripts/control-agent.sh pause
```

### 6. Coordinate with Dependent Systems

If other systems depend on this agent:
- Pause downstream consumers first
- Pause this agent
- Resume this agent
- Resume downstream consumers

### 7. Monitor Processing Lag

```bash
# Before pausing, check if agent is behind
./scripts/control-agent.sh status | grep documents

# After resuming, monitor catch-up
watch -n 5 './scripts/control-agent.sh status | grep documents'
```

## Integration Examples

### CI/CD Pipeline

```yaml
# GitLab CI example
deploy:
  script:
    - ./scripts/control-agent.sh pause
    - kubectl apply -f k8s/
    - kubectl rollout status deployment/pulling-agent
    - ./scripts/control-agent.sh resume
```

### Monitoring Alert Response

```bash
#!/bin/bash
# auto-pause-on-alert.sh
# Webhook handler that pauses agent when alert fires

if [ "$ALERT_STATUS" = "firing" ]; then
    kubectl create configmap agent-control \
      --from-literal=state=pause \
      -o yaml --dry-run=client | kubectl apply -f -
    echo "Agent paused due to alert: $ALERT_NAME"
fi
```

### Manual Runbook

```markdown
## Database Maintenance Runbook

1. Pause pulling agent:
   ```
   ./scripts/control-agent.sh pause
   ./scripts/control-agent.sh status  # Verify paused
   ```

2. Perform database maintenance

3. Resume pulling agent:
   ```
   ./scripts/control-agent.sh resume
   ./scripts/control-agent.sh status  # Verify running
   ```

4. Monitor for 10 minutes to ensure normal operation
```

## Security Considerations

### RBAC for Control Operations

The control Jobs require RBAC permissions to update ConfigMaps:

```yaml
# See k8s/jobs/control-jobs.yaml for full RBAC setup
- apiGroups: [""]
  resources: ["configmaps"]
  verbs: ["get", "create", "update", "patch"]
  resourceNames: ["agent-control"]
```

### Audit Trail

All control operations via ConfigMap are audited by Kubernetes:

```bash
# View who changed ConfigMap
kubectl get events --field-selector involvedObject.name=agent-control

# View ConfigMap history (if using GitOps)
git log k8s/configmap.yaml
```

## Summary

| Method | Speed | Persistence | Recommended For |
|--------|-------|-------------|-----------------|
| Control Script | Fast | Yes (ConfigMap) | **General use** |
| ConfigMap | 2-4s | Yes | Declarative ops |
| Signals | Immediate | No | Emergency |
| Jobs | Fast | Yes | Automation |
| CronJobs | Scheduled | Yes | Regular maintenance |

**Recommendation:** Use `control-agent.sh` for manual operations, CronJobs for scheduled operations, and signals only for emergencies.
