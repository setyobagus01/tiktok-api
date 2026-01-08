# Use Microsoft Playwright base image with Python
FROM mcr.microsoft.com/playwright/python:v1.48.0-jammy

WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers and system dependencies
# This ensures all browsers (chromium, firefox, webkit) are available
RUN python -m playwright install --with-deps

# Copy application code
COPY . .

# Expose port
EXPOSE 8000

# Set environment variables for anti-detection (can be overridden at runtime)
ENV ENABLE_ANTI_DETECTION=true
ENV MIN_REQUEST_DELAY=1.0
ENV MAX_REQUEST_DELAY=3.0
ENV TIKTOK_BROWSER=webkit

# Run the application
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
