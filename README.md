# MongoDB Pulling Agent

A robust, production-ready background job for pulling data from MongoDB collections, designed to run on Kubernetes.

## Features

- ✅ **HTTP API endpoints** for control and monitoring (no kubectl exec required)
- ✅ Graceful shutdown handling (SIGTERM/SIGINT)
- ✅ HTTP-based health checks for Kubernetes probes
- ✅ Pause/resume control via API, signals, or ConfigMap
- ✅ Interruptible polling with configurable intervals
- ✅ Heartbeat monitoring for liveness detection
- ✅ Structured logging
- ✅ Async MongoDB operations with Motor
- ✅ Production-ready with comprehensive monitoring

## Architecture

```
┌───────────────────────────────────────────────┐
│         Kubernetes Pod                        │
│  ┌─────────────────────────────────────────┐  │
│  │     Pulling Agent Process               │  │
│  │                                         │  │
│  │  ┌───────────────────────────────────┐  │  │
│  │  │   FastAPI Server (Port 8000)      │  │  │
│  │  │   - Control endpoints             │  │  │
│  │  │   - Health/Readiness probes       │  │  │
│  │  │   - Statistics & monitoring       │  │  │
│  │  └───────────────────────────────────┘  │  │
│  │                                         │  │
│  │  ┌───────────────────────────────────┐  │  │
│  │  │   Main Event Loop                 │  │  │
│  │  │   - Poll MongoDB                  │  │  │
│  │  │   - Process batches               │  │  │
│  │  │   - Handle signals                │  │  │
│  │  └───────────────────────────────────┘  │  │
│  │                                         │  │
│  │  ┌───────────────────────────────────┐  │  │
│  │  │  Background Tasks                 │  │  │
│  │  │  - Heartbeat monitoring           │  │  │
│  │  │  - Control file monitoring        │  │  │
│  │  └───────────────────────────────────┘  │  │
│  └─────────────────────────────────────────┘  │
│                                               │
│  Service: pulling-agent:8000 (ClusterIP)      │
│  Volume: /tmp/health (emptyDir)               │
│  Volume: /tmp/control (ConfigMap)             │
└───────────────────────────────────────────────┘
         ↓
    MongoDB Cluster
```

## Project Structure

```
pulling-agent/
├── src/
│   ├── __init__.py
│   ├── agent.py           # Core PullingAgent class
│   ├── api.py             # FastAPI endpoints for control & monitoring
│   ├── config.py          # Configuration management
│   ├── main.py            # Application entry point
│   └── mongo_client.py    # MongoDB connection handling
├── k8s/
│   ├── deployment.yaml    # Kubernetes Deployment + Service
│   ├── configmap.yaml     # Control ConfigMap
│   └── secret.yaml        # MongoDB credentials (example)
├── docs/
│   └── API-REFERENCE.md   # API documentation
├── tests/
│   ├── __init__.py
│   └── test_agent.py      # Unit tests
├── Dockerfile
├── requirements.txt
├── .dockerignore
├── .gitignore
└── README.md
```

## Quick Start

### Local Development

1. **Install dependencies:**
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

2. **Set environment variables:**
```bash
export MONGODB_URI="mongodb://localhost:27017"
export MONGODB_DATABASE="mydb"
export MONGODB_COLLECTION="mycollection"
export POLL_INTERVAL=5
export LOG_LEVEL=INFO
```

3. **Run the agent:**
```bash
python -m src.main
```

### Docker Build

```bash
# Build image
docker build -t pulling-agent:latest .

# Run locally
docker run -e MONGODB_URI="mongodb://host.docker.internal:27017" \
           -e MONGODB_DATABASE="mydb" \
           -e MONGODB_COLLECTION="mycollection" \
           pulling-agent:latest
```

### Kubernetes Deployment

1. **Create MongoDB secret:**
```bash
kubectl create secret generic mongodb-secret \
  --from-literal=uri='mongodb://username:password@mongodb-service:27017'
```

2. **Deploy the agent:**
```bash
kubectl apply -f k8s/
```

3. **Check status:**
```bash
# View logs
kubectl logs -f deployment/pulling-agent

# Check health files
kubectl exec deployment/pulling-agent -- ls -la /tmp/health/

# View pod status
kubectl get pods -l app=pulling-agent
```

## Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `MONGODB_URI` | Yes | - | MongoDB connection string |
| `MONGODB_DATABASE` | Yes | - | Database name |
| `MONGODB_COLLECTION` | Yes | - | Collection to pull from |
| `POLL_INTERVAL` | No | 5 | Seconds between poll cycles |
| `BATCH_SIZE` | No | 100 | Documents per batch |
| `SHUTDOWN_TIMEOUT` | No | 30 | Graceful shutdown timeout (seconds) |
| `LOG_LEVEL` | No | INFO | Logging level (DEBUG, INFO, WARNING, ERROR) |
| `HEARTBEAT_INTERVAL` | No | 5 | Heartbeat update interval (seconds) |
| `API_HOST` | No | 0.0.0.0 | API server bind address |
| `API_PORT` | No | 8000 | API server port |

## Control Operations

The agent provides multiple methods for control and monitoring. **HTTP API is the recommended method for production environments** as it doesn't require `kubectl exec` access.

### API Endpoints (Recommended for Production)

**Port forward to access the API:**
```bash
kubectl port-forward svc/pulling-agent 8000:8000
```

**Pause the agent:**
```bash
curl -X POST http://localhost:8000/api/agent/pause
```

**Resume the agent:**
```bash
curl -X POST http://localhost:8000/api/agent/resume
```

**Check status:**
```bash
curl http://localhost:8000/api/agent/state
curl http://localhost:8000/api/stats
```

**Health checks:**
```bash
curl http://localhost:8000/health
curl http://localhost:8000/readiness
```

📖 **See [docs/API-REFERENCE.md](docs/API-REFERENCE.md) for complete API documentation.**

### Alternative Control Methods

**Using the control script:**
```bash
# Pause the agent
./scripts/control-agent.sh pause

# Resume the agent
./scripts/control-agent.sh resume

# Check status
./scripts/control-agent.sh status

# Restart the agent
./scripts/control-agent.sh restart
```

### Pause/Resume via ConfigMap

```bash
# Pause the agent
kubectl create configmap agent-control \
  --from-literal=state=pause \
  -o yaml --dry-run=client | kubectl apply -f -

# Resume the agent
kubectl create configmap agent-control \
  --from-literal=state=resume \
  -o yaml --dry-run=client | kubectl apply -f -

# Or use Makefile shortcuts
make k8s-pause
make k8s-resume
```

### Pause/Resume via Signals (Legacy)

> **Note:** Use the HTTP API instead of kubectl exec for production environments.

```bash
# Get pod name
POD=$(kubectl get pod -l app=pulling-agent -o jsonpath='{.items[0].metadata.name}')

# Pause (SIGUSR1)
kubectl exec $POD -- kill -USR1 1

# Resume (SIGUSR2)
kubectl exec $POD -- kill -USR2 1
```

### Scheduled Pause/Resume

For automated control based on schedule, see `k8s/jobs/cronjobs-example.yaml`:

```bash
# Deploy CronJobs for scheduled operations
kubectl apply -f k8s/jobs/cronjobs-example.yaml

# Example: Pause at 2 AM, resume at 4 AM daily
# Or pause during business hours, resume outside
```

**For detailed pause/unpause operations, see [docs/PAUSE-UNPAUSE-GUIDE.md](docs/PAUSE-UNPAUSE-GUIDE.md)**

## Health Checks

The agent uses file-based health checks:

- **Liveness**: `/tmp/health/liveness` - Updated every 5 seconds by heartbeat
- **Readiness**: `/tmp/health/readiness` - Exists only when agent is ready to process

### Manual Health Check

```bash
# Check if agent is alive (file modified within 30 seconds)
kubectl exec deployment/pulling-agent -- sh -c \
  'test -f /tmp/health/liveness && \
   [ $(($(date +%s) - $(stat -c %Y /tmp/health/liveness))) -lt 30 ]' \
  && echo "Healthy" || echo "Unhealthy"

# Check if agent is ready
kubectl exec deployment/pulling-agent -- test -f /tmp/health/readiness \
  && echo "Ready" || echo "Not Ready"
```

## Monitoring

### Logs

```bash
# Follow logs
kubectl logs -f deployment/pulling-agent

# Last 100 lines
kubectl logs --tail=100 deployment/pulling-agent

# Logs from previous crashed container
kubectl logs deployment/pulling-agent --previous
```

### Events

```bash
# View pod events
kubectl describe pod -l app=pulling-agent

# Watch events
kubectl get events --watch
```

## Business Logic Implementation

The current implementation has a placeholder `_process_batch()` method. Implement your MongoDB pulling logic:

```python
# src/agent.py
async def _process_batch(self):
    """Pull and process documents from MongoDB"""
    cursor = self.collection.find(
        {"status": "pending"},
        limit=self.config.batch_size
    )
    
    documents = await cursor.to_list(length=self.config.batch_size)
    
    if not documents:
        logger.debug("No pending documents found")
        return
    
    logger.info(f"Processing {len(documents)} documents")
    
    for doc in documents:
        try:
            # Your processing logic here
            await self._process_document(doc)
            
            # Mark as processed
            await self.collection.update_one(
                {"_id": doc["_id"]},
                {"$set": {"status": "processed", "processed_at": datetime.utcnow()}}
            )
        except Exception as e:
            logger.error(f"Failed to process document {doc['_id']}: {e}")
            await self.collection.update_one(
                {"_id": doc["_id"]},
                {"$set": {"status": "failed", "error": str(e)}}
            )
```

## Testing

```bash
# Run unit tests
python -m pytest tests/ -v

# Run with coverage
python -m pytest tests/ --cov=src --cov-report=html

# Run specific test
python -m pytest tests/test_agent.py::test_pause_resume -v
```

## Troubleshooting

### Agent not starting

```bash
# Check pod status
kubectl describe pod -l app=pulling-agent

# Check logs
kubectl logs deployment/pulling-agent

# Common issues:
# - MongoDB connection failed (check secret and network)
# - Missing environment variables
# - Image pull errors
```

### Agent not processing

```bash
# Check if paused
kubectl exec deployment/pulling-agent -- cat /tmp/control/state

# Check readiness
kubectl exec deployment/pulling-agent -- ls /tmp/health/

# Verify MongoDB connection
kubectl exec deployment/pulling-agent -- cat /tmp/health/liveness
```

### High CPU/Memory usage

```bash
# Check resource usage
kubectl top pod -l app=pulling-agent

# Adjust resources in deployment.yaml
# Reduce BATCH_SIZE if memory is high
# Increase POLL_INTERVAL if CPU is high
```

## Production Considerations

1. **MongoDB Connection Pooling**: Motor handles this automatically
2. **Error Handling**: Implement retry logic with exponential backoff
3. **Dead Letter Queue**: Store failed documents for manual review
4. **Metrics**: Add Prometheus metrics for observability
5. **Circuit Breaker**: Pause processing if MongoDB is unhealthy
6. **Rate Limiting**: Respect MongoDB cluster capacity
7. **Idempotency**: Ensure processing can safely retry
8. **Alerting**: Set up alerts on liveness failures

## License

MIT

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Submit a pull request
