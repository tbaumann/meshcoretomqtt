#!/usr/bin/env python3
import sys
import json
import serial
import argparse
import re
import time
import calendar
import logging
import configparser
from datetime import datetime
from time import sleep

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("Error: paho-mqtt not installed. Install with:")
    print("pip install paho-mqtt")
    sys.exit(1)

# Regex patterns for message parsing
RAW_PATTERN = re.compile(r"(\d{2}:\d{2}:\d{2}) - (\d{1,2}/\d{1,2}/\d{4}) U RAW: (.*)")
PACKET_PATTERN = re.compile(
    r"(\d{2}:\d{2}:\d{2}) - (\d{1,2}/\d{1,2}/\d{4}) U: (RX|TX), len=(\d+) \(type=(\d+), route=([A-Z]), payload_len=(\d+)\)"
    r"(?: SNR=(-?\d+) RSSI=(-?\d+) score=(\d+)( time=(\d+))? hash=([0-9A-F]+)(?: \[(.*)\])?)?"
)

# Initialize logging (console only)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

class MeshCoreBridge:
    last_raw: bytes = None

    def __init__(self, config_file="config.ini", debug=False):
        self.debug = debug
        self.repeater_name = None
        self.repeater_pub_key = None
        self.radio_info = None
        self.ser = None
        self.mqtt_client = None
        self.mqtt_connected = False
        self.should_exit = False

        # Load configuration
        self.config = configparser.ConfigParser()
        try:
            self.config.read(config_file)
            logger.info("Configuration loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load configuration: {str(e)}")
            sys.exit(1)

    def sanitize_client_id(self, name):
        """Convert repeater name to valid MQTT client ID"""
        client_id = self.config.get("mqtt", "client_id_prefix", fallback="meshcore_") + name.replace(" ", "_")
        client_id = re.sub(r"[^a-zA-Z0-9_-]", "", client_id)
        return client_id[:23]

    def connect_serial(self):
        ports = self.config.get("serial", "ports").split(",")
        baud_rate = self.config.getint("serial", "baud_rate")
        timeout = self.config.getint("serial", "timeout", fallback=2)

        for port in ports:
            try:
                self.ser = serial.Serial(
                    port=port,
                    baudrate=baud_rate,
                    parity=serial.PARITY_NONE,
                    stopbits=serial.STOPBITS_ONE,
                    bytesize=serial.EIGHTBITS,
                    timeout=timeout,
                    rtscts=False
                )
                self.ser.write("\r\n\r\n")
                self.ser.flushInput()
                self.ser.flushOutput()
                logger.info(f"Connected to {port}")
                return True
            except (serial.SerialException, OSError) as e:
                logger.warning(f"Failed to connect to {port}: {str(e)}")
                continue
        logger.error("Failed to connect to any serial port")
        return False

    def set_repeater_time(self):
        self.ser.flushInput()
        self.ser.flushOutput()
        epoc_time = int(calendar.timegm(time.gmtime()))
        timecmd=f'time {epoc_time}\r\n'
        self.ser.write(timecmd.encode())
        logger.debug(f"Sent '{timecmd}' command")

        sleep(0.5)
        response = self.ser.read_all().decode(errors='replace')
        logger.debug(f"Raw response: {response}")

    def get_repeater_name(self):
        if not self.ser:
            return False

        self.ser.flushInput()
        self.ser.flushOutput()
        self.ser.write(b"get name\r\n")
        logger.debug("Sent 'get name' command")

        sleep(0.5)
        response = self.ser.read_all().decode(errors='replace')
        logger.debug(f"Raw response: {response}")

        if "-> >" in response:
            self.repeater_name = response.split("-> >")[1].strip()
            if '\n' in self.repeater_name:
                self.repeater_name = self.repeater_name.split('\n')[0]
            logger.info(f"Repeater name: {self.repeater_name}")
            return True
        
        logger.error("Failed to get repeater name from response")
        return False

    def get_repeater_pubkey(self):
        if not self.ser:
            return False
        self.ser.flushInput()
        self.ser.flushOutput()
        self.ser.write(b"get public.key\r\n")
        logger.debug("Sent 'get public.key' command")

        sleep(1.0)
        response = self.ser.read_all().decode(errors='replace')
        logger.debug(f"Raw response: {response}")

        if "-> >" in response:
            self.repeater_pub_key = response.split("-> >")[1].strip()
            if '\n' in self.repeater_pub_key:
                self.repeater_pub_key = self.repeater_pub_key.split('\n')[0]
            logger.info(f"Repeater pub key: {self.repeater_pub_key}")
            return True
        
        logger.error("Failed to get repeater pub key from response")
        return False

    def get_radio_info(self):
        """Query the repeater for radio information"""
        if not self.ser:
            return None

        self.ser.flushInput()
        self.ser.flushOutput()
        self.ser.write(b"get radio\r\n")
        logger.debug("Sent 'get radio' command")

        sleep(0.5)  # Adjust delay if necessary
        response = self.ser.read_all().decode(errors='replace')
        logger.debug(f"Raw radio response: {response}")

        if "-> >" in response:
            radio_info = response.split("-> >")[1].strip()
            if '\n' in radio_info:
                radio_info = radio_info.split('\n')[0]
            logger.debug(f"Parsed radio info: {radio_info}")
            return radio_info
        
        logger.error("Failed to get radio info from response")
        return None

    def on_mqtt_connect(self, client, userdata, flags, rc, properties=None):
        if rc == 0:
            self.mqtt_connected = True
            logger.info("Connected to MQTT broker")
            # Publish online status once on connection
            self.publish_status("online")
        else:
            self.mqtt_connected = False
            logger.error(f"MQTT connection failed with code {rc}")

    def on_mqtt_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        self.mqtt_connected = False
        logger.warning(f"Disconnected from MQTT broker (code: {reason_code}; flags: {disconnect_flags}; userdata: {userdata}; properties: {properties})")
        logger.warning("Exiting...")
        self.should_exit = True

    def publish_status(self, status):
        """Publish status with additional information"""
        status_msg = {
            "status": status,
            "timestamp": datetime.now().isoformat(),
            "repeater": self.repeater_name,
            "repeater_id": self.repeater_pub_key,
            "radio": self.radio_info if self.radio_info else "unknown"  # Use stored radio info
        }
        if self.safe_publish(self.config.get("topics", "status"), json.dumps(status_msg), retain=True):
            logger.debug(f"Published status: {status}")

    def safe_publish(self, topic, payload, retain=False):
        if not self.mqtt_connected:
            logger.warning(f"Not connected - skipping publish to {topic}")
            return False

        try:
            qos = self.config.getint("mqtt", "qos", fallback=0)
            if qos == 1:
                qos = 0 # force qos=1 to 0 because qos 1 can cause retry storms.
            result = self.mqtt_client.publish(topic, payload, qos=qos, retain=retain)
            if result.rc != mqtt.MQTT_ERR_SUCCESS:
                logger.error(f"Publish failed to {topic}: {mqtt.error_string(result.rc)}")
                return False
            logger.debug(f"Published to {topic}: {payload}")
            return True
        except Exception as e:
            logger.error(f"Publish error to {topic}: {str(e)}")
            return False

    def connect_mqtt(self):
        if not self.repeater_name:
            logger.error("Cannot connect to MQTT without repeater name")
            return False

        client_id = self.sanitize_client_id(self.repeater_pub_key)
        logger.info(f"Using client ID: {client_id}")
        self.mqtt_client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
            clean_session=False
        )
        
        self.mqtt_client.username_pw_set(
            self.config.get("mqtt", "username"),
            self.config.get("mqtt", "password")
        )
        
        # Set Last Will and Testament
        lwt_topic = self.config.get("topics", "status")
        lwt_payload = json.dumps({
            "status": "offline",
            "timestamp": datetime.now().isoformat(),
            "repeater": self.repeater_name,
            "repeater_id": self.repeater_pub_key
        })
        lwt_qos = self.config.getint("mqtt", "qos", fallback=1)  # Use QoS 1 for reliability
        lwt_retain = self.config.getboolean("mqtt", "retain", fallback=True)
        
        self.mqtt_client.will_set(
            lwt_topic,
            lwt_payload,
            qos=lwt_qos,
            retain=lwt_retain
        )
        
        logger.debug(f"Set LWT for topic: {lwt_topic}, payload: {lwt_payload}, QoS: {lwt_qos}, retain: {lwt_retain}")
        
        # Set callbacks
        self.mqtt_client.on_connect = self.on_mqtt_connect
        self.mqtt_client.on_disconnect = self.on_mqtt_disconnect
        
        # Connect to broker
        try:
            self.mqtt_client.loop_stop()
            self.mqtt_client.connect(
                self.config.get("mqtt", "server"),
                self.config.getint("mqtt", "port"),
                keepalive=30  # Reduced keepalive for faster detection
            )

            self.mqtt_client.loop_start()  # Start the MQTT loop
            logger.debug("MQTT loop started")
            return True
        except Exception as e:
            logger.error(f"MQTT connection error: {str(e)}")
            return False
        
    def parse_and_publish(self, line):
        if not line:
            return
        logger.debug(f"From Radio: {line}")
        message = {
            "origin": self.repeater_name,
            "origin_id": self.repeater_pub_key,
            "timestamp": datetime.now().isoformat()
        }

        # Handle RAW messages
        if "U RAW:" in line:
            parts = line.split("U RAW:")
            if len(parts) > 1:
                self.last_raw = parts[1].strip()

        # Handle DEBUG messages
        if self.debug:
            if line.startswith("DEBUG"):
                message.update({
                    "type": "DEBUG",
                    "message": line
                })
                self.safe_publish(self.config.get("topics", "debug"), json.dumps(message))
                return

        # Handle Packet messages (RX and TX)
        packet_match = PACKET_PATTERN.match(line)
        if packet_match:
            packet_type = packet_match.group(5)
            payload = {
                "type": "PACKET",
                "direction": packet_match.group(3).lower(),  # rx or tx
                "time": packet_match.group(1),
                "date": packet_match.group(2),
                "len": packet_match.group(4),
                "packet_type": packet_type,
                "route": packet_match.group(6),
                "payload_len": packet_match.group(7),
                "raw": self.last_raw
            }

            # Add SNR, RSSI, score, and hash for RX packets
            if packet_match.group(3).lower() == "rx":
                payload.update({
                    "SNR": packet_match.group(8),
                    "RSSI": packet_match.group(9),
                    "score": packet_match.group(10),
                    "duration": packet_match.group(12),
                    "hash": packet_match.group(13)
                })

                # Add path for route=D
                if packet_match.group(6) == "D" and packet_match.group(14):
                    payload["path"] = packet_match.group(14)

            message.update(payload)
            self.safe_publish(self.config.get("topics", "packets"), json.dumps(message))
            return

    def run(self):
        if not self.connect_serial():
            return

        self.set_repeater_time()

        if not self.get_repeater_name():
            logger.error("Failed to get repeater name")
            return
        
        if not self.get_repeater_pubkey():
            logger.error("Failed to get the repeater id (public key)")
            return
        
        # Get radio info before connecting to MQTT
        self.radio_info = self.get_radio_info()
        if not self.radio_info:
            logger.error("Failed to get radio info")
            return
        
        while True:
            if self.connect_mqtt():
                break
            else:
                logger.warning("MQTT connection failed. Retrying...")
                sleep(1)
        
        try:
            while True:
                if self.should_exit:
                    sys.exit(-1)
                try:
                    # Check for serial data
                    if self.ser.in_waiting > 0:
                        line = self.ser.readline().decode(errors='replace').strip()
                        logger.debug(f"RX: {line}")
                        self.parse_and_publish(line)
                except OSError:
                   logger.warning("Serial connection unavailable, trying to reconnect")
                   self.connect_serial()
                   sleep(0.5)
                sleep(0.01)
                
        except KeyboardInterrupt:
            logger.info("\nExiting...")
            self.mqtt_client.disconnect()
            self.ser.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-debug", action="store_true", help="Enable debug output")
    args = parser.parse_args()
    
    if args.debug:
        logger.setLevel(logging.DEBUG)

    bridge = MeshCoreBridge(debug=args.debug)
    bridge.run()