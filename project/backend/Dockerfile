# DocSentinel Backend — ARM-compatible Docker image
FROM python:3.11-slim

# ARM64 support label
LABEL org.opencontainers.image.title="DocSentinel Backend"
LABEL org.opencontainers.image.description="Self-healing agentic document intelligence"

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

# Create directories
RUN mkdir -p uploads extracted_images mineru_output

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
