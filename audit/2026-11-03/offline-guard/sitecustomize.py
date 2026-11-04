import socket, os, ipaddress
_original_connect = socket.socket.connect
_original_connect_ex = socket.socket.connect_ex
def allowed(sock, address):
    if sock.family == socket.AF_UNIX: return True
    host = address[0]
    if host == "localhost": return True
    try: return ipaddress.ip_address(host).is_loopback
    except ValueError: return False
def connect(sock, address):
    if not allowed(sock,address):
        with open(os.environ["AUDIT_NETWORK_LOG"],"a") as f: f.write(repr(address)+"\n")
        raise RuntimeError("External network forbidden during offline audit")
    return _original_connect(sock,address)
def connect_ex(sock,address):
    if not allowed(sock,address):
        with open(os.environ["AUDIT_NETWORK_LOG"],"a") as f: f.write(repr(address)+"\n")
        raise RuntimeError("External network forbidden during offline audit")
    return _original_connect_ex(sock,address)
socket.socket.connect = connect
socket.socket.connect_ex = connect_ex
