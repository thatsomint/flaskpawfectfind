FROM python:3.11-slim-bullseye

# Add cache busting
#ARG CACHE_BUST=1

WORKDIR /app

# Create non-root user (FIXED: do this AFTER copying files)
#RUN useradd -m -u 1000 flaskuser && chown -R flaskuser:flaskuser /app
#USER flaskuser

# Install system dependencies including ODBC driver AND build tools for bcrypt
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    unixodbc \
    unixodbc-dev \
    curl \
    gnupg \
    build-essential \
    python3-dev \
    pkg-config \
    apt-transport-https \
    && curl -sSL https://packages.microsoft.com/keys/microsoft.asc > /etc/apt/trusted.gpg.d/microsoft.asc \
    && curl -sSL https://packages.microsoft.com/config/debian/11/prod.list > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y msodbcsql18 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (for better caching)
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .


# Use port 8000 for Azure 
EXPOSE 8000

CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "1", "--timeout", "120", "--access-logfile", "-", "--error-logfile", "-", "--preload", "flask_app:app"]