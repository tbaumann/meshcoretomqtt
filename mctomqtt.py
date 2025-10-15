#!/usr/bin/env python3
import sys
import os
import json
import serial
import argparse
import re
import time
import calendar
import logging
from datetime import datetime
from time import sleep
from auth_token import create_auth_token, read_private_key_file

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("Error: paho-mqtt not installed. Install with:")
    print("pip install paho-mqtt")
    sys.exit(1)

def load_env_files():
    """Load environment variables from .env and .env.local files"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    env_file = os.path.join(script_dir, '.env')
    env_local_file = os.path.join(script_dir, '.env.local')
    
    def parse_env_file(filepath):
        """Parse a .env file and return a dictionary"""
        env_vars = {}
        if not os.path.exists(filepath):
            return env_vars
        
        with open(filepath, 'r') as f:
            for line in f:
                line = line.strip()
                # Skip comments and empty lines
                if not line or line.startswith('#'):
                    continue
                # Parse KEY=VALUE
                if '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip()
                    # Remove quotes if present
                    if value and value[0] in ('"', "'") and value[-1] == value[0]:
                        value = value[1:-1]
                    env_vars[key] = value
        return env_vars
    
    # Load .env first (defaults)
    env_vars = parse_env_file(env_file)
    
    # Load .env.local (overrides)
    local_vars = parse_env_file(env_local_file)
    env_vars.update(local_vars)
    
    # Set environment variables
    for key, value in env_vars.items():
        if key not in os.environ:
            os.environ[key] = value
    
    return env_vars

# Load environment configuration
load_env_files()

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

    def __init__(self, debug=False):
        self.debug = debug
        self.repeater_name = None
        self.repeater_pub_key = None
        self.repeater_priv_key = None
        self.radio_info = None
        self.ser = None
        self.mqtt_clients = []
        self.mqtt_connected = False
        self.should_exit = False
        self.global_iata = os.getenv('MCTOMQTT_IATA', 'XXX')
        self.reconnect_delay = 1.0  # Start with 1 second
        self.max_reconnect_delay = 120.0  # Max 2 minutes
        self.reconnect_backoff = 1.5  # Exponential backoff multiplier
        
        logger.info("Configuration loaded from environment variables")
    
    def get_env(self, key, fallback=''):
        """Get environment variable with fallback (all vars are MCTOMQTT_ prefixed)"""
        return os.getenv(f"MCTOMQTT_{key}", fallback)
    
    def get_env_bool(self, key, fallback=False):
        """Get boolean environment variable, checking MCTOMQTT_ prefix first"""
        value = self.get_env(key, str(fallback)).lower()
        return value in ('true', '1', 'yes', 'on')
    
    def get_env_int(self, key, fallback=0):
        """Get integer environment variable, checking MCTOMQTT_ prefix first"""
        try:
            return int(self.get_env(key, str(fallback)))
        except ValueError:
            return fallback
    
    def resolve_topic_template(self, template, broker_num=None):
        """Resolve topic template with {IATA} and {PUBLIC_KEY} placeholders"""
        if not template:
            return template
        
        # Get IATA - broker-specific or global
        iata = self.global_iata
        if broker_num:
            broker_iata = self.get_env(f'MQTT{broker_num}_IATA', '')
            if broker_iata:
                iata = broker_iata
        
        # Replace template variables
        resolved = template.replace('{IATA}', iata)
        resolved = resolved.replace('{PUBLIC_KEY}', self.repeater_pub_key if self.repeater_pub_key else 'UNKNOWN')
        return resolved
    
    def get_topic(self, topic_type, broker_num=None):
        """Get topic with template resolution, checking broker-specific override first"""
        topic_type_upper = topic_type.upper()
        
        # Check broker-specific topic override
        if broker_num:
            broker_topic = self.get_env(f'MQTT{broker_num}_TOPIC_{topic_type_upper}', '')
            if broker_topic:
                return self.resolve_topic_template(broker_topic, broker_num)
        
        # Fall back to global topic
        global_topic = self.get_env(f'TOPIC_{topic_type_upper}', '')
        return self.resolve_topic_template(global_topic, broker_num)

    def sanitize_client_id(self, name):
        """Convert repeater name to valid MQTT client ID"""
        prefix = self.get_env("MQTT1_CLIENT_ID_PREFIX", "meshcore_")
        client_id = prefix + name.replace(" ", "_")
        client_id = re.sub(r"[^a-zA-Z0-9_-]", "", client_id)
        return client_id[:23]

    def connect_serial(self):
        ports = self.get_env("SERIAL_PORTS", "/dev/ttyACM0").split(",")
        baud_rate = self.get_env_int("SERIAL_BAUD_RATE", 115200)
        timeout = self.get_env_int("SERIAL_TIMEOUT", 2)

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
        broker_num = userdata.get('broker_num', None) if userdata else None
        if rc == 0:
            # Reset reconnect delay on successful connection
            self.reconnect_delay = 1.0
            
            # Mark this specific broker as connected
            for mqtt_info in self.mqtt_clients:
                if mqtt_info['broker_num'] == broker_num:
                    mqtt_info['connected'] = True
                    break
            
            # Check if this is the first successful connection
            was_connected = self.mqtt_connected
            self.mqtt_connected = True
            
            if not was_connected:
                logger.info(f"Connected to MQTT broker: {broker_name}")
            else:
                logger.info(f"Reconnected to MQTT broker: {broker_name}")
            
            # Publish online status once on connection
            self.publish_status("online", client, broker_num)
        else:
            logger.error(f"MQTT connection failed for {broker_name} with code {rc}")

    def on_mqtt_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        broker_name = userdata.get('name', 'unknown') if userdata else 'unknown'
        broker_num = userdata.get('broker_num', None) if userdata else None
        
        logger.warning(f"Disconnected from MQTT broker {broker_name} (code: {reason_code})")
        
        # Mark this specific client as disconnected
        for mqtt_info in self.mqtt_clients:
            if mqtt_info['client'] == client:
                mqtt_info['connected'] = False
                mqtt_info['reconnect_at'] = time.time() + self.reconnect_delay
                break
        
        # Check if ALL brokers are disconnected
        all_disconnected = all(not info.get('connected', False) for info in self.mqtt_clients)
        if all_disconnected:
            self.mqtt_connected = False

    def publish_status(self, status, client=None, broker_num=None):
        """Publish status with additional information"""
        status_msg = {
            "status": status,
            "timestamp": datetime.now().isoformat(),
            "origin": self.repeater_name,
            "origin_id": self.repeater_pub_key,
            "radio": self.radio_info if self.radio_info else "unknown"
        }
        status_topic = self.get_topic("status", broker_num)
        if client:
            self.safe_publish(status_topic, json.dumps(status_msg), retain=True, client=client, broker_num=broker_num)
        else:
            self.safe_publish(status_topic, json.dumps(status_msg), retain=True)
        logger.debug(f"Published status: {status}")

    def safe_publish(self, topic, payload, retain=False, client=None, broker_num=None):
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
            broker_num = mqtt_client_info['broker_num']
            try:
                mqtt_client = mqtt_client_info['client']
                qos = self.get_env_int(f"MQTT{broker_num}_QOS", 0)
                if qos == 1:
                    qos = 0  # force qos=1 to 0 because qos 1 can cause retry storms
                
                result = mqtt_client.publish(topic, payload, qos=qos, retain=retain)
                if result.rc != mqtt.MQTT_ERR_SUCCESS:
                    logger.error(f"Publish failed to {topic} on MQTT{broker_num}: {mqtt.error_string(result.rc)}")
                else:
                    logger.debug(f"Published to {topic} on MQTT{broker_num}")
                    success = True
            except Exception as e:
                logger.error(f"Publish error to {topic} on MQTT{broker_num}: {str(e)}")
        
        return success

    def connect_mqtt_broker(self, broker_num):
        """Connect to a single MQTT broker"""
        if not self.repeater_name:
            logger.error("Cannot connect to MQTT without repeater name")
            return None

        # Connect to broker
        try:
            if not self.get_env_bool(f"MQTT{broker_num}_ENABLED", False):
                logger.debug(f"MQTT broker {broker_num} is disabled, skipping")
                return None

            client_id = self.sanitize_client_id(self.repeater_pub_key)
            if broker_num > 1:
                client_id += f"_{broker_num}"
            
            logger.info(f"Connecting to MQTT{broker_num} with client ID: {client_id}")
            
            transport = self.get_env(f"MQTT{broker_num}_TRANSPORT", "tcp")
            
            mqtt_client = mqtt.Client(
                mqtt.CallbackAPIVersion.VERSION2,
                client_id=client_id,
                clean_session=False,
                transport=transport
            )
            
            mqtt_client.user_data_set({
                'name': f"MQTT{broker_num}",
                'broker_num': broker_num
            })
            
            use_auth_token = self.get_env_bool(f"MQTT{broker_num}_USE_AUTH_TOKEN", False)
            
            if use_auth_token:
                if not self.repeater_priv_key:
                    logger.error(f"MQTT{broker_num}: Private key not available from device for auth token")
                    return None
                
                try:
                    username = f"v1_{self.repeater_pub_key.upper()}"
                    audience = self.get_env(f"MQTT{broker_num}_TOKEN_AUDIENCE", "")
                    claims = {}
                    if audience:
                        claims['aud'] = audience
                        logger.info(f"MQTT{broker_num}: Using auth token authentication with device private key [aud: {audience}]")
                    else:
                        logger.info(f"MQTT{broker_num}: Using auth token authentication with device private key")
                    
                    password = create_auth_token(self.repeater_pub_key, self.repeater_priv_key, **claims)
                    mqtt_client.username_pw_set(username, password)
                except Exception as e:
                    logger.error(f"MQTT{broker_num}: Failed to generate auth token: {e}")
                    return None
            else:
                username = self.get_env(f"MQTT{broker_num}_USERNAME", "")
                password = self.get_env(f"MQTT{broker_num}_PASSWORD", "")
                if username:
                    mqtt_client.username_pw_set(username, password)
            
            lwt_topic = self.get_topic("status", broker_num)
            lwt_payload = json.dumps({
                "status": "offline",
                "timestamp": datetime.now().isoformat(),
                "repeater": self.repeater_name,
                "repeater_id": self.repeater_pub_key
            })
            lwt_qos = self.get_env_int(f"MQTT{broker_num}_QOS", 0)
            lwt_retain = self.get_env_bool(f"MQTT{broker_num}_RETAIN", True)
            
            mqtt_client.will_set(lwt_topic, lwt_payload, qos=lwt_qos, retain=lwt_retain)
            logger.debug(f"MQTT{broker_num}: Set LWT")
            
            mqtt_client.on_connect = self.on_mqtt_connect
            mqtt_client.on_disconnect = self.on_mqtt_disconnect
            
            server = self.get_env(f"MQTT{broker_num}_SERVER", "")
            if not server:
                logger.error(f"MQTT{broker_num}: Server not configured")
                return None
                
            port = self.get_env_int(f"MQTT{broker_num}_PORT", 1883)
            
            use_tls = self.get_env_bool(f"MQTT{broker_num}_USE_TLS", False)
            if use_tls:
                import ssl
                tls_verify = self.get_env_bool(f"MQTT{broker_num}_TLS_VERIFY", True)
                
                if tls_verify:
                    mqtt_client.tls_set(cert_reqs=ssl.CERT_REQUIRED)
                    mqtt_client.tls_insecure_set(False)
                    logger.debug(f"MQTT{broker_num}: TLS/SSL enabled with certificate verification")
                else:
                    mqtt_client.tls_set(cert_reqs=ssl.CERT_NONE)
                    mqtt_client.tls_insecure_set(True)
                    logger.warning(f"MQTT{broker_num}: TLS certificate verification disabled (insecure)")
            
            if transport == "websockets":
                mqtt_client.ws_set_options(
                    path="/",
                    headers=None
                )
                logger.debug(f"MQTT{broker_num}: WebSocket transport configured")
            
            keepalive = self.get_env_int(f"MQTT{broker_num}_KEEPALIVE", 60)
            mqtt_client.connect(server, port, keepalive=keepalive)
            mqtt_client.loop_start()
            
            logger.info(f"Connected to MQTT{broker_num} at {server}:{port} (transport={transport}, tls={use_tls})")
            return {
                'client': mqtt_client,
                'broker_num': broker_num,
                'server': server,
                'port': port,
                'connected': False,
                'reconnect_at': 0
            }
            
        except Exception as e:
            logger.error(f"MQTT connection error for MQTT{broker_num}: {str(e)}")
            return None

    def connect_mqtt(self):
        """Connect to all configured MQTT brokers"""
        # Try to connect to MQTT1, MQTT2, MQTT3, MQTT4 (can expand if needed)
        for broker_num in range(1, 5):
            client_info = self.connect_mqtt_broker(broker_num)
            if client_info:
                self.mqtt_clients.append(client_info)
        
        if len(self.mqtt_clients) == 0:
            logger.error("Failed to connect to any MQTT broker")
            return False
        
        logger.info(f"Initiated connection to {len(self.mqtt_clients)} MQTT broker(s)")
        
        # Wait for at least one broker to connect
        max_wait = 10  # seconds
        start_time = time.time()
        while not self.mqtt_connected and (time.time() - start_time) < max_wait:
            sleep(0.1)
        
        return self.mqtt_connected
    
    def reconnect_disconnected_brokers(self):
        """Check and reconnect any disconnected brokers with exponential backoff"""
        current_time = time.time()
        
        for mqtt_info in self.mqtt_clients:
            # Skip if already connected
            if mqtt_info.get('connected', False):
                continue
            
            # Check if it's time to attempt reconnect
            if current_time < mqtt_info.get('reconnect_at', 0):
                continue
            
            broker_num = mqtt_info['broker_num']
            try:
                logger.info(f"Attempting to reconnect MQTT{broker_num}... (delay was {self.reconnect_delay:.1f}s)")
                mqtt_info['client'].reconnect()
                
                # Update reconnect timing with exponential backoff
                self.reconnect_delay = min(self.reconnect_delay * self.reconnect_backoff, self.max_reconnect_delay)
                mqtt_info['reconnect_at'] = current_time + self.reconnect_delay
                
            except Exception as e:
                logger.warning(f"Reconnect attempt failed for MQTT{broker_num}: {e}")
                # Update reconnect timing with exponential backoff
                self.reconnect_delay = min(self.reconnect_delay * self.reconnect_backoff, self.max_reconnect_delay)
                mqtt_info['reconnect_at'] = current_time + self.reconnect_delay
        
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
                debug_topic = self.get_topic("debug")
                if debug_topic:
                    self.safe_publish(debug_topic, json.dumps(message))
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
            packets_topic = self.get_topic("packets")
            if packets_topic:
                self.safe_publish(packets_topic, json.dumps(message))
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
        
        # Initial MQTT connection
        retry_count = 0
        max_initial_retries = 10
        while retry_count < max_initial_retries:
            if self.connect_mqtt():
                break
            else:
                retry_count += 1
                wait_time = min(retry_count * 2, 30)  # Max 30 seconds between initial retries
                logger.warning(f"Initial MQTT connection failed. Retrying in {wait_time}s... (attempt {retry_count}/{max_initial_retries})")
                sleep(wait_time)
        
        if retry_count >= max_initial_retries:
            logger.error("Failed to establish initial MQTT connection after maximum retries")
            return
        
        try:
            while True:
                if self.should_exit:
                    sys.exit(-1)
                
                # Check and reconnect any disconnected brokers
                self.reconnect_disconnected_brokers()
                
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