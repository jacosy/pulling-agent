# Kubernetes Jobs and CronJobs for Worker Control

This directory contains Kubernetes Job and CronJob manifests for controlling pulling agent workers.

## Control Methods

### 🌟 Distributed Worker Control (Recommended)

Controls **ALL workers** simultaneously using MongoDB-based distributed coordination.

**Files:**
- `worker-control-jobs.yaml` - One-time jobs for pause/resume/status
- `worker-cronjobs.yaml` - Scheduled CronJobs for automated control

**Advantages:**
- ✅ Controls all workers at once (distributed)
- ✅ Sub-second propagation via MongoDB Change Streams
- ✅ Persistent state (survives pod restarts)
- ✅ Full audit trail (version, timestamp, reason, updated_by)
- ✅ No RBAC permissions needed (uses Service)
- ✅ Works with multiple replicas/pods

**Method:** HTTP API (`/api/worker/*`)

**Example:**
```bash
kubectl apply -f worker-control-jobs.yaml
```

### 📁 ConfigMap-Based Control (Legacy)

Controls **individual pods** via ConfigMap updates.

**Files:**
- `control-jobs.yaml` - One-time jobs for pause/resume via ConfigMap
- `cronjobs-example.yaml` - Scheduled CronJobs via ConfigMap

**Advantages:**
- ✅ Works without Service/HTTP access
- ✅ Simple kubectl commands

**Disadvantages:**
- ❌ Controls single pod only (not distributed)
- ❌ Requires RBAC permissions
- ❌ No version tracking or audit trail
- ❌ 2-second polling delay

**Method:** ConfigMap updates

**Example:**
```bash
kubectl apply -f control-jobs.yaml
```

## Quick Reference

### Distributed Worker Control

```bash
# Pause all workers
kubectl apply -f worker-control-jobs.yaml
kubectl wait --for=condition=complete job/pause-all-workers

# Resume all workers
kubectl delete job pause-all-workers  # Clean up first
kubectl apply -f worker-control-jobs.yaml
kubectl wait --for=condition=complete job/resume-all-workers

# Check worker state
kubectl delete job resume-all-workers  # Clean up
kubectl apply -f worker-control-jobs.yaml
kubectl wait --for=condition=complete job/check-worker-state
kubectl logs job/check-worker-state

# Install scheduled CronJobs
kubectl apply -f worker-cronjobs.yaml

# Test a CronJob immediately
kubectl create job test-pause --from=cronjob/pause-workers-maintenance
kubectl logs job/test-pause
```

### ConfigMap-Based Control

```bash
# Pause agent (ConfigMap method)
kubectl apply -f control-jobs.yaml
kubectl wait --for=condition=complete job/pause-pulling-agent-configmap

# Resume agent (ConfigMap method)
kubectl delete job pause-pulling-agent-configmap
kubectl apply -f control-jobs.yaml
kubectl wait --for=condition=complete job/resume-pulling-agent-configmap

# Install scheduled CronJobs (ConfigMap method)
kubectl apply -f cronjobs-example.yaml
```

## Comparison

| Feature | Distributed Worker Control | ConfigMap Control |
|---------|---------------------------|-------------------|
| **Controls** | ALL workers | Single pod |
| **Propagation** | < 1s (Change Streams) or ~10s (polling) | ~2s |
| **RBAC Needed** | ❌ No | ✅ Yes |
| **Audit Trail** | ✅ Full (version, reason, who, when) | ❌ None |
| **Survives Restart** | ✅ Yes | ❌ No |
| **Multiple Replicas** | ✅ Yes | ❌ No |
| **Recommended** | ✅ Yes | ❌ Legacy only |

## Environment Variables

For distributed worker control, ensure your deployment has:

```yaml
env:
- name: ENABLE_DISTRIBUTED_CONTROL
  value: "true"
- name: ENABLE_CHANGE_STREAMS
  value: "true"
- name: CONTROL_POLLING_INTERVAL
  value: "10"
```

See `../deployment.yaml` for complete configuration.

## Testing

### Test Distributed Worker Control

```bash
# 1. Apply the jobs
kubectl apply -f worker-control-jobs.yaml

# 2. Pause all workers
kubectl delete job pause-all-workers 2>/dev/null || true
kubectl create job pause-all-workers --from=job/pause-all-workers
kubectl wait --for=condition=complete --timeout=60s job/pause-all-workers
kubectl logs job/pause-all-workers

# 3. Check state
kubectl exec -it deployment/pulling-agent -- \
  curl -s localhost:8000/api/worker/control-state | jq

# 4. Resume all workers
kubectl delete job resume-all-workers 2>/dev/null || true
kubectl create job resume-all-workers --from=job/resume-all-workers
kubectl wait --for=condition=complete --timeout=60s job/resume-all-workers
kubectl logs job/resume-all-workers

# 5. Verify
kubectl exec -it deployment/pulling-agent -- \
  curl -s localhost:8000/api/worker/control-state | jq
```

### Test ConfigMap Control

```bash
# 1. Apply the jobs
kubectl apply -f control-jobs.yaml

# 2. Pause agent (ConfigMap)
kubectl delete job pause-pulling-agent-configmap 2>/dev/null || true
kubectl create job pause-test --from=job/pause-pulling-agent-configmap
kubectl wait --for=condition=complete --timeout=60s job/pause-test
kubectl logs job/pause-test

# 3. Check ConfigMap
kubectl get configmap agent-control -o yaml

# 4. Check pod logs
kubectl logs -l app=pulling-agent --tail=50 | grep -i pause

# 5. Resume agent (ConfigMap)
kubectl delete job resume-pulling-agent-configmap 2>/dev/null || true
kubectl create job resume-test --from=job/resume-pulling-agent-configmap
kubectl wait --for=condition=complete --timeout=60s job/resume-test
kubectl logs job/resume-test
```

## Cleanup

```bash
# Remove jobs
kubectl delete job -l app=pulling-agent-control

# Remove CronJobs
kubectl delete cronjob -l app=pulling-agent-control

# Remove RBAC (if using ConfigMap method)
kubectl delete serviceaccount agent-controller
kubectl delete role agent-controller
kubectl delete rolebinding agent-controller
```

## See Also

- [Distributed Control Documentation](../../docs/DISTRIBUTED-CONTROL.md)
- [Quick Start Guide](../../docs/DISTRIBUTED-CONTROL-QUICKSTART.md)
- [API Reference](../../docs/API-REFERENCE.md)
- [Deployment Configuration](../deployment.yaml)
