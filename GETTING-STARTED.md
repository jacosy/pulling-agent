# Getting Started Guide

## Quick Start (5 Minutes)

### 1. Extract the Project

```bash
tar -xzf pulling-agent.tar.gz
cd pulling-agent
```

### 2. Review the Structure

```bash
ls -la
cat README.md
```

### 3. Local Development Setup

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements-dev.txt

# Copy environment template
cp .env.example .env

# Edit .env with your MongoDB details
nano .env  # or use your favorite editor
```

### 4. Run Locally

```bash
# Set environment variables
export $(cat .env | xargs)

# Run the agent
python -m src.main

# In another terminal, check health files
ls -la /tmp/health/
cat /tmp/health/liveness
```

### 5. Test the Agent

```bash
# Run unit tests
make test

# Or with coverage
make test-coverage
```

## Kubernetes Deployment (10 Minutes)

### 1. Build Docker Image

```bash
# Build
docker build -t pulling-agent:v1.0.0 .

# Test locally
docker run --rm \
  -e MONGODB_URI="mongodb://host.docker.internal:27017" \
  -e MONGODB_DATABASE="testdb" \
  -e MONGODB_COLLECTION="testcoll" \
  pulling-agent:v1.0.0
```

### 2. Push to Registry (if using remote K8s)

```bash
# Tag for your registry
docker tag pulling-agent:v1.0.0 your-registry/pulling-agent:v1.0.0

# Push
docker push your-registry/pulling-agent:v1.0.0

# Update k8s/deployment.yaml
sed -i 's|pulling-agent:latest|your-registry/pulling-agent:v1.0.0|' k8s/deployment.yaml
```

### 3. Create MongoDB Secret

```bash
# Create secret with your MongoDB connection string
kubectl create secret generic mongodb-secret \
  --from-literal=uri='mongodb://username:password@mongodb-host:27017/dbname'

# Verify
kubectl get secret mongodb-secret
```

### 4. Update Configuration

Edit `k8s/deployment.yaml` and update the ConfigMap:

```yaml
data:
  database: "your_database_name"        # Change this
  collection: "your_collection_name"    # Change this
  poll_interval: "5"
  batch_size: "100"
```

### 5. Deploy to Kubernetes

```bash
# Deploy all resources
kubectl apply -f k8s/

# Or use Makefile
make k8s-deploy
```

### 6. Verify Deployment

```bash
# Check pod status
kubectl get pods -l app=pulling-agent

# View logs
kubectl logs -f deployment/pulling-agent

# Check health
POD=$(kubectl get pod -l app=pulling-agent -o jsonpath='{.items[0].metadata.name}')
kubectl exec $POD -- cat /tmp/health/liveness
```

## Customizing Business Logic

### 1. Edit the Processing Logic

Open `src/agent.py` and find the `_process_batch()` method:

```python
async def _process_batch(self):
    """
    Pull and process one batch of documents from MongoDB.
    
    TODO: Implement your business logic here.
    """
    # Your custom logic here
    cursor = self.mongo.collection.find(
        {"status": "pending"},  # Your query
        limit=self.config.batch_size
    )
    
    documents = await cursor.to_list(length=self.config.batch_size)
    
    for doc in documents:
        # Process each document
        await self._process_document(doc)
        
        # Update status
        await self.mongo.collection.update_one(
            {"_id": doc["_id"]},
            {"$set": {"status": "processed"}}
        )
```

### 2. Test Your Changes

```bash
# Run locally first
python -m src.main

# Run tests
make test

# Lint code
make lint
make format
```

### 3. Rebuild and Deploy

```bash
# Rebuild Docker image
docker build -t pulling-agent:v1.1.0 .

# Push to registry
docker push your-registry/pulling-agent:v1.1.0

# Update deployment
kubectl set image deployment/pulling-agent agent=your-registry/pulling-agent:v1.1.0

# Watch rollout
kubectl rollout status deployment/pulling-agent
```

## Common Operations

### Pause the Agent

```bash
# Via ConfigMap
make k8s-pause

# Via signal
POD=$(kubectl get pod -l app=pulling-agent -o jsonpath='{.items[0].metadata.name}')
kubectl exec $POD -- kill -USR1 1

# Verify
kubectl logs --tail=10 deployment/pulling-agent
# Look for: "Pausing agent"
```

### Resume the Agent

```bash
# Via ConfigMap
make k8s-resume

# Via signal
kubectl exec $POD -- kill -USR2 1
```

### Monitor the Agent

```bash
# Follow logs
kubectl logs -f deployment/pulling-agent

# Check health status
kubectl exec $POD -- cat /tmp/health/liveness

# View resource usage
kubectl top pod -l app=pulling-agent

# Get processing stats
kubectl exec $POD -- cat /tmp/health/liveness | grep -E "batches|documents|errors"
```

### Troubleshoot Issues

```bash
# Check pod status
kubectl describe pod -l app=pulling-agent

# View recent errors
kubectl logs --tail=100 deployment/pulling-agent | grep ERROR

# Test MongoDB connection
kubectl exec $POD -- python3 -c "
from motor.motor_asyncio import AsyncIOMotorClient
import asyncio
asyncio.run(AsyncIOMotorClient('$MONGODB_URI').admin.command('ping'))
"

# Check probe configuration
kubectl get deployment pulling-agent -o yaml | grep -A 10 livenessProbe
```

## Next Steps

1. **Read the documentation:**
   - `README.md` - Overview and features
   - `docs/OPERATIONS.md` - Comprehensive operations guide
   - `docs/QUICK-REFERENCE.md` - Command reference
   - `docs/PROJECT-STRUCTURE.md` - Code organization

2. **Customize for your use case:**
   - Implement your MongoDB query logic
   - Add error handling specific to your domain
   - Tune performance parameters

3. **Set up monitoring:**
   - Configure Prometheus metrics (optional)
   - Set up log aggregation
   - Create dashboards

4. **Production readiness:**
   - Review resource limits
   - Test failure scenarios
   - Document your customizations
   - Set up backup procedures

## Getting Help

- Check `docs/OPERATIONS.md` for troubleshooting
- Review `docs/QUICK-REFERENCE.md` for common commands
- Look at test examples in `tests/test_agent.py`
- Read inline code comments in `src/`

## Project Layout

```
pulling-agent/
├── src/                    # Application code
├── k8s/                    # Kubernetes manifests
├── tests/                  # Unit tests
├── docs/                   # Documentation
├── scripts/                # Utility scripts
├── Dockerfile              # Container definition
├── Makefile               # Task automation
└── README.md              # Main documentation
```

## Key Files to Know

- `src/agent.py` - Core agent logic (customize here)
- `src/config.py` - Configuration options
- `k8s/deployment.yaml` - Kubernetes deployment
- `Makefile` - Useful commands
- `docs/OPERATIONS.md` - Troubleshooting guide

Happy deploying! 🚀
