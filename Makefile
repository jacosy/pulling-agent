.PHONY: help install test lint format docker-build docker-run k8s-deploy k8s-delete k8s-logs clean

help:
	@echo "Available targets:"
	@echo "  install           - Install dependencies"
	@echo "  test              - Run tests"
	@echo "  lint              - Run linter"
	@echo "  format            - Format code"
	@echo "  docker-build      - Build Docker image"
	@echo "  docker-run        - Run Docker container locally"
	@echo "  k8s-deploy        - Deploy to Kubernetes"
	@echo "  k8s-delete        - Delete from Kubernetes"
	@echo "  k8s-logs          - View logs from Kubernetes"
	@echo "  k8s-pause         - Pause the agent"
	@echo "  k8s-resume        - Resume the agent"
	@echo "  k8s-control-status - Show agent control status"
	@echo "  clean             - Clean up generated files"

install:
	pip install -r requirements.txt
	pip install pytest pytest-asyncio pytest-cov black flake8

test:
	python -m pytest tests/ -v

test-coverage:
	python -m pytest tests/ --cov=src --cov-report=html --cov-report=term

lint:
	flake8 src/ tests/ --max-line-length=100 --exclude=__pycache__

format:
	black src/ tests/ --line-length=100

docker-build:
	docker build -t pulling-agent:latest .

docker-run:
	docker run --rm \
		-e MONGODB_URI="${MONGODB_URI}" \
		-e MONGODB_DATABASE="${MONGODB_DATABASE}" \
		-e MONGODB_COLLECTION="${MONGODB_COLLECTION}" \
		-e POLL_INTERVAL=5 \
		-e LOG_LEVEL=DEBUG \
		pulling-agent:latest

k8s-deploy:
	kubectl apply -f k8s/

k8s-delete:
	kubectl delete -f k8s/

k8s-logs:
	kubectl logs -f deployment/pulling-agent

k8s-status:
	@echo "=== Pods ==="
	kubectl get pods -l app=pulling-agent
	@echo "\n=== Deployment ==="
	kubectl get deployment pulling-agent
	@echo "\n=== ConfigMaps ==="
	kubectl get configmap agent-config agent-control
	@echo "\n=== Secrets ==="
	kubectl get secret mongodb-secret

k8s-health:
	@POD=$$(kubectl get pod -l app=pulling-agent -o jsonpath='{.items[0].metadata.name}'); \
	echo "=== Liveness Check ==="; \
	kubectl exec $$POD -- cat /tmp/health/liveness || echo "Not healthy"; \
	echo "\n=== Readiness Check ==="; \
	kubectl exec $$POD -- test -f /tmp/health/readiness && echo "Ready" || echo "Not ready"

k8s-pause:
	kubectl create configmap agent-control --from-literal=state=pause -o yaml --dry-run=client | kubectl apply -f -
	@echo "Agent pause requested. Check status with: make k8s-control-status"

k8s-resume:
	kubectl create configmap agent-control --from-literal=state=resume -o yaml --dry-run=client | kubectl apply -f -
	@echo "Agent resume requested. Check status with: make k8s-control-status"

k8s-control-status:
	@./scripts/control-agent.sh status || echo "Run: chmod +x scripts/control-agent.sh && make k8s-control-status"

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	rm -rf .pytest_cache htmlcov .coverage
	rm -rf build dist *.egg-info
