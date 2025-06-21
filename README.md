# meshcoretomqtt
A python based script to send meshore debug and packet capture data to MQTT for analysis.  Requires meshcore repeater to be connected to a raspberry pi, server or similar linux device able to run python.

The goal is to have multiple repeaters logging data to the same MQTT server so you can "easily" troubleshoot packets through the mesh.
You will need to build a custom image with packet logging and/or debug for your repeater to view the data.  Alternatively you could obtain custom images from someone that can build them for you.

One way of tracking a message through the mesh is filtering the MQTT data on the hash field as each message has a unique hash.  You can see which repeaters the message hits!

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
- Ensure you have paho mqtt and pyserial installed

  ```
  sudo apt update
  sudo apt install -y python3-venv

  python3 -m venv mctomqtt
  source mctomqtt/bin/activate

  pip install pyserial paho-mqtt`
- Download the script and config file...

  `git clone https://github.com/Cisien/meshcoretomqtt`

- Create/download or edit the config.ini (in the same folder as the script) file with your mqtt server.  You will need to update the configuration section with your mqtt server.
  ```
  server = mqtt_server
  port = 1883
  username = mqtt_user
  password = mqtt_password
  ```
- Run the script.

  `python ./mctomqtt.py`
  
  Note: run with `-debug` flag to output info to screen.

  If you wish to run it in the background run as follows...
  ```
  nohup python3 mctomqtt.py > output.log 2>&1 &
  ```

  The included mctomqtt.service systemd service file can be installed in /etc/systemd/system/. This file needs to be updated to point to the path where this repo has been cloned to and the path of python in the venv that was created in an earlier step.
  ```
  sudo systemctl daemon-reload
  sudo systemctl enable mctomqtt.service
  sudo systemctl start mctomqtt.service
  ```

## Privacy
MeshCore does not currently have any privacy controls baked into the protocol ([#435](https://github.com/ripplebiz/MeshCore/issues/435)). To compensate for this, the decoding logic will not publish the decoded payload of an advert for any node that does not have a `^` character at the end of its name. Downstream consumers of this data should ignore any packets that include a "sender" or "receiver" that it has not seen a recent advert for.

## Viewing the data

- Use a MQTT tool to view the packet data.

  I recommend MQTTX
- Data will appear in the following topics...
  ```
  TOPIC_STATUS = "meshcore/status"
  TOPIC_RAW = "meshcore/raw"
  TOPIC_DEBUG = "meshcore/debug"
  TOPIC_PACKETS = "meshcore/packets"
  TOPIC_DECODED = "meshcore/decoded"
  ```
  Status: The last will and testement (LWT) of each node connected.  Here you can see online / offline status of a node on the MQTT server.

  RAW: The raw packet data going through the repeater.

  DEBUG: The debug info (if enabled on the repeater build)

  PACKETS: The flood or direct packets going through the repeater.

  DECODED: Packets are decoded (and decrypted when the key is known) and pubished to this topic as unencrypted JSON

## Example MQTT data...

Note: origin is the repeater node reporting the data to mqtt.  Not the origin of the LoRa packet.

Flood packet...
```
Topic: meshcore/packets QoS: 0
{"origin": "ag loft rpt", "timestamp": "2025-03-16T00:07:11.191561", "type": "PACKET", "direction": "rx", "time": "00:07:09", "date": "16/3/2025", "len": "87", "packet_type": "5", "route": "F", "payload_len": "83", "SNR": "4", "RSSI": "-93", "score": "1000", "hash": "AC9D2DDDD8395712"}
```
Direct packet...
```
Topic: meshcore/packets QoS: 0
{"origin": "ag loft rpt", "timestamp": "2025-03-15T23:09:00.710459", "type": "PACKET", "direction": "rx", "time": "23:08:59", "date": "15/3/2025", "len": "22", "packet_type": "2", "route": "D", "payload_len": "20", "SNR": "5", "RSSI": "-93", "score": "1000", "hash": "890BFA3069FD1250", "path": "C2 -> E2"}
```

## ToDo
- Complete more thorough testing
- Fix bugs with keepalive status topic