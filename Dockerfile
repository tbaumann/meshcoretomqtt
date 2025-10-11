# Basic container
# Example usage: 
#   docker run -d --name mctomqtt \
#     -v ./config/.env.local:/opt/.env.local \
#     --device=/dev/ttyACM0 \
#     meshcoretomqtt:latest

FROM debian:bookworm

ENV DEBIAN_FRONTEND=noninteractive

WORKDIR /opt

# Install dependencies
RUN apt-get update && apt-get install -y \
    python3-pip \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python packages
RUN pip install pyserial paho-mqtt --break-system-packages

# Install Node.js via nvm and meshcore-decoder for auth token support
ENV NVM_DIR=/root/.nvm
ENV NODE_VERSION=lts/*

RUN curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash \
    && . "$NVM_DIR/nvm.sh" \
    && nvm install $NODE_VERSION \
    && nvm use $NODE_VERSION \
    && npm install -g @michaelhart/meshcore-decoder

# Add node to PATH
ENV NODE_PATH=$NVM_DIR/versions/node/$(ls $NVM_DIR/versions/node | head -1)/lib/node_modules
ENV PATH=$NVM_DIR/versions/node/$(ls $NVM_DIR/versions/node | head -1)/bin:$PATH

# Copy application files
COPY ./mctomqtt.py /opt/
COPY ./auth_token.py /opt/
COPY ./.env /opt/

# .env.local should be mounted as a volume with your configuration
# Example: -v ./config/.env.local:/opt/.env.local

CMD ["/usr/bin/python3", "/opt/mctomqtt.py"]
