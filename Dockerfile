# Use Microsoft Playwright base image with all browsers pre-installed
FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

WORKDIR /app

# Install xvfb for virtual display (allows non-headless mode in container)
RUN apt-get update && apt-get install -y \
    xvfb \
    x11-utils \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers (webkit is less detectable than chromium)
RUN python -m playwright install webkit chromium

# Copy application code
COPY . .

# Expose port
EXPOSE 8000

# Create startup script that launches xvfb before the app
RUN echo '#!/bin/bash\nXvfb :99 -screen 0 1920x1080x24 &\nexport DISPLAY=:99\nsleep 2\npython -m uvicorn main:app --host 0.0.0.0 --port 8000' > /app/start.sh && chmod +x /app/start.sh

# Run the application with virtual display
CMD ["/app/start.sh"]
