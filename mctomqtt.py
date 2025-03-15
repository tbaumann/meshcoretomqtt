#!/usr/bin/env python3
import sys
import json
import serial
import argparse
import re
import time  # Added missing import
from datetime import datetime
from time import sleep

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("Error: paho-mqtt not installed. Install with:")
    print("pip install paho-mqtt")
    sys.exit(1)

# =============== CONFIGURATION SECTION ===============
MQTT_SERVER = "MQTT_SERVER"
MQTT_PORT = 1883
MQTT_USER = "MQTT_USER"
MQTT_PASS = "MQTT_PASSWORD"
SERIAL_PORTS = ["/dev/ttyUSB0", "/dev/ttyACM0"]
BAUD_RATE = 115200

# MQTT Topics
TOPIC_STATUS = "meshcore/status"
TOPIC_RAW = "meshcore/raw"
TOPIC_DEBUG = "meshcore/debug"
TOPIC_PACKETS = "meshcore/packets"
# ======================================================

class MeshCoreBridge:
    def __init__(self, debug=False):
        self.debug = debug
        self.repeater_name = None
        self.ser = None
        self.mqtt_client = None
        self.mqtt_connected = False
        self.last_status_time = 0
        self.status_interval = 60  # Send status every 60 seconds

    def sanitize_client_id(self, name):
        """Convert repeater name to valid MQTT client ID"""
        client_id = name.replace(" ", "_")
        client_id = re.sub(r"[^a-zA-Z0-9_-]", "", client_id)
        return client_id[:23]

    def connect_serial(self):
        for port in SERIAL_PORTS:
            try:
                self.ser = serial.Serial(
                    port=port,
                    baudrate=BAUD_RATE,
                    parity=serial.PARITY_NONE,
                    stopbits=serial.STOPBITS_ONE,
                    bytesize=serial.EIGHTBITS,
                    timeout=2,
                    rtscts=False
                )
                self.ser.flushInput()
                self.ser.flushOutput()
                if self.debug:
                    print(f"Connected to {port}")
                return True
            except (serial.SerialException, OSError):
                if self.debug:
                    print(f"Failed to connect to {port}")
                continue
        print("Failed to connect to any serial port")
        return False

    def get_repeater_name(self):
        if not self.ser:
            return False

        self.ser.flushInput()
        self.ser.flushOutput()
        self.ser.write(b"get name\r\n")
        if self.debug:
            print("Sent 'get name' command")

        sleep(0.5)
        response = self.ser.read_all().decode(errors='replace')
        if self.debug:
            print(f"Raw response: {response}")

        if "-> >" in response:
            self.repeater_name = response.split("-> >")[1].strip()
            if '\n' in self.repeater_name:
                self.repeater_name = self.repeater_name.split('\n')[0]
            if self.debug:
                print(f"Repeater name: {self.repeater_name}")
            return True
        
        return False

    def on_mqtt_connect(self, client, userdata, flags, rc, properties=None):
        if rc == 0:
            self.mqtt_connected = True
            if self.debug:
                print("Connected to MQTT broker")
            # Publish initial status
            self.publish_status("online")
        else:
            self.mqtt_connected = False
            print(f"MQTT connection failed with code {rc}")

    def publish_status(self, status):
        """Publish status with additional information"""
        status_msg = {
            "status": status,
            "timestamp": datetime.now().isoformat(),
            "repeater": self.repeater_name
        }
        if self.safe_publish(TOPIC_STATUS, json.dumps(status_msg), retain=True):
            self.last_status_time = time.time()
            if self.debug:
                print(f"Published status: {status}")

    def safe_publish(self, topic, payload, retain=False):
        if not self.mqtt_connected:
            if self.debug:
                print(f"Not connected - skipping publish to {topic}")
            return False

        try:
            result = self.mqtt_client.publish(topic, payload, retain=retain)
            if result.rc != mqtt.MQTT_ERR_SUCCESS:
                if self.debug:
                    print(f"Publish failed to {topic}: {mqtt.error_string(result.rc)}")
                return False
            if self.debug:
                print(f"Published to {topic}: {payload}")
            return True
        except Exception as e:
            if self.debug:
                print(f"Publish error to {topic}: {str(e)}")
            return False

    def connect_mqtt(self):
        if not self.repeater_name:
            print("Cannot connect to MQTT without repeater name")
            return False

        client_id = self.sanitize_client_id(self.repeater_name)
        if self.debug:
            print(f"Using client ID: {client_id}")

        self.mqtt_client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
            clean_session=False
        )
        
        self.mqtt_client.username_pw_set(MQTT_USER, MQTT_PASS)
        self.mqtt_client.will_set(TOPIC_STATUS, json.dumps({
            "status": "offline",
            "timestamp": datetime.now().isoformat(),
            "repeater": self.repeater_name
        }), retain=True)
        
        self.mqtt_client.on_connect = self.on_mqtt_connect
        self.mqtt_client.connect(MQTT_SERVER, MQTT_PORT, 60)
        self.mqtt_client.loop_start()
        return True

    def parse_and_publish(self, line):
        if not line:
            return

        message = {
            "origin": self.repeater_name,
            "timestamp": datetime.now().isoformat()
        }

        # Handle RAW messages
        if "U RAW:" in line:
            parts = line.split("U RAW:")
            if len(parts) > 1:
                message.update({
                    "type": "RAW",
                    "data": parts[1].strip()
                })
                self.safe_publish(TOPIC_RAW, json.dumps(message))
                return

        # Handle DEBUG messages
        if line.startswith("DEBUG"):
            message.update({
                "type": "DEBUG",
                "message": line
            })
            self.safe_publish(TOPIC_DEBUG, json.dumps(message))
            return

        # Handle Packet messages
        if "U: RX," in line:
            message.update({
                "type": "PACKET",
                "message": line
            })
            self.safe_publish(TOPIC_PACKETS, json.dumps(message))
            return

    def run(self):
        if not self.connect_serial():
            return
        
        if not self.get_repeater_name():
            print("Failed to get repeater name")
            if self.debug:
                print("Troubleshooting tips:")
                print("1. Check 'get name' command works in serial terminal")
                print("2. Verify correct line endings (CR+LF)")
                print("3. Check repeater response format")
            return
        
        if not self.connect_mqtt():
            return
        
        try:
            while True:
                # Check for serial data
                if self.ser.in_waiting > 0:
                    line = self.ser.readline().decode(errors='replace').strip()
                    if self.debug:
                        print(f"RX: {line}")
                    self.parse_and_publish(line)
                
                # Periodic status updates
                if time.time() - self.last_status_time > self.status_interval:
                    self.publish_status("online")
                
                sleep(0.01)
                
        except KeyboardInterrupt:
            print("\nExiting...")
            self.publish_status("offline")
            self.mqtt_client.disconnect()
            self.ser.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-debug", action="store_true", help="Enable debug output")
    args = parser.parse_args()
    
    bridge = MeshCoreBridge(debug=args.debug)
    bridge.run()