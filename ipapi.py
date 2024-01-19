from flask import Flask, jsonify, request, abort
import logging
from logging.handlers import RotatingFileHandler

app = Flask(__name__)

# 日志配置
logging.basicConfig(level=logging.INFO)
handler = RotatingFileHandler('app.log', maxBytes=10000, backupCount=3)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.addHandler(handler)

# 简单的内存存储解决方案
ip_store = {}

@app.route('/ips', methods=['GET'])
def get_ips():
    return jsonify(ip_store)

@app.route('/ips', methods=['POST'])
def add_ip():
    if not request.is_json:
        abort(400, description="Invalid data format. JSON required.")
    data = request.get_json()
    if 'name' not in data or 'ip' not in data:
        abort(400, description="Invalid data. Please provide 'name' and 'ip'.")
    ip_store[data['name']] = data['ip']
    logger.info(f"Added IP: {data['name']} - {data['ip']}")
    return jsonify({"message": "IP added successfully"}), 201

@app.route('/ips/<name>', methods=['DELETE'])
def delete_ip(name):
    if name not in ip_store:
        abort(404, description=f"IP with name '{name}' not found.")
    del ip_store[name]
    logger.info(f"Deleted IP: {name}")
    return jsonify({"message": "IP deleted successfully"})

@app.errorhandler(400)
def bad_request(error):
    return jsonify(error=str(error)), 400

@app.errorhandler(404)
def not_found(error):
    return jsonify(error=str(error)), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify(error=str(error)), 500

if __name__ == '__main__':
    app.run(debug=True)
