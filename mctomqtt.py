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
from auth_token import create_auth_token, read_private_key_file

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
        self.repeater_priv_key = None
        self.radio_info = None
        self.ser = None
        self.mqtt_clients = []
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
                self.ser.write(b"\r\n\r\n")
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

    def get_repeater_privkey(self):
        if not self.ser:
            return False
        
        self.ser.flushInput()
        self.ser.flushOutput()
        self.ser.write(b"get prv.key\r\n")
        logger.debug("Sent 'get prv.key' command")

        sleep(1.0)
        response = self.ser.read_all().decode(errors='replace')
        logger.debug(f"Raw response: {repr(response)}")

        if "-> >" in response:
            priv_key = response.split("-> >")[1].strip()
            if '\n' in priv_key:
                priv_key = priv_key.split('\n')[0]

            priv_key_clean = priv_key.replace(' ', '').replace('\r', '').replace('\n', '')
            if len(priv_key_clean) == 128:
                try:
                    int(priv_key_clean, 16)  # Validate it's hex
                    self.repeater_priv_key = priv_key_clean
                    logger.info(f"Repeater priv key: {self.repeater_priv_key[:4]}... (truncated for security)")
                    return True
                except ValueError as e:
                    logger.error(f"Response not valid hex: {priv_key_clean[:32]}... Error: {e}")
            else:
                logger.error(f"Response wrong length: {len(priv_key_clean)} (expected 128)")
        
        logger.error("Failed to get repeater priv key from response - command may not be supported by firmware")
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
        broker_name = userdata.get('name', 'unknown') if userdata else 'unknown'
        if rc == 0:
            self.mqtt_connected = True
            logger.info(f"Connected to MQTT broker: {broker_name}")
            # Publish online status once on connection
            self.publish_status("online", client)
        else:
            logger.error(f"MQTT connection failed for {broker_name} with code {rc}")

    def on_mqtt_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        broker_name = userdata.get('name', 'unknown') if userdata else 'unknown'
        logger.warning(f"Disconnected from MQTT broker {broker_name} (code: {reason_code})")
        # Exit if ANY broker disconnects
        self.mqtt_connected = False
        logger.warning("MQTT broker disconnected. Exiting...")
        self.should_exit = True

    def publish_status(self, status, client=None):
        """Publish status with additional information"""
        status_msg = {
            "status": status,
            "timestamp": datetime.now().isoformat(),
            "origin": self.repeater_name,
            "origin_id": self.repeater_pub_key,
            "repeater": self.repeater_name,
            "repeater_id": self.repeater_pub_key,
            "radio": self.radio_info if self.radio_info else "unknown"
        }
        if client:
            self.safe_publish(self.config.get("topics", "status"), json.dumps(status_msg), retain=True, client=client)
        else:
            self.safe_publish(self.config.get("topics", "status"), json.dumps(status_msg), retain=True)
        logger.debug(f"Published status: {status}")

    def safe_publish(self, topic, payload, retain=False, client=None):
        """Publish to one or all MQTT brokers"""
        if not self.mqtt_connected:
            logger.warning(f"Not connected - skipping publish to {topic}")
            return False

        success = False
        
        if client:
            clients_to_publish = [info for info in self.mqtt_clients if info['client'] == client]
        else:
            clients_to_publish = self.mqtt_clients
        
        for mqtt_client_info in clients_to_publish:
            config_section = mqtt_client_info['config_section']
            try:
                mqtt_client = mqtt_client_info['client']
                qos = self.config.getint(config_section, "qos", fallback=0)
                if qos == 1:
                    qos = 0  # force qos=1 to 0 because qos 1 can cause retry storms
                
                result = mqtt_client.publish(topic, payload, qos=qos, retain=retain)
                if result.rc != mqtt.MQTT_ERR_SUCCESS:
                    logger.error(f"Publish failed to {topic} on {config_section}: {mqtt.error_string(result.rc)}")
                else:
                    logger.debug(f"Published to {topic} on {config_section}")
                    success = True
            except Exception as e:
                logger.error(f"Publish error to {topic} on {config_section}: {str(e)}")
        
        return success

    def connect_mqtt_broker(self, config_section):
        """Connect to a single MQTT broker"""
        if not self.repeater_name:
            logger.error("Cannot connect to MQTT without repeater name")
            return None

        # Connect to broker
        try:
            if not self.config.getboolean(config_section, "enabled", fallback=True):
                logger.info(f"MQTT broker {config_section} is disabled, skipping")
                return None

            client_id = self.sanitize_client_id(self.repeater_pub_key)
            if config_section != "mqtt":
                client_id += f"_{config_section}"
            
            logger.info(f"Connecting to {config_section} with client ID: {client_id}")
            
            transport = self.config.get(config_section, "transport", fallback="tcp")
            
            mqtt_client = mqtt.Client(
                mqtt.CallbackAPIVersion.VERSION2,
                client_id=client_id,
                clean_session=False,
                transport=transport
            )
            
            mqtt_client.user_data_set({
                'name': config_section
            })
            
            use_auth_token = self.config.getboolean(config_section, "use_auth_token", fallback=False)
            
            if use_auth_token:
                if not self.repeater_priv_key:
                    logger.error(f"{config_section}: Private key not available from device for auth token")
                    return None
                
                try:
                    username = f"v1_{self.repeater_pub_key.upper()}"
                    audience = self.config.get(config_section, "token_audience", fallback=None)
                    claims = {}
                    if audience and audience.strip():
                        claims['aud'] = audience.strip()
                        logger.info(f"{config_section}: Using auth token authentication with device private key [aud: {audience}]")
                    else:
                        logger.info(f"{config_section}: Using auth token authentication with device private key")
                    
                    password = create_auth_token(self.repeater_pub_key, self.repeater_priv_key, **claims)
                    mqtt_client.username_pw_set(username, password)
                except Exception as e:
                    logger.error(f"{config_section}: Failed to generate auth token: {e}")
                    return None
            else:
                username = self.config.get(config_section, "username", fallback="")
                password = self.config.get(config_section, "password", fallback="")
                if username:
                    mqtt_client.username_pw_set(username, password)
            
            lwt_topic = self.config.get("topics", "status")
            lwt_payload = json.dumps({
                "status": "offline",
                "timestamp": datetime.now().isoformat(),
                "repeater": self.repeater_name,
                "repeater_id": self.repeater_pub_key
            })
            lwt_qos = self.config.getint(config_section, "qos", fallback=1)
            lwt_retain = self.config.getboolean(config_section, "retain", fallback=True)
            
            mqtt_client.will_set(lwt_topic, lwt_payload, qos=lwt_qos, retain=lwt_retain)
            logger.debug(f"{config_section}: Set LWT")
            
            mqtt_client.on_connect = self.on_mqtt_connect
            mqtt_client.on_disconnect = self.on_mqtt_disconnect
            
            server = self.config.get(config_section, "server")
            port = self.config.getint(config_section, "port")
            
            use_tls = self.config.getboolean(config_section, "use_tls", fallback=False)
            if use_tls:
                import ssl
                tls_insecure = self.config.getboolean(config_section, "tls_insecure", fallback=False)
                
                if tls_insecure:
                    mqtt_client.tls_set(cert_reqs=ssl.CERT_NONE)
                    mqtt_client.tls_insecure_set(True)
                    logger.warning(f"{config_section}: TLS certificate verification disabled (insecure)")
                else:
                    mqtt_client.tls_set(cert_reqs=ssl.CERT_REQUIRED)
                    mqtt_client.tls_insecure_set(False)
                
                logger.debug(f"{config_section}: TLS/SSL enabled")
            
            if transport == "websockets":
                mqtt_client.ws_set_options(
                    path="/",
                    headers=None
                )
                logger.debug(f"{config_section}: WebSocket transport configured")
            
            keepalive = self.config.getint(config_section, "keepalive", fallback=60)
            mqtt_client.connect(server, port, keepalive=keepalive)
            mqtt_client.loop_start()
            
            logger.info(f"Connected to {config_section} at {server}:{port} (transport={transport}, tls={use_tls})")
            return {
                'client': mqtt_client,
                'config_section': config_section
            }
            
        except Exception as e:
            logger.error(f"MQTT connection error for {config_section}: {str(e)}")
            return None

    def connect_mqtt(self):
        """Connect to all configured MQTT brokers"""
        for section in self.config.sections():
            if section.startswith("mqtt"):
                client_info = self.connect_mqtt_broker(section)
                if client_info:
                    self.mqtt_clients.append(client_info)
                else:
                    logger.warning(f"Failed to connect to MQTT broker: {section}")
        
        if len(self.mqtt_clients) == 0:
            logger.error("Failed to connect to any MQTT broker")
            return False
        
        logger.info(f"Connected to {len(self.mqtt_clients)} MQTT broker(s)")
        return True
        
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
        
        if not self.get_repeater_privkey():
            logger.warning("Failed to get repeater private key - auth token authentication will not be available")
        
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
            for mqtt_client_info in self.mqtt_clients:
                try:
                    mqtt_client_info['client'].disconnect()
                except:
                    pass
            self.ser.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-debug", action="store_true", help="Enable debug output")
    args = parser.parse_args()
    
    if args.debug:
        logger.setLevel(logging.DEBUG)

    bridge = MeshCoreBridge(debug=args.debug)
    bridge.run()