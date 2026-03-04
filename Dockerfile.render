FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy lightweight requirements (no PyTorch/CUDA for API server)
COPY requirements.render.txt .
RUN pip install --no-cache-dir -r requirements.render.txt

# Copy application source
COPY v1/ /app/v1/
COPY . /app/

# Create src symlink manually (symlinks don't copy well in Docker)
RUN ln -sf /app/v1/src /app/src || true

# Set environment variables
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV RENDER=true

# Expose port
EXPOSE 8000

# Run application
CMD ["uvicorn", "src.app:app", "--host", "0.0.0.0", "--port", "8000"]
