# Use official Python runtime with Debian base (Python 3.11 for modern spaCy/thinc compatibility)
FROM python:3.11-slim

# Install system dependencies & Node.js 20.x
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    gnupg \
    build-essential \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" | tee /etc/apt/sources.list.d/nodesource.list \
    && apt-get update \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip setuptools wheel
RUN pip install --no-cache-dir -r requirements.txt
RUN python -m spacy download en_core_web_md

# Copy repository
COPY . .

# Install Node dependencies & Build Frontend
RUN npm run install:server
RUN npm run install:client
RUN npm run build:client

# Expose server port
ENV PORT=5000
EXPOSE 5000

# Start Express server (serves React frontend and handles DOCX redactions)
CMD ["npm", "start"]
