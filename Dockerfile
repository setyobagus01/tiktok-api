# Use base Python image (we'll install Playwright dynamically)
FROM python:3.11-slim-bookworm

WORKDIR /app

# Install system dependencies for Playwright browsers and xvfb
RUN apt-get update && apt-get install -y \
    # Xvfb for virtual display (non-headless mode)
    xvfb \
    x11-utils \
    # Dependencies for Playwright browsers
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    libatspi2.0-0 \
    libwayland-client0 \
    # Additional dependencies for webkit
    libwoff1 \
    libharfbuzz-icu0 \
    libgstreamer-plugins-base1.0-0 \
    libgstreamer1.0-0 \
    libopus0 \
    libwebpdemux2 \
    libenchant-2-2 \
    libsecret-1-0 \
    libhyphen0 \
    libmanette-0.2-0 \
    libflite1 \
    libgles2 \
    gstreamer1.0-libav \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers AND their dependencies (ensures version match)
RUN python -m playwright install webkit chromium --with-deps

# Copy application code
COPY . .

# Expose port
EXPOSE 8000

# Create startup script that launches xvfb before the app
RUN echo '#!/bin/bash\nXvfb :99 -screen 0 1920x1080x24 &\nexport DISPLAY=:99\nsleep 2\npython -m uvicorn main:app --host 0.0.0.0 --port 8000' > /app/start.sh && chmod +x /app/start.sh

# Run the application with virtual display
CMD ["/app/start.sh"]

