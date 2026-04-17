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
    # 1. Log every message received so we can see what's happening
    if packet.get("format") == "message":
        from_call = packet.get("from")
        addresse = packet.get("addresse", "").strip()
        msg_text = packet.get("message_text", "")
        print(f"DEBUG: Msg from {from_call} to {addresse}: {msg_text}")

        # 2. Match the Tactical Call
        # We use .startswith because radios often send 'ALKBOT-0' or 'ALKBOT   '
        if addresse.startswith("ALKBOT"):
            msgNo = packet.get("msgNo")
            
            # 3. Clean the message text
            # Radios often add a message ID like 'hello {01'. We strip that off.
            clean_text = msg_text.split('{')[0].strip().lower()

            # 4. Handle Acknowledgement (ACK)
            if msgNo and msgNo not in received_msgs:
                received_msgs.add(msgNo)
                print(f"ACKing message {msgNo} from {from_call}")
                threading.Thread(target=send_ack, args=(client, msgNo, from_call)).start()

            # 5. Execute Command
            # This looks for a file in /commands that matches the message text
            command_func = command_functions.get(clean_text)
            if command_func:
                print(f"Command found: {clean_text}. Executing...")
                response = command_func()
                if response:
                    threading.Thread(target=send_response, args=(client, from_call, response)).start()
            else:
                print(f"No command script found for '{clean_text}' in /commands folder.")

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
