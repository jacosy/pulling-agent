# Use Python 3.11 slim image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/ ./src/

# Create health check directories
RUN mkdir -p /tmp/health /tmp/control

# Run as non-root user for security
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app /tmp/health /tmp/control
USER appuser

# Set Python to run in unbuffered mode (better for logging)
ENV PYTHONUNBUFFERED=1

# Run the application
CMD ["python", "-m", "src.main"]
