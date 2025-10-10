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
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

# Install Python packages
RUN pip install pyserial paho-mqtt --break-system-packages

# Install meshcore-decoder for auth token support
RUN npm install -g @michaelhart/meshcore-decoder

# Copy application files
COPY ./mctomqtt.py /opt/
COPY ./auth_token.py /opt/
COPY ./.env /opt/

# .env.local should be mounted as a volume with your configuration
# Example: -v ./config/.env.local:/opt/.env.local

CMD ["/usr/bin/python3", "/opt/mctomqtt.py"]
