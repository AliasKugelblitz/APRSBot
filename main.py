import aprslib
import threading
import importlib
import os
import time

# APRS login details
CALLSIGN = "KE2FCA-10"
PASSCODE = "18848"  # Your passcode here
TACTICAL_NAME = "ALKBOT" # Simplified for logic checks
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
    if not os.path.exists(COMMANDS_FOLDER):
        return
    for filename in os.listdir(COMMANDS_FOLDER):
        if filename.endswith(".py") and filename != "__init__.py":
            module_name = filename[:-3]
            module = importlib.import_module(f"{COMMANDS_FOLDER}.{module_name}")
            if hasattr(module, 'handle_command'):
                command_functions[module_name] = module.handle_command

def get_aprs_timestamp():
    """Returns APRS formatted timestamp: DDHHMMz (UTC)"""
    return time.strftime("%d%H%M", time.gmtime()) + "z"

def send_ack(client, msgNo, to_call):
    """Function to send ACK in a separate thread."""
    to_call_padded = f"{to_call:<9}"
    if any(char.isalpha() for char in msgNo):
        msgNo += "}"
    # Source MUST be CALLSIGN to pass server validation
    ack_message = f"{CALLSIGN}>APRS::{to_call_padded}:ack{msgNo}\r\n"
    try:
        client.sendall(ack_message)
        print(f"ACK sent to {to_call}")
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
                current_message = f"{current_message} {word}".strip()
        if current_message:
            messages.append(current_message)
        return messages

    messages = split_message(response_message, 48)

    for msg in messages:
        response = f"{CALLSIGN}>APRS::{to_call_padded}:{msg}\r\n"
        try:
            client.sendall(response)
            print(f"Response sent to {to_call}")
        except Exception as e:
            print(f"Error sending response: {e}")
        time.sleep(5)

def handle_packet(packet):
    """Callback function to process incoming packets."""
    # Log incoming to see why ALKBOT might be failing
    raw_addresse = packet.get("addresse", "").strip()
    message_text = packet.get("message_text", "")
    
    # Logic: Accept if addressee is CALLSIGN OR if TACTICAL_NAME is in the addressee field
    if message_text and (raw_addresse == CALLSIGN or TACTICAL_NAME in raw_addresse):
        from_call = packet.get("from")
        msgNo = packet.get("msgNo")

        if msgNo and msgNo not in received_msgs:
            received_msgs.add(msgNo)
            print(f"Accepted msg for {raw_addresse} from {from_call}")
            threading.Thread(target=send_ack, args=(client, msgNo, from_call)).start()

        command_function = command_functions.get(message_text.lower().strip())
        if command_function:
            response_message = command_function()
            if response_message:
                threading.Thread(target=send_response, args=(client, from_call, response_message)).start()

def connect_to_aprs():
    """Function to connect to the APRS network."""
    global client
    client = aprslib.IS(CALLSIGN, PASSCODE, port=PORT)
    
    # Combined filter: b/ for your call, p/ for packets starting with ALK
    # This is more reliable than g/ on some rotate servers
    client.set_filter(f"b/{CALLSIGN} p/{TACTICAL_NAME[:3]}")

    try:
        client.connect(SERVER, PORT)
        print(f"Connected as {CALLSIGN}")
        
        # Create the Tactical Object (Object name MUST be 9 chars)
        obj_name = f"{TACTICAL_NAME:<9}"
        timestamp = get_aprs_timestamp()
        pos_packet = f"{CALLSIGN}>APRS,TCPIP*:;{obj_name}*{timestamp}4045.37N/07339.86W?Bot online\r\n"
        
        client.sendall(pos_packet)
        client.consumer(handle_packet, raw=False)
    except Exception as e:
        print(f"Connection error: {e}")

if __name__ == "__main__":
    load_commands()
    connect_to_aprs()