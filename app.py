import os
import json
import logging
import requests
from flask import Flask, request, jsonify
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# XTB API Configuration
XTB_DEMO_URL = "https://ws.xtb.com/demo"
XTB_USER_ID = "17190137"
XTB_PASSWORD = "K193652744T"

# Symbol mapping between TradingView and XTB
SYMBOL_MAPPING = {
    "BTCUSD": "BITCOIN",
    "EURUSD": "EURUSD",
    "US500": "US500",
    "SPX500": "US500",
    "SP500": "US500"
}

class XTBSession:
    def __init__(self):
        self.session_id = None
        self.last_auth_time = None

    def authenticate(self):
        """Authenticate with XTB API"""
        payload = {
            "command": "login",
            "arguments": {
                "userId": XTB_USER_ID,
                "password": XTB_PASSWORD,
                "appName": "Python Trading Bot"
            }
        }

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Python Trading Bot",
            "Accept": "application/json",
            "Connection": "keep-alive"
        }

        try:
            logger.info("Attempting XTB authentication...")
            response = requests.post(
                XTB_DEMO_URL,
                json=payload,
                headers=headers,
                timeout=30
            )
            logger.info(f"Auth Response Status: {response.status_code}")
            logger.info(f"Auth Response: {response.text}")

            if response.status_code == 200:
                response_data = response.json()
                if response_data.get("status"):
                    self.session_id = response_data.get("streamSessionId")
                    self.last_auth_time = datetime.now()
                    logger.info("Successfully authenticated with XTB")
                    return True
                else:
                    logger.error(f"Authentication failed: {response_data}")
            else:
                logger.error(f"HTTP {response.status_code}: {response.text}")
            return False

        except Exception as e:
            logger.error(f"Authentication error: {str(e)}")
            return False

    def place_trade(self, symbol: str, action: str, volume: float):
        """Place a trade order"""
        if not self.session_id:
            if not self.authenticate():
                return {"error": "Failed to authenticate with XTB"}

        cmd = 0 if action.lower() == "buy" else 1  # 0 for BUY, 1 for SELL

        transaction = {
            "command": "tradeTransaction",
            "arguments": {
                "tradeTransInfo": {
                    "cmd": cmd,
                    "customComment": "TV Signal",
                    "expiration": 0,
                    "order": 0,
                    "price": 0.0,
                    "sl": 0.0,
                    "tp": 0.0,
                    "symbol": symbol,
                    "type": 0,
                    "volume": volume
                }
            }
        }

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Python Trading Bot",
            "Accept": "application/json",
            "Connection": "keep-alive"
        }

        try:
            response = requests.post(
                XTB_DEMO_URL,
                json=transaction,
                headers=headers,
                timeout=30
            )
            logger.info(f"Trade Response Status: {response.status_code}")
            logger.info(f"Trade Response: {response.text}")

            if response.status_code == 200:
                response_data = response.json()
                if response_data.get("status"):
                    logger.info(f"Successfully placed {action} order for {volume} {symbol}")
                    return {"success": True, "data": response_data}
                return {"error": response_data.get("errorDesc", "Unknown error")}
            return {"error": f"HTTP {response.status_code}: {response.text}"}

        except Exception as e:
            logger.error(f"Trade error: {str(e)}")
            return {"error": str(e)}

def convert_symbol(tv_symbol: str) -> str:
    """Convert TradingView symbol to XTB symbol"""
    return SYMBOL_MAPPING.get(tv_symbol, tv_symbol)

# Initialize XTB session
xtb_session = XTBSession()

@app.route("/test-xtb", methods=["GET"])
def test_xtb():
    try:
        # First, get our IP
        r = requests.get('https://api.ipify.org')
        our_ip = r.text
        logger.info(f"Testing from IP: {our_ip}")
        
        # Try XTB connection
        payload = {
            "command": "login",
            "arguments": {
                "userId": XTB_USER_ID,
                "password": XTB_PASSWORD,
                "appName": "Python Trading Bot"
            }
        }
        
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Python Trading Bot",
            "Accept": "application/json",
            "Connection": "keep-alive"
        }
        
        response = requests.post(
            XTB_DEMO_URL,
            json=payload,
            headers=headers,
            timeout=30
        )
        
        return jsonify({
            "heroku_ip": our_ip,
            "xtb_status": response.status_code,
            "xtb_response": response.text
        })
    except Exception as e:
        logger.error(f"Test endpoint error: {str(e)}")
        return jsonify({"error": str(e)})

@app.route("/webhook", methods=["POST"])
def webhook():
    """Handle incoming webhook from TradingView"""
    try:
        data = request.json
        logger.info(f"Received webhook: {data}")

        # Validate required fields
        if not all(key in data for key in ["action", "symbol", "volume"]):
            return jsonify({"error": "Missing required fields"}), 400

        # Extract and validate action
        action = data["action"].lower()
        if action not in ["buy", "sell"]:
            return jsonify({"error": "Invalid action"}), 400

        # Convert symbol and validate volume
        symbol = convert_symbol(data["symbol"])
        try:
            volume = float(data["volume"])
            if volume <= 0:
                return jsonify({"error": "Volume must be positive"}), 400
        except ValueError:
            return jsonify({"error": "Invalid volume"}), 400

        # Place the trade
        result = xtb_session.place_trade(symbol, action, volume)
        
        if "error" in result:
            return jsonify(result), 400
        return jsonify(result)

    except json.JSONDecodeError:
        return jsonify({"error": "Invalid JSON"}), 400
    except Exception as e:
        logger.error(f"Webhook error: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route("/health")
def health_check():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "authenticated": bool(xtb_session.session_id)
    })

@app.route("/")
def index():
    return "XTB TradingView Webhook Listener is running!"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
