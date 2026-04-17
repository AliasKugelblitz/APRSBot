import aprslib
import threading
import queue
import time
import importlib
import os
import time

# APRS login details
CALLSIGN = "KE2FCA-10"
PASSCODE = "18848"  # Your passcode here
TACTICAL_NAME = "ALKBOT   "
# APRS server settings
SERVER = "rotate.aprs2.net"
PORT = 14580

# Path to the commands folder
COMMANDS_FOLDER = "commands"

# List of received message IDs to avoid duplicate ACKs
received_msgs = set()

# Dictionary to hold command functions
command_functions = {}

def load_commands():
    """Dynamically load command modules from the commands folder."""
    for filename in os.listdir(COMMANDS_FOLDER):
        if filename.endswith(".py") and filename != "__init__.py":
            module_name = filename[:-3]
            module = importlib.import_module(f"{COMMANDS_FOLDER}.{module_name}")
            if hasattr(module, 'handle_command'):
                command_functions[module_name] = module.handle_command
            else:
                print(f"Module {module_name} does not have a 'handle_command' function.")

def get_aprs_timestamp():
    """Returns APRS formatted timestamp: DDHHMMz (UTC)"""
    now = time.gmtime()
    return time.strftime("%d%H%M", now) + "z"

def send_ack(client, msgNo, to_call):
    """Function to send ACK in a separate thread."""
    to_call_padded = f"{to_call:<9}"
    
    # Handle message IDs that contain letters
    if any(char.isalpha() for char in msgNo):
        msgNo += "}"
    
    # 1. Source MUST be the login CALLSIGN for the server to accept it
    # 2. Every raw packet MUST end with \r\n
    ack_message = f"{CALLSIGN}>APRS::{to_call_padded}:ack{msgNo}\r\n"
    
    try:
        print(f"Sending ACK: {ack_message.strip()}")
        client.sendall(ack_message.encode('utf-8')) # Use encode for reliability
        print(f"ACK sent for message {msgNo} to {to_call}")
    except Exception as e:
        print(f"Error sending ACK: {e}")


def send_response(client, to_call, response_message):
    """Function to send a response message in a separate thread."""
    to_call_padded = f"{to_call:<9}"

    def split_message(message, max_length):
        words = message.split()
        messages = []
        current_message = ""
        for word in words:
            if len(current_message) + len(word) + 1 > max_length:
                messages.append(current_message)
                current_message = word
            else:
                if current_message:
                    current_message += " "
                current_message += word
        if current_message:
            messages.append(current_message)
        return messages

    messages = split_message(response_message, 48)

    for msg in messages:
        # Again: Use CALLSIGN for the header and append \r\n
        response = f"{CALLSIGN}>APRS::{to_call_padded}:{msg}\r\n"
        try:
            print(f"Sending response: {response.strip()}")
            client.sendall(response.encode('utf-8'))
            print(f"Response sent to {to_call}")
        except Exception as e:
            print(f"Error sending response: {e}")
        
        # APRS-IS suggests a delay between bursts
        time.sleep(2)


def handle_packet(packet):
    # Log all incoming messages for debugging
    if packet.get("format") == "message":
        print(f"Message from {packet.get('from')} to {packet.get('addresse')}: {packet.get('message_text')}")

    # Check if the message is for ALKBOT
    target = packet.get("addresse", "").strip()
    if "message_text" in packet and target == "ALKBOT":
        from_call = packet.get("from")
        msgNo = packet.get("msgNo")
        
        # Strip APRS message IDs (e.g., "hello {01" becomes "hello")
        raw_text = packet.get("message_text", "").split('{')[0].strip().lower()

        # Handle ACKs
        if msgNo and msgNo not in received_msgs:
            received_msgs.add(msgNo)
            threading.Thread(target=send_ack, args=(client, msgNo, from_call)).start()

        # Match Command
        command_function = command_functions.get(raw_text)
        if command_function:
            response_message = command_function()
            if response_message:
                print(f"Executing command '{raw_text}' for {from_call}")
                threading.Thread(target=send_response, args=(client, from_call, response_message)).start()

def connect_to_aprs():
    """Function to connect to the APRS network."""
    global client
    client = aprslib.IS(CALLSIGN, PASSCODE, port=PORT)
    print(f"Connecting to APRS-IS server {SERVER}:{PORT} as {CALLSIGN}")
    client.set_filter("b/KE2FCA-10/ALKBOT*")
    print(f"Filter set to listen only for messages addressed to {CALLSIGN}")

    try:
        client.connect(SERVER, PORT)
        print("Connected to APRS-IS server successfully")
        timestamp = get_aprs_timestamp()
        pos_packet = f"{CALLSIGN}>APRS,TCPIP*:;{TACTICAL_NAME}*{timestamp}4045.37N/07339.86W?Bot online\r\n"
        client.sendall(pos_packet)
        print(f"Position beacon sent for {CALLSIGN}")
        client.consumer(handle_packet, raw=False)
    except Exception as e:
        print(f"Error connecting to APRS-IS server: {e}")

if __name__ == "__main__":
    load_commands()
    connect_to_aprs()
