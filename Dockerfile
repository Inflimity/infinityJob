# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Set work directory
WORKDIR /app

# Install system dependencies required for Playwright and general build
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt \
    fastapi \
    "uvicorn[standard]"

# Install Playwright chromium and its system dependencies
RUN playwright install chromium --with-deps

# Copy project
COPY . /app/

# Expose port for FastAPI Dashboard
EXPOSE 8000

# Command to run the application
CMD ["python", "main.py"]
