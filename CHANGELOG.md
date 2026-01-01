# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2025-01-01

### Added
- Initial release of MongoDB Pulling Agent
- Async MongoDB pulling with Motor driver
- File-based health checks for Kubernetes (liveness/readiness)
- Graceful shutdown on SIGTERM/SIGINT
- **Pause/resume control via SIGUSR1/SIGUSR2 signals**
- **Pause/resume control via ConfigMap file**
- **Control script (`control-agent.sh`) for easy pause/resume/status operations**
- **Kubernetes Jobs for one-time pause/resume operations**
- **CronJobs for scheduled pause/resume operations**
- Heartbeat monitoring (updates every 5 seconds)
- Configurable poll interval and batch size
- Structured logging with configurable levels
- Statistics tracking (batches, documents, errors)
- Docker containerization
- Kubernetes deployment manifests
- Comprehensive test suite
- Documentation (README, Operations Guide, Quick Reference, Pause/Unpause Guide)
- Example configurations and scripts

### Control Features
- **5 methods to pause/resume**: Control script, ConfigMap, Signals, Jobs, CronJobs
- Automatic state verification in control script
- Dual-method approach (ConfigMap + signal) for redundancy
- Colored output in control script for better UX
- Status command showing health files and recent logs
- RBAC configuration for control operations
- Example CronJob schedules for common use cases

### Features
- Zero-dependency HTTP server (pure file-based probes)
- Interruptible sleep for responsive shutdown
- State machine for agent lifecycle
- Background heartbeat task
- Control file monitoring task
- Async/await throughout for efficient I/O
- Resource limits and requests in K8s manifests
- Non-root container user for security
- Health check script for advanced probe scenarios

### Documentation
- Detailed README with quick start guide
- Operations guide with troubleshooting
- Quick reference card
- Inline code documentation
- Example environment files
- Kubernetes manifest examples
