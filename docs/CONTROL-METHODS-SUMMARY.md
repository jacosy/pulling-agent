# Pause/Unpause Control Methods - Quick Summary

## Overview

The pulling agent supports **5 different methods** for pause/resume operations, allowing operators to choose based on their needs:

```
┌─────────────────────────────────────────────────────────────┐
│                    Control Methods                           │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  1. Control Script (Recommended for manual ops)             │
│     ./scripts/control-agent.sh pause|resume|status          │
│     ✓ User-friendly  ✓ Verifies state  ✓ Colored output    │
│                                                              │
│  2. ConfigMap (Recommended for declarative ops)             │
│     kubectl create configmap agent-control ...              │
│     ✓ Declarative  ✓ Persistent  ✓ Auditable               │
│                                                              │
│  3. Unix Signals (For emergency/immediate response)         │
│     kubectl exec $POD -- kill -USR1 1  (pause)             │
│     ✓ Immediate  ✓ No dependencies                          │
│                                                              │
│  4. Kubernetes Jobs (For automation/CI-CD)                  │
│     kubectl apply -f k8s/jobs/control-jobs.yaml            │
│     ✓ Auditable  ✓ RBAC controlled                          │
│                                                              │
│  5. CronJobs (For scheduled operations)                     │
│     kubectl apply -f k8s/jobs/cronjobs-example.yaml        │
│     ✓ Automated  ✓ Scheduled  ✓ Repeatable                 │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

## Method Comparison

| Method | Speed | Persists | Use Case | Command |
|--------|-------|----------|----------|---------|
| **Control Script** | 2-4s | ✓ | Manual operations | `./scripts/control-agent.sh pause` |
| **ConfigMap** | 2-4s | ✓ | Declarative/GitOps | `kubectl create configmap...` |
| **Signals** | <1s | ✗ | Emergency stop | `kubectl exec $POD -- kill -USR1 1` |
| **Jobs** | 2-4s | ✓ | CI/CD pipelines | `kubectl create job pause-now...` |
| **CronJobs** | Scheduled | ✓ | Maintenance windows | `kubectl apply -f cronjobs.yaml` |

## Quick Start Examples

### Method 1: Control Script (Recommended)

```bash
# Make executable (one-time)
chmod +x scripts/control-agent.sh

# Pause
./scripts/control-agent.sh pause
# Output:
# Pausing agent...
# ConfigMap updated to 'pause'
# SIGUSR1 signal sent to pod
# Waiting for agent to pause..
# ✓ Agent successfully paused

# Check status
./scripts/control-agent.sh status
# Shows:
# - Current state (RUNNING/PAUSED/UNHEALTHY)
# - Health file contents
# - Recent logs
# - Processing statistics

# Resume
./scripts/control-agent.sh resume
# ✓ Agent successfully resumed

# Different namespace
NAMESPACE=production ./scripts/control-agent.sh pause
```

**Why use this?**
- Easiest for manual operations
- Automatic verification
- Clear colored output
- Shows detailed status

### Method 2: ConfigMap

```bash
# Pause
kubectl create configmap agent-control \
  --from-literal=state=pause \
  -o yaml --dry-run=client | kubectl apply -f -

# Resume
kubectl create configmap agent-control \
  --from-literal=state=resume \
  -o yaml --dry-run=client | kubectl apply -f -

# Using Makefile shortcuts
make k8s-pause
make k8s-resume
make k8s-control-status

# Check current ConfigMap state
kubectl get configmap agent-control -o jsonpath='{.data.state}'
```

**Why use this?**
- Declarative approach
- Works with GitOps workflows
- Survives pod restarts
- Kubernetes-native

### Method 3: Unix Signals

```bash
POD=$(kubectl get pod -l app=pulling-agent -o jsonpath='{.items[0].metadata.name}')

# Pause immediately (SIGUSR1)
kubectl exec $POD -- kill -USR1 1

# Resume immediately (SIGUSR2)
kubectl exec $POD -- kill -USR2 1

# Verify in logs
kubectl logs $POD --tail=20 | grep -i pause
```

**Why use this?**
- Immediate response (< 1 second)
- Works even if ConfigMap is broken
- Emergency situations
- No external dependencies

### Method 4: Kubernetes Jobs

```bash
# One-time setup: Deploy RBAC
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

**Why use this?**
- Perfect for CI/CD pipelines
- RBAC controlled
- Auditable via K8s events
- Can be triggered programmatically

### Method 5: CronJobs (Scheduled)

```bash
# Deploy RBAC and CronJobs
kubectl apply -f k8s/jobs/control-jobs.yaml
kubectl apply -f k8s/jobs/cronjobs-example.yaml

# View scheduled jobs
kubectl get cronjobs

NAME                         SCHEDULE      SUSPEND   ACTIVE
pause-agent-maintenance      0 2 * * *     False     0
resume-agent-maintenance     0 4 * * *     False     0

# Manually trigger a CronJob (for testing)
kubectl create job test-pause --from=cronjob/pause-agent-maintenance

# Temporarily disable a CronJob
kubectl patch cronjob pause-agent-maintenance -p '{"spec":{"suspend":true}}'

# Re-enable
kubectl patch cronjob pause-agent-maintenance -p '{"spec":{"suspend":false}}'
```

**Example schedules:**

```yaml
# Daily maintenance window: 2 AM - 4 AM
Pause:  "0 2 * * *"    # 2 AM every day
Resume: "0 4 * * *"    # 4 AM every day

# Weekday business hours: 9 AM - 6 PM
Pause:  "0 18 * * 1-5" # 6 PM weekdays
Resume: "0 9 * * 1-5"  # 9 AM weekdays

# Weekend processing only
Pause:  "0 18 * * 5"   # Friday 6 PM
Resume: "0 18 * * 0"   # Sunday 6 PM
```

**Why use this?**
- Automated maintenance windows
- Predictable schedules
- Set and forget
- Perfect for off-hours processing

## Verification

All methods can be verified the same way:

```bash
# Check state
./scripts/control-agent.sh status

# Or manually
POD=$(kubectl get pod -l app=pulling-agent -o jsonpath='{.items[0].metadata.name}')

# Readiness file exists = RUNNING, absent = PAUSED
kubectl exec $POD -- test -f /tmp/health/readiness && echo "RUNNING" || echo "PAUSED"

# Check liveness file
kubectl exec $POD -- cat /tmp/health/liveness
# Output when paused:
# paused
# 2025-01-01T10:30:45.123456
# batches=42
# documents=4200
# errors=0

# Check logs
kubectl logs $POD --tail=20 | grep -i -E "paus|resum"
```

## Decision Tree

```
Need to pause/resume?
│
├─ Manual operation? ──────────────────────────> Use Control Script
│
├─ Emergency/immediate? ───────────────────────> Use Signals
│
├─ Part of deployment pipeline? ──────────────> Use Jobs
│
├─ Regular maintenance schedule? ─────────────> Use CronJobs
│
└─ GitOps/declarative workflow? ──────────────> Use ConfigMap
```

## Common Operations

### Maintenance Window

```bash
# Before maintenance
./scripts/control-agent.sh pause
./scripts/control-agent.sh status  # Verify paused

# Perform maintenance
# ...

# After maintenance
./scripts/control-agent.sh resume
./scripts/control-agent.sh status  # Verify running
```

### CI/CD Deployment

```bash
# In your deployment script
./scripts/control-agent.sh pause
kubectl apply -f k8s/
kubectl rollout status deployment/pulling-agent
./scripts/control-agent.sh resume
```

### Emergency Stop

```bash
# Fastest way to stop processing
POD=$(kubectl get pod -l app=pulling-agent -o jsonpath='{.items[0].metadata.name}')
kubectl exec $POD -- kill -USR1 1

# Verify stopped
kubectl logs $POD --tail=5
```

### Scheduled Maintenance (Automated)

```bash
# One-time setup
kubectl apply -f k8s/jobs/control-jobs.yaml
kubectl apply -f k8s/jobs/cronjobs-example.yaml

# Monitor
kubectl get cronjobs
kubectl logs -l app=pulling-agent-control
```

## Files Reference

| File | Purpose |
|------|---------|
| `scripts/control-agent.sh` | Interactive control script |
| `k8s/configmap.yaml` | ConfigMap for control state |
| `k8s/jobs/control-jobs.yaml` | Jobs + RBAC for one-time operations |
| `k8s/jobs/cronjobs-example.yaml` | CronJobs for scheduled operations |
| `docs/PAUSE-UNPAUSE-GUIDE.md` | Comprehensive guide |

## For More Details

See the comprehensive guide: [docs/PAUSE-UNPAUSE-GUIDE.md](PAUSE-UNPAUSE-GUIDE.md)

Topics covered:
- Detailed explanation of each method
- Troubleshooting pause/resume issues
- Best practices
- Security considerations
- Integration examples
- Advanced use cases
