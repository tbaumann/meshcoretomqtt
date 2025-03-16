# Basic container. Example usage: docker run -d --name mctomqtt-yagi -v ./config.ini:/opt/config.ini --device=/dev/ttyACM0  meshcoretomqtt:150326
# Mapping the script over the top will allow you to make changes like the mqtt server details. Could move them into ENVs later. 

FROM debian:bookworm

ENV DEBIAN_FRONTEND=noninteractive

WORKDIR /opt

RUN apt-get update && apt-get install -y python3-pip

RUN pip install pyserial paho-mqtt --break-system-packages

COPY ./mctomqtt.py /opt
COPY ./config.ini /opt


CMD ["/usr/bin/python3", "/opt/mctomqtt.py"]
