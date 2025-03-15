# meshcoretomqtt
A python based script to send meshore debug and packet capture data to MQTT for analysis  Requires meshcore repeater to be connected to a raspberry pi, server or similar linux device able to run python.

The goal is to have multiple repeaters logging data to the same MQTT server so you can "easily" troubleshoot packets through the mesh.
You will need to build a custom image with packet logging and/or debug for your repeater to view the data.  Alternatively you could obtain custom images from someone that can build them for you.

## Usage
- Setup a raspberry pi (zero / 2 / 3 or 4 recommended)
- Setup / compile / flash a meshcore repater with the appropriate build flags...

  Recommended minimum...
  ```
    -D MESH_PACKET_LOGGING=1
  ```
  You can also add the following if you want debug data too...
  ```
    -D MESH_DEBUG=1
  ```
- Plug the repeater into the pi via USB (rak or heltec tested)
- Configure the repeater with a unique name and setup as per meshcore guides.
- Ensure python is installed on your pi / server device.
- Ensure you have paho mqtt client installed

  `pip3 install paho-mqtt --break-system-packages`
- Download the script...

  `wget https://raw.githubusercontent.com/Andrew-a-g/meshcoretomqtt/refs/heads/main/mctomqtt.py`
- Edit the script with your mqtt server.  You will need to update the configuration section with your mqtt server.
  ```
  MQTT_SERVER = "MQTT_SERVER"
  MQTT_PORT = 1883
  MQTT_USER = "MQTT_USER"
  MQTT_PASS = "MQTT_PASSWORD"
  ```
- Run the script.

  `python ./mctomqtt.py`
  
  Note: run with `-debug` flag to output info to screen.

  If you wish to run it in the background run as follows...
  ```
  python ./mctomqtt.py &
  ```

  In future once stable I will add instructions to run as a service.

## Viewing the data

- Use a MQTT tool to view the packet data.

  I recommend MQTTX
- Data will appear in the following topics...
  ```
  TOPIC_STATUS = "meshcore/status"
  TOPIC_RAW = "meshcore/raw"
  TOPIC_DEBUG = "meshcore/debug"
  TOPIC_PACKETS = "meshcore/packets"
  ```
  Status: The last will and testement (LWT) of each node connected.  Here you can see online / offline status of a node on the MQTT server.

  RAW: The raw packet data going through the repeater.

  DEBUG: The debug info (if enabled on the repeater build)
  
  PACKETS: The flood or direct packets going through the repeater.

## Example MQTT data...
```
Topic: meshcore/status QoS: 0
{"status": "online", "timestamp": "2025-03-15T17:08:34.015328", "repeater": "ag"}
2025-03-15 17:08:34:029

Topic: meshcore/raw QoS: 0
{"origin": "ag", "timestamp": "2025-03-15T17:08:35.563722", "type": "RAW", "data": "110133E2CAB6E73A661BFC2CA7755CD7F697BD83EBA4AADF10921479801354E2A151A411B4D5673C1C01EDF897AE28E57079FAF5238BB325C10F01E583EEB660ECECDD50AC62925A823CD1D979F9D61B9E9D96294E8B604A86E37E069AE45AD318AA186FBDA0099101F40F0367DAF3FF43524E205465726D696E616C2031"}
2025-03-15 17:08:35:560

Topic: meshcore/packets QoS: 0
{"origin": "ag", "timestamp": "2025-03-15T17:08:35.582962", "type": "PACKET", "message": "17:08:34 - 15/3/2025 U: RX, len=126 (type=4, route=F, payload_len=123) SNR=5 RSSI=-96 score=1000 hash=5093FEC3C49AF86A"}
2025-03-15 17:08:35:604

Topic: meshcore/debug QoS: 0
{"origin": "ag", "timestamp": "2025-03-15T17:08:35.600120", "type": "DEBUG", "message": "DEBUG: 17:08:34 - 15/3/2025 U Dispatcher::checkRecv(), score delay below threshold (-323)"}
```