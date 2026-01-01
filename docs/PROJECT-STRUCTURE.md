# Project Structure

```
pulling-agent/
├── src/                          # Application source code
│   ├── __init__.py              # Package initialization
│   ├── agent.py                 # Core PullingAgent class (330 lines)
│   ├── config.py                # Configuration management
│   ├── main.py                  # Application entry point
│   └── mongo_client.py          # MongoDB connection wrapper
│
├── k8s/                          # Kubernetes manifests
│   ├── deployment.yaml          # Deployment + ConfigMap
│   ├── configmap.yaml           # Control ConfigMap
│   ├── secret.yaml.example      # Secret template (don't commit real secrets!)
│   └── jobs/                    # Control jobs and CronJobs
│       ├── control-jobs.yaml    # One-time pause/resume Jobs + RBAC
│       └── cronjobs-example.yaml # Scheduled pause/resume CronJobs
│
├── tests/                        # Unit tests
│   ├── __init__.py
│   └── test_agent.py            # Agent tests with pytest
│
├── scripts/                      # Utility scripts
│   ├── health-check.sh          # Advanced health check script
│   └── control-agent.sh         # Pause/resume/status control script
│
├── docs/                         # Documentation
│   ├── OPERATIONS.md            # Operations guide
│   ├── QUICK-REFERENCE.md       # Quick reference card
│   ├── PAUSE-UNPAUSE-GUIDE.md   # Detailed pause/unpause operations
│   └── PROJECT-STRUCTURE.md     # This file
│
├── Dockerfile                    # Docker image definition
├── requirements.txt              # Python dependencies (production)
├── requirements-dev.txt          # Python dependencies (development)
├── Makefile                      # Common tasks automation
├── .dockerignore                 # Docker build exclusions
├── .gitignore                    # Git exclusions
├── .env.example                  # Environment variables template
├── README.md                     # Main documentation
├── CHANGELOG.md                  # Version history
└── LICENSE                       # MIT License
```

## File Descriptions

### Source Code (`src/`)

| File | Lines | Description |
|------|-------|-------------|
| `agent.py` | ~330 | Main agent implementation with event loop, health checks, signal handling |
| `config.py` | ~60 | Configuration dataclass with validation and env loading |
| `main.py` | ~50 | Entry point that sets up logging and runs the agent |
| `mongo_client.py` | ~60 | MongoDB connection manager with Motor |

### Kubernetes (`k8s/`)

| File | Description |
|------|-------------|
| `deployment.yaml` | Deployment with 1 replica, health probes, resource limits, ConfigMap |
| `configmap.yaml` | Control ConfigMap for pause/resume commands |
| `secret.yaml.example` | Template for MongoDB credentials (must create real secret) |

### Tests (`tests/`)

| File | Description |
|------|-------------|
| `test_agent.py` | Unit tests for config, agent lifecycle, pause/resume, health files |

### Documentation (`docs/`)

| File | Description |
|------|-------------|
| `OPERATIONS.md` | Comprehensive operations guide with troubleshooting |
| `QUICK-REFERENCE.md` | One-page reference for common commands |

### Configuration Files

| File | Purpose |
|------|---------|
| `Dockerfile` | Multi-stage build, non-root user, Python 3.11 |
| `requirements.txt` | Motor 3.3.2, PyMongo 4.6.1 |
| `requirements-dev.txt` | Adds pytest, black, flake8 |
| `Makefile` | Commands for test, lint, docker-build, k8s-deploy, etc. |
| `.env.example` | Template for local development environment variables |

## Key Components

### Agent Lifecycle
1. Load config from environment
2. Connect to MongoDB
3. Start heartbeat task (updates liveness every 5s)
4. Start control monitor task (checks ConfigMap every 2s)
5. Enter main loop:
   - Wait if paused
   - Process one batch from MongoDB
   - Sleep (interruptible) for poll_interval
6. On shutdown signal:
   - Cancel background tasks
   - Close MongoDB connection
   - Remove health files
   - Exit gracefully

### Health Checks
- **Liveness**: `/tmp/health/liveness` - Updated by heartbeat task
- **Readiness**: `/tmp/health/readiness` - Exists when state=RUNNING
- **Control**: `/tmp/control/state` - Read by control monitor task

### Signal Handling
- **SIGTERM/SIGINT**: Graceful shutdown
- **SIGUSR1**: Pause processing
- **SIGUSR2**: Resume processing

## Development Workflow

1. **Local Development**
   ```bash
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements-dev.txt
   export MONGODB_URI="mongodb://localhost:27017"
   export MONGODB_DATABASE="testdb"
   export MONGODB_COLLECTION="testcoll"
   python -m src.main
   ```

2. **Testing**
   ```bash
   make test           # Run tests
   make test-coverage  # With coverage report
   make lint           # Check code style
   make format         # Auto-format code
   ```

3. **Docker Build**
   ```bash
   make docker-build
   make docker-run
   ```

4. **Deploy to K8s**
   ```bash
   # Create secret first
   kubectl create secret generic mongodb-secret --from-literal=uri='...'
   
   make k8s-deploy
   make k8s-logs
   make k8s-status
   ```

## Customization Points

### Business Logic
Implement your MongoDB pulling logic in `src/agent.py`:
- `_process_batch()` - Main batch processing
- `_process_document()` - Individual document processing

### Configuration
Adjust in `k8s/deployment.yaml` ConfigMap:
- `poll_interval` - Time between polls
- `batch_size` - Documents per batch
- `database` / `collection` - MongoDB target

### Resource Limits
Tune in `k8s/deployment.yaml`:
- Memory: 256Mi-512Mi (default)
- CPU: 100m-500m (default)

### Health Probe Timing
Adjust in `k8s/deployment.yaml`:
- `initialDelaySeconds` - Wait before first check
- `periodSeconds` - Time between checks
- `failureThreshold` - Failures before restart
