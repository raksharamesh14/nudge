# Multi-stage build for optimized voice bot deployment
FROM python:3.11-slim as builder

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv for faster dependency management
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.cargo/bin:$PATH"

# Set working directory
WORKDIR /app

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies
RUN uv sync --frozen

# Production stage
FROM python:3.11-slim

# Install runtime dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd --create-home --shell /bin/bash app
USER app
WORKDIR /home/app

# Copy virtual environment from builder
COPY --from=builder --chown=app:app /app/.venv /home/app/.venv

# Copy application code
COPY --chown=app:app src/ /home/app/src/
COPY --chown=app:app deployment/scripts/ /home/app/deployment/scripts/
COPY --chown=app:app .env /home/app/.env

# Set environment variables
ENV PATH="/home/app/.venv/bin:$PATH"
ENV PYTHONPATH="/home/app"

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run the application
CMD ["bash", "-c", "python deployment/scripts/download_s3.py && python src/bot.py"]
