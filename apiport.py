from flask import Flask, request, jsonify
import socket

app = Flask(__name__)

def is_port_open(ip, port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1)  # 设置超时时间
    try:
        sock.connect((ip, port))
        return True
    except socket.error:
        return False
    finally:
        sock.close()

@app.route('/check_port')
def check_port():
    ip = request.args.get('ip')
    port = request.args.get('port', type=int)
    if not ip or port is None:
        return jsonify({'error': 'Missing IP or port parameters'}), 400
    status = is_port_open(ip, port)
    return jsonify({'ip': ip, 'port': port, 'open': status})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10080)
~                                             
