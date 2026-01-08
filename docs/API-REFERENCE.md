# API Reference

The Pulling Agent now exposes HTTP API endpoints for control and monitoring, eliminating the need for `kubectl exec` in production environments.

## Base URL

```
http://pulling-agent:8000
```

In development or when port-forwarding:
```bash
kubectl port-forward svc/pulling-agent 8000:8000
curl http://localhost:8000
```

## Authentication

Currently, the API does not implement authentication. For production use:
- Deploy behind an API gateway with authentication
- Use Kubernetes NetworkPolicies to restrict access
- Consider adding API key authentication if needed

## API Endpoints

### Root

**GET /**

Returns basic API information.

**Response:**
```json
{
  "service": "Pulling Agent API",
  "version": "1.0.0",
  "status": "running"
}
```

---

### Health Check (Liveness)

**GET /health**

Liveness probe - checks if the agent is alive.

**Replaces:** `kubectl exec $POD -- cat /tmp/health/liveness`

**Response (200 OK):**
```json
{
  "status": "healthy",
  "timestamp": "2025-01-08T12:34:56.789",
  "state": "running"
}
```

**Possible States:** `running`, `paused`, `stopping`, `stopped`

---

### Readiness Check

**GET /readiness**

Readiness probe - checks if the agent is ready to process documents.

**Replaces:** `kubectl exec $POD -- test -f /tmp/health/readiness`

**Response (200 OK):**
```json
{
  "status": "ready",
  "timestamp": "2025-01-08T12:34:56.789",
  "state": "running"
}
```

**Response (503 Service Unavailable):**
```json
{
  "detail": "Agent not ready (state: paused)"
}
```

---

### Get Agent State

**GET /api/agent/state**

Get the current operational state of the agent.

**Response (200 OK):**
```json
{
  "state": "running",
  "timestamp": "2025-01-08T12:34:56.789"
}
```

**Possible States:**
- `running` - Agent is actively processing documents
- `paused` - Agent is paused, not processing
- `stopping` - Agent is shutting down gracefully
- `stopped` - Agent has stopped

---

### Pause Agent

**POST /api/agent/pause**

Pause the agent's processing. Current batch will complete before pausing.

**Replaces:** `kubectl exec $POD -- kill -USR1 1`

**Response (200 OK):**
```json
{
  "message": "Agent paused successfully",
  "state": "paused"
}
```

**Response (400 Bad Request):**
```json
{
  "detail": "Cannot pause from state: stopped"
}
```

**Example:**
```bash
curl -X POST http://localhost:8000/api/agent/pause
```

---

### Resume Agent

**POST /api/agent/resume**

Resume the agent's processing after being paused.

**Replaces:** `kubectl exec $POD -- kill -USR2 1`

**Response (200 OK):**
```json
{
  "message": "Agent resumed successfully",
  "state": "running"
}
```

**Response (400 Bad Request):**
```json
{
  "detail": "Cannot resume from state: running"
}
```

**Example:**
```bash
curl -X POST http://localhost:8000/api/agent/resume
```

---

### Shutdown Agent

**POST /api/agent/shutdown**

Initiate graceful shutdown of the agent.

**Replaces:** `kubectl exec $POD -- kill -TERM 1`

**Response (202 Accepted):**
```json
{
  "message": "Shutdown initiated",
  "state": "stopping"
}
```

**Note:** Returns 202 (Accepted) because shutdown is asynchronous.

**Example:**
```bash
curl -X POST http://localhost:8000/api/agent/shutdown
```

---

### Get Processing Statistics

**GET /api/stats**

Get comprehensive processing statistics.

**Replaces:** Parsing `/tmp/health/liveness` file contents

**Response (200 OK):**
```json
{
  "state": "running",
  "batches_processed": 1523,
  "documents_processed": 152300,
  "errors_count": 5,
  "last_heartbeat": "2025-01-08T12:34:56.789",
  "uptime_seconds": 86400.5
}
```

**Example:**
```bash
curl http://localhost:8000/api/stats
```

---

### Get Configuration

**GET /api/config**

Get current agent configuration (non-sensitive values only).

**Response (200 OK):**
```json
{
  "mongodb_database": "mydb",
  "mongodb_collection": "mycollection",
  "poll_interval": 5,
  "batch_size": 100,
  "heartbeat_interval": 5,
  "log_level": "INFO"
}
```

**Note:** MongoDB URI and other secrets are not exposed.

---

### MongoDB Connection Status

**GET /api/mongo/status**

Check MongoDB connection status.

**Replaces:** `kubectl exec $POD -- python3 -c "from motor... ping"`

**Response (200 OK):**
```json
{
  "connected": true,
  "database": "mydb",
  "collection": "mycollection",
  "ping_response": {
    "ok": 1.0
  }
}
```

**Response (503 Service Unavailable):**
```json
{
  "detail": "MongoDB connection error: ..."
}
```

---

## Interactive API Documentation

FastAPI automatically generates interactive API documentation:

### Swagger UI
```
http://pulling-agent:8000/docs
```

### ReDoc
```
http://pulling-agent:8000/redoc
```

### OpenAPI Schema
```
http://pulling-agent:8000/openapi.json
```

---

## Usage Examples

### Check if Agent is Running
```bash
curl http://pulling-agent:8000/health
```

### Pause Processing During Maintenance
```bash
# Pause the agent
curl -X POST http://pulling-agent:8000/api/agent/pause

# Perform maintenance...

# Resume processing
curl -X POST http://pulling-agent:8000/api/agent/resume
```

### Monitor Processing Statistics
```bash
# Get current stats
curl http://pulling-agent:8000/api/stats | jq

# Watch stats in real-time
watch -n 5 'curl -s http://pulling-agent:8000/api/stats | jq'
```

### Check MongoDB Connection
```bash
curl http://pulling-agent:8000/api/mongo/status | jq
```

### Get Current State
```bash
curl http://pulling-agent:8000/api/agent/state
```

---

## Error Responses

All error responses follow this format:

```json
{
  "detail": "Error description here"
}
```

**Common HTTP Status Codes:**
- `200 OK` - Request successful
- `202 Accepted` - Request accepted (async operation)
- `400 Bad Request` - Invalid request or state transition
- `503 Service Unavailable` - Service not ready or connection failed

---

## Integration with Monitoring Tools

### Prometheus Metrics (Future Enhancement)
Consider adding `/metrics` endpoint for Prometheus scraping.

### Health Check Integration
The `/health` and `/readiness` endpoints are designed to work with:
- Kubernetes probes (already configured)
- Load balancers
- Monitoring systems (Datadog, New Relic, etc.)
- Uptime monitoring (UptimeRobot, Pingdom, etc.)

---

## Migration from kubectl exec

| Old Method | New API Endpoint |
|------------|------------------|
| `kubectl exec $POD -- kill -USR1 1` | `POST /api/agent/pause` |
| `kubectl exec $POD -- kill -USR2 1` | `POST /api/agent/resume` |
| `kubectl exec $POD -- kill -TERM 1` | `POST /api/agent/shutdown` |
| `kubectl exec $POD -- cat /tmp/health/liveness` | `GET /api/stats` |
| `kubectl exec $POD -- test -f /tmp/health/readiness` | `GET /readiness` |
| `kubectl exec $POD -- ls -la /tmp/health/` | `GET /health` + `GET /readiness` |
| MongoDB connection test | `GET /api/mongo/status` |

---

## Security Considerations

1. **Network Policies**: Restrict access to the API service using Kubernetes NetworkPolicies
2. **Service Mesh**: Use Istio/Linkerd for mTLS and authentication
3. **API Gateway**: Deploy Kong/Ambassador for rate limiting and authentication
4. **RBAC**: Use Kubernetes RBAC to control who can access the service
5. **Audit Logging**: All API calls are logged for audit purposes

---

## Next Steps

To enhance the API further, consider:
1. Adding API key authentication
2. Implementing rate limiting
3. Adding Prometheus metrics endpoint
4. Implementing webhook notifications
5. Adding batch operation endpoints
6. Implementing API versioning
