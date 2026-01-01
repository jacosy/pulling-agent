# Operations Guide

## Table of Contents
- [Deployment](#deployment)
- [Monitoring](#monitoring)
- [Control Operations](#control-operations)
- [Troubleshooting](#troubleshooting)
- [Maintenance](#maintenance)

## Deployment

### Prerequisites

1. **Kubernetes cluster** (v1.24+)
2. **kubectl** configured to access your cluster
3. **MongoDB** instance accessible from the cluster
4. **Docker** for building images

### Initial Setup

1. **Build and push Docker image:**

```bash
# Build
docker build -t your-registry/pulling-agent:v1.0.0 .

# Push to registry
docker push your-registry/pulling-agent:v1.0.0

# Update image in k8s/deployment.yaml
sed -i 's|pulling-agent:latest|your-registry/pulling-agent:v1.0.0|' k8s/deployment.yaml
```

2. **Create MongoDB secret:**

```bash
# Create secret with connection string
kubectl create secret generic mongodb-secret \
  --from-literal=uri='mongodb://username:password@mongodb-host:27017/dbname?authSource=admin'

# Verify secret
kubectl get secret mongodb-secret -o yaml
```

3. **Update configuration:**

Edit `k8s/deployment.yaml` ConfigMap section:
```yaml
data:
  database: "your_database_name"
  collection: "your_collection_name"
  poll_interval: "5"
  batch_size: "100"
```

4. **Deploy to Kubernetes:**

```bash
# Apply all manifests
kubectl apply -f k8s/

# Or use Makefile
make k8s-deploy
```

5. **Verify deployment:**

```bash
# Check pod status
kubectl get pods -l app=pulling-agent

# Check logs
kubectl logs -f deployment/pulling-agent

# Check health
kubectl exec deployment/pulling-agent -- cat /tmp/health/liveness
```

## Monitoring

### Health Status

```bash
# Get pod name
POD=$(kubectl get pod -l app=pulling-agent -o jsonpath='{.items[0].metadata.name}')

# Check liveness (should update every 5 seconds)
kubectl exec $POD -- cat /tmp/health/liveness

# Example output:
# running
# 2025-01-01T10:30:45.123456
# batches=42
# documents=4200
# errors=0

# Check readiness
kubectl exec $POD -- test -f /tmp/health/readiness && echo "Ready" || echo "Not ready"
```

### Logs

```bash
# Follow logs in real-time
kubectl logs -f deployment/pulling-agent

# Last 100 lines
kubectl logs --tail=100 deployment/pulling-agent

# Logs from previous crashed container
kubectl logs deployment/pulling-agent --previous

# Filter for errors
kubectl logs deployment/pulling-agent | grep ERROR

# Watch for specific pattern
kubectl logs -f deployment/pulling-agent | grep "Processing batch"
```

### Resource Usage

```bash
# Current resource usage
kubectl top pod -l app=pulling-agent

# Describe pod (includes events)
kubectl describe pod -l app=pulling-agent

# Watch pod events
kubectl get events --watch --field-selector involvedObject.name=$POD
```

### Metrics

The agent writes statistics to the liveness file:
- `batches`: Total batches processed
- `documents`: Total documents processed
- `errors`: Total errors encountered

```bash
# Extract metrics
kubectl exec $POD -- cat /tmp/health/liveness | grep -E "batches|documents|errors"
```

## Control Operations

### Pause/Resume via ConfigMap

**Pause the agent:**
```bash
kubectl create configmap agent-control \
  --from-literal=state=pause \
  -o yaml --dry-run=client | kubectl apply -f -

# Or use Makefile
make k8s-pause

# Verify
kubectl exec $POD -- cat /tmp/control/state
# Output: pause

# Check readiness (should be gone)
kubectl exec $POD -- ls /tmp/health/readiness
# Output: ls: /tmp/health/readiness: No such file or directory
```

**Resume the agent:**
```bash
kubectl create configmap agent-control \
  --from-literal=state=resume \
  -o yaml --dry-run=client | kubectl apply -f -

# Or use Makefile
make k8s-resume

# Verify
kubectl logs -f deployment/pulling-agent
# Look for: "Resuming agent"
```

### Pause/Resume via Signals

**Pause (SIGUSR1):**
```bash
POD=$(kubectl get pod -l app=pulling-agent -o jsonpath='{.items[0].metadata.name}')
kubectl exec $POD -- kill -USR1 1
```

**Resume (SIGUSR2):**
```bash
kubectl exec $POD -- kill -USR2 1
```

### Graceful Restart

```bash
# Restart with zero downtime (if replicas > 1)
kubectl rollout restart deployment/pulling-agent

# Or delete pod (Deployment will recreate it)
kubectl delete pod -l app=pulling-agent

# Watch rollout status
kubectl rollout status deployment/pulling-agent
```

### Graceful Shutdown

```bash
# Delete deployment (allows 45 seconds for graceful shutdown)
kubectl delete deployment pulling-agent

# Watch logs during shutdown
kubectl logs -f $POD
# Look for: "Initiating graceful shutdown"
```

## Troubleshooting

### Agent Not Starting

**Symptom:** Pod stuck in `CrashLoopBackOff`

```bash
# Check logs
kubectl logs deployment/pulling-agent

# Common issues and solutions:

# 1. MongoDB connection failed
#    - Verify secret: kubectl get secret mongodb-secret -o yaml
#    - Test connectivity: kubectl run -it --rm debug --image=mongo:7 --restart=Never -- mongosh $MONGODB_URI

# 2. Missing environment variables
#    - Check deployment: kubectl get deployment pulling-agent -o yaml
#    - Verify ConfigMap: kubectl get configmap agent-config -o yaml

# 3. Image pull errors
#    - Check image name: kubectl describe pod -l app=pulling-agent
#    - Verify registry access: kubectl get events
```

### Agent Not Processing

**Symptom:** Agent running but not pulling documents

```bash
# Check if paused
kubectl exec $POD -- cat /tmp/control/state

# Check readiness
kubectl exec $POD -- ls /tmp/health/readiness

# Check logs for errors
kubectl logs deployment/pulling-agent | grep ERROR

# Verify MongoDB connectivity
kubectl exec $POD -- python3 -c "from motor.motor_asyncio import AsyncIOMotorClient; import asyncio; asyncio.run(AsyncIOMotorClient('$MONGODB_URI').admin.command('ping'))"

# Check if there are documents to process
# (Connect to MongoDB and query the collection)
```

### High Resource Usage

**Symptom:** High CPU or memory

```bash
# Check current usage
kubectl top pod -l app=pulling-agent

# Solutions:

# 1. Reduce batch size
kubectl patch configmap agent-config --type merge -p '{"data":{"batch_size":"50"}}'

# 2. Increase poll interval
kubectl patch configmap agent-config --type merge -p '{"data":{"poll_interval":"10"}}'

# 3. Increase resource limits
kubectl edit deployment pulling-agent
# Update resources.limits.memory and resources.limits.cpu

# 4. Restart to apply changes
kubectl rollout restart deployment/pulling-agent
```

### Liveness Probe Failures

**Symptom:** Pod restarting frequently

```bash
# Check probe configuration
kubectl get deployment pulling-agent -o yaml | grep -A 10 livenessProbe

# Check heartbeat file age
kubectl exec $POD -- sh -c 'stat -c %Y /tmp/health/liveness; date +%s'

# If heartbeat is stale, check if main loop is stuck
kubectl logs deployment/pulling-agent | tail -50

# Adjust probe timing if needed (deployment.yaml)
livenessProbe:
  initialDelaySeconds: 30  # Increase if slow startup
  periodSeconds: 15        # Check less frequently
  failureThreshold: 5      # Allow more failures before restart
```

### MongoDB Connection Issues

```bash
# Test MongoDB connection from pod
kubectl exec -it $POD -- sh

# Inside pod:
python3 << EOF
from motor.motor_asyncio import AsyncIOMotorClient
import asyncio

async def test():
    client = AsyncIOMotorClient('$MONGODB_URI')
    result = await client.admin.command('ping')
    print(f"Ping result: {result}")
    
    db = client['$MONGODB_DATABASE']
    collections = await db.list_collection_names()
    print(f"Collections: {collections}")

asyncio.run(test())
EOF
```

## Maintenance

### Updating Configuration

```bash
# Update ConfigMap
kubectl edit configmap agent-config

# Changes are reflected in ~60 seconds
# Agent checks /tmp/control/state every 2 seconds

# Force immediate reload by restarting
kubectl rollout restart deployment/pulling-agent
```

### Updating Secrets

```bash
# Update MongoDB connection string
kubectl create secret generic mongodb-secret \
  --from-literal=uri='mongodb://new-connection-string' \
  --dry-run=client -o yaml | kubectl apply -f -

# Restart to pick up new secret
kubectl rollout restart deployment/pulling-agent
```

### Scaling

```bash
# Scale to multiple replicas (if using leader election)
kubectl scale deployment pulling-agent --replicas=3

# Verify
kubectl get pods -l app=pulling-agent
```

### Upgrading

```bash
# Build new version
docker build -t your-registry/pulling-agent:v1.1.0 .
docker push your-registry/pulling-agent:v1.1.0

# Update image
kubectl set image deployment/pulling-agent agent=your-registry/pulling-agent:v1.1.0

# Monitor rollout
kubectl rollout status deployment/pulling-agent

# Rollback if needed
kubectl rollout undo deployment/pulling-agent
```

### Backup and Recovery

```bash
# Export current deployment
kubectl get deployment pulling-agent -o yaml > pulling-agent-backup.yaml
kubectl get configmap agent-config -o yaml > agent-config-backup.yaml

# Restore from backup
kubectl apply -f pulling-agent-backup.yaml
kubectl apply -f agent-config-backup.yaml
```

### Log Rotation

Kubernetes handles log rotation automatically, but you can configure:

```yaml
# In deployment.yaml
spec:
  template:
    spec:
      containers:
      - name: agent
        env:
        - name: LOG_LEVEL
          value: "WARNING"  # Reduce log volume
```

### Performance Tuning

**For high-throughput scenarios:**

```yaml
# Increase batch size and reduce interval
data:
  batch_size: "500"
  poll_interval: "2"

# Increase resources
resources:
  requests:
    memory: "512Mi"
    cpu: "250m"
  limits:
    memory: "1Gi"
    cpu: "1000m"
```

**For low-resource environments:**

```yaml
# Smaller batches and longer intervals
data:
  batch_size: "50"
  poll_interval: "30"

# Minimal resources
resources:
  requests:
    memory: "128Mi"
    cpu: "50m"
  limits:
    memory: "256Mi"
    cpu: "200m"
```

## Best Practices

1. **Always use graceful shutdown** - Allow the `terminationGracePeriodSeconds`
2. **Monitor health files** - Set up alerts on liveness probe failures
3. **Review logs regularly** - Watch for increasing error counts
4. **Test in staging first** - Validate configuration changes before production
5. **Document customizations** - Keep track of non-default settings
6. **Use version tags** - Never use `latest` in production
7. **Set resource limits** - Prevent runaway resource consumption
8. **Enable monitoring** - Integrate with Prometheus/Grafana if available
