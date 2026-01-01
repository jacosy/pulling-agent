#!/bin/bash
# Control script for MongoDB Pulling Agent
# Usage: ./control-agent.sh [pause|resume|status|restart]

set -e

NAMESPACE="${NAMESPACE:-default}"
APP_LABEL="app=pulling-agent"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Get pod name
get_pod() {
    kubectl get pod -n "$NAMESPACE" -l "$APP_LABEL" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null
}

# Get current state
get_state() {
    local pod=$(get_pod)
    if [ -z "$pod" ]; then
        echo "ERROR: No pod found"
        return 1
    fi
    
    # Check if readiness file exists
    if kubectl exec -n "$NAMESPACE" "$pod" -- test -f /tmp/health/readiness 2>/dev/null; then
        echo "RUNNING"
    else
        # Check liveness to see if it's paused or unhealthy
        if kubectl exec -n "$NAMESPACE" "$pod" -- test -f /tmp/health/liveness 2>/dev/null; then
            local content=$(kubectl exec -n "$NAMESPACE" "$pod" -- cat /tmp/health/liveness 2>/dev/null | head -1)
            if [ "$content" = "paused" ]; then
                echo "PAUSED"
            else
                echo "UNKNOWN"
            fi
        else
            echo "UNHEALTHY"
        fi
    fi
}

# Pause the agent
pause_agent() {
    echo -e "${YELLOW}Pausing agent...${NC}"
    
    # Method 1: Update ConfigMap
    kubectl create configmap agent-control \
        -n "$NAMESPACE" \
        --from-literal=state=pause \
        -o yaml --dry-run=client | kubectl apply -n "$NAMESPACE" -f - > /dev/null
    
    echo "ConfigMap updated to 'pause'"
    
    # Method 2: Send signal (backup method)
    local pod=$(get_pod)
    if [ -n "$pod" ]; then
        kubectl exec -n "$NAMESPACE" "$pod" -- kill -USR1 1 2>/dev/null || true
        echo "SIGUSR1 signal sent to pod"
    fi
    
    # Wait and verify
    echo -n "Waiting for agent to pause"
    for i in {1..10}; do
        sleep 1
        echo -n "."
        state=$(get_state)
        if [ "$state" = "PAUSED" ]; then
            echo ""
            echo -e "${GREEN}✓ Agent successfully paused${NC}"
            return 0
        fi
    done
    
    echo ""
    echo -e "${RED}Warning: Agent may not have paused yet. Check status.${NC}"
}

# Resume the agent
resume_agent() {
    echo -e "${YELLOW}Resuming agent...${NC}"
    
    # Method 1: Update ConfigMap
    kubectl create configmap agent-control \
        -n "$NAMESPACE" \
        --from-literal=state=resume \
        -o yaml --dry-run=client | kubectl apply -n "$NAMESPACE" -f - > /dev/null
    
    echo "ConfigMap updated to 'resume'"
    
    # Method 2: Send signal (backup method)
    local pod=$(get_pod)
    if [ -n "$pod" ]; then
        kubectl exec -n "$NAMESPACE" "$pod" -- kill -USR2 1 2>/dev/null || true
        echo "SIGUSR2 signal sent to pod"
    fi
    
    # Wait and verify
    echo -n "Waiting for agent to resume"
    for i in {1..10}; do
        sleep 1
        echo -n "."
        state=$(get_state)
        if [ "$state" = "RUNNING" ]; then
            echo ""
            echo -e "${GREEN}✓ Agent successfully resumed${NC}"
            return 0
        fi
    done
    
    echo ""
    echo -e "${RED}Warning: Agent may not have resumed yet. Check status.${NC}"
}

# Show agent status
show_status() {
    local pod=$(get_pod)
    
    if [ -z "$pod" ]; then
        echo -e "${RED}ERROR: No pod found${NC}"
        echo "Run: kubectl get pods -n $NAMESPACE -l $APP_LABEL"
        return 1
    fi
    
    echo "=== Pulling Agent Status ==="
    echo "Namespace: $NAMESPACE"
    echo "Pod: $pod"
    echo ""
    
    # Get state
    state=$(get_state)
    
    if [ "$state" = "RUNNING" ]; then
        echo -e "State: ${GREEN}$state${NC}"
    elif [ "$state" = "PAUSED" ]; then
        echo -e "State: ${YELLOW}$state${NC}"
    else
        echo -e "State: ${RED}$state${NC}"
    fi
    
    echo ""
    echo "--- Health Files ---"
    
    # Liveness file
    if kubectl exec -n "$NAMESPACE" "$pod" -- test -f /tmp/health/liveness 2>/dev/null; then
        echo "Liveness: ✓ (exists)"
        kubectl exec -n "$NAMESPACE" "$pod" -- cat /tmp/health/liveness 2>/dev/null | sed 's/^/  /'
    else
        echo -e "Liveness: ${RED}✗ (missing)${NC}"
    fi
    
    echo ""
    
    # Readiness file
    if kubectl exec -n "$NAMESPACE" "$pod" -- test -f /tmp/health/readiness 2>/dev/null; then
        echo "Readiness: ✓ (exists)"
        kubectl exec -n "$NAMESPACE" "$pod" -- cat /tmp/health/readiness 2>/dev/null | sed 's/^/  /'
    else
        echo "Readiness: ✗ (missing - agent not processing)"
    fi
    
    echo ""
    echo "--- Control ConfigMap ---"
    local cm_state=$(kubectl get configmap agent-control -n "$NAMESPACE" -o jsonpath='{.data.state}' 2>/dev/null || echo "not found")
    echo "ConfigMap state: $cm_state"
    
    echo ""
    echo "--- Recent Logs (last 10 lines) ---"
    kubectl logs -n "$NAMESPACE" "$pod" --tail=10 | sed 's/^/  /'
}

# Restart the agent
restart_agent() {
    echo -e "${YELLOW}Restarting agent...${NC}"
    
    local pod=$(get_pod)
    if [ -z "$pod" ]; then
        echo -e "${RED}ERROR: No pod found${NC}"
        return 1
    fi
    
    # Delete pod (Deployment will recreate it)
    kubectl delete pod -n "$NAMESPACE" "$pod"
    
    echo "Pod deleted. Deployment will create a new one."
    echo -n "Waiting for new pod"
    
    for i in {1..30}; do
        sleep 1
        echo -n "."
        new_pod=$(get_pod)
        if [ -n "$new_pod" ] && [ "$new_pod" != "$pod" ]; then
            # Check if pod is ready
            if kubectl get pod -n "$NAMESPACE" "$new_pod" -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' | grep -q "True"; then
                echo ""
                echo -e "${GREEN}✓ Agent restarted successfully${NC}"
                echo "New pod: $new_pod"
                return 0
            fi
        fi
    done
    
    echo ""
    echo -e "${YELLOW}Warning: Pod recreated but may not be ready yet${NC}"
    echo "Run: kubectl get pods -n $NAMESPACE -l $APP_LABEL"
}

# Show usage
usage() {
    cat << EOF
Usage: $0 [COMMAND]

Commands:
    pause       Pause the agent (stops processing, completes current batch)
    resume      Resume the agent (starts processing again)
    status      Show current agent status
    restart     Restart the agent (delete pod, let Deployment recreate)
    help        Show this help message

Environment Variables:
    NAMESPACE   Kubernetes namespace (default: default)

Examples:
    # Pause the agent
    $0 pause
    
    # Resume the agent
    $0 resume
    
    # Check status
    $0 status
    
    # Use different namespace
    NAMESPACE=production $0 pause

Notes:
    - Pause completes the current batch before stopping
    - Resume resumes from where it left off
    - Uses both ConfigMap and signals for redundancy
    - Status shows health files and recent logs

EOF
}

# Main
main() {
    local command="${1:-help}"
    
    case "$command" in
        pause)
            pause_agent
            ;;
        resume)
            resume_agent
            ;;
        status)
            show_status
            ;;
        restart)
            restart_agent
            ;;
        help|--help|-h)
            usage
            ;;
        *)
            echo -e "${RED}ERROR: Unknown command '$command'${NC}"
            echo ""
            usage
            exit 1
            ;;
    esac
}

main "$@"
