import os
import json
import logging
import requests
from flask import Flask, request, jsonify
from datetime import datetime, timedelta
import time

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# XTB API Configuration
XTB_API_URL = "https://ws.xtb.com/demo"
XTB_USER_ID = "17190137"
XTB_PASSWORD = "K193652744T"

# Symbol mapping between TradingView and XTB
SYMBOL_MAPPING = {
    "BTCUSD": "BITCOIN",
    "EURUSD": "EURUSD",
    "US500": "US500",
    "SPX500": "US500",  # Alternative TradingView symbol
    "SP500": "US500",   # Another alternative
    # Add more symbols as needed
}

class XTBSession:
    def __init__(self):
        self.session_id = None
        self.last_auth_time = None
        self.session_duration = timedelta(minutes=30)  # Session expires after 30 minutes

    def is_session_valid(self):
        if not self.session_id or not self.last_auth_time:
            return False
        return datetime.now() - self.last_auth_time < self.session_duration

    def authenticate(self):
        payload = {
            "command": "login",
            "arguments": {
                "userId": XTB_USER_ID,
                "password": XTB_PASSWORD
            }
        }

        try:
            response = requests.post(
                f"{XTB_API_URL}/login",
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=10
            )
            
            if response.status_code != 200:
                logger.error(f"Authentication failed with status code: {response.status_code}")
                return False

            response_data = response.json()
            
            if response_data.get("status"):
                self.session_id = response_data["streamSessionId"]
                self.last_auth_time = datetime.now()
                logger.info("Successfully authenticated with XTB")
                return True
            
            logger.error(f"Authentication failed: {response_data.get('errorDesc', 'Unknown error')}")
            return False

        except Exception as e:
            logger.error(f"Authentication error: {str(e)}")
            return False

    def ensure_authenticated(self):
        if not self.is_session_valid():
            return self.authenticate()
        return True

    def place_order(self, symbol: str, action: str, volume: float):
        if not self.ensure_authenticated():
            return {"error": "Failed to authenticate with XTB"}

        order_type = 0 if action.lower() == "buy" else 1
        
        payload = {
            "command": "tradeTransaction",
            "arguments": {
                "tradeTransInfo": {
                    "cmd": order_type,
                    "symbol": symbol,
                    "volume": volume,
                    "type": 0,  # Market order
                    "price": 0.0  # Market price
                }
            }
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.session_id}"
        }

        try:
            response = requests.post(
                f"{XTB_API_URL}/trade",
                json=payload,
                headers=headers,
                timeout=10
            )
            
            if response.status_code != 200:
                logger.error(f"Order placement failed with status code: {response.status_code}")
                return {"error": f"HTTP {response.status_code}"}

            response_data = response.json()
            
            if response_data.get("status"):
                logger.info(f"Successfully placed {action} order for {volume} {symbol}")
                return response_data
            
            error_msg = response_data.get("errorDesc", "Unknown error")
            logger.error(f"Order placement failed: {error_msg}")
            return {"error": error_msg}

        except Exception as e:
            logger.error(f"Order placement error: {str(e)}")
            return {"error": str(e)}

def convert_symbol(tv_symbol: str) -> str:
    """Convert TradingView symbol to XTB symbol"""
    return SYMBOL_MAPPING.get(tv_symbol, tv_symbol)

# Initialize XTB session
xtb_session = XTBSession()

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.json
        logger.info(f"Webhook received: {data}")

        # Validate required fields
        if not all(key in data for key in ["action", "symbol", "volume"]):
            logger.error("Missing required fields in webhook data")
            return jsonify({"error": "Missing required fields"}), 400

        # Extract and validate data
        action = data["action"].lower()
        if action not in ["buy", "sell"]:
            logger.error(f"Invalid action: {action}")
            return jsonify({"error": "Invalid action"}), 400

        # Convert symbol and place order
        tv_symbol = data["symbol"]
        xtb_symbol = convert_symbol(tv_symbol)
        
        try:
            volume = float(data["volume"])
            if volume <= 0:
                return jsonify({"error": "Volume must be positive"}), 400
        except ValueError:
            return jsonify({"error": "Invalid volume format"}), 400

        # Place the order
        result = xtb_session.place_order(xtb_symbol, action, volume)
        
        if "error" in result:
            return jsonify(result), 400
        
        return jsonify(result)

    except json.JSONDecodeError:
        logger.error("Invalid JSON in webhook payload")
        return jsonify({"error": "Invalid JSON"}), 400
    except Exception as e:
        logger.error(f"Webhook processing error: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route("/health")
def health_check():
    """Health check endpoint"""
    if xtb_session.is_session_valid():
        return jsonify({"status": "healthy", "session": "valid"})
    return jsonify({"status": "healthy", "session": "expired"})

@app.route("/")
def index():
    return "XTB TradingView Webhook Listener is running!"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
