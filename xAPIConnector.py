import json
import logging
from flask import Flask, request, jsonify
from xAPIConnector import *

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# XTB Credentials
XTB_USER_ID = "17190137"
XTB_PASSWORD = "K193652744T"

class XTBSession:
    def __init__(self):
        self.client = None
        self.stream_client = None
        self.stream_session_id = None

    def authenticate(self):
        try:
            self.client = APIClient()
            login_response = self.client.execute(
                loginCommand(userId=XTB_USER_ID, password=XTB_PASSWORD, appName="Python Trading Bot")
            )
            logger.info(f"Login response: {login_response}")
            
            if login_response['status'] == True:
                self.stream_session_id = login_response['streamSessionId']
                return True
            return False
        except Exception as e:
            logger.error(f"Authentication error: {e}")
            return False

    def place_trade(self, symbol: str, action: str, volume: float):
        if not self.client:
            if not self.authenticate():
                return {"error": "Failed to authenticate"}

        cmd = TransactionSide.BUY if action.lower() == "buy" else TransactionSide.SELL
        
        transaction_info = {
            "cmd": cmd,
            "symbol": symbol,
            "volume": volume,
            "type": TransactionType.ORDER_OPEN,
            "price": 0.0
        }

        try:
            response = self.client.execute({
                "command": "tradeTransaction",
                "arguments": {
                    "tradeTransInfo": transaction_info
                }
            })
            
            logger.info(f"Trade response: {response}")
            return response
            
        except Exception as e:
            logger.error(f"Trade error: {e}")
            return {"error": str(e)}

# Initialize XTB session
xtb_session = XTBSession()

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.json
        logger.info(f"Received webhook: {data}")

        if not all(key in data for key in ["action", "symbol", "volume"]):
            return jsonify({"error": "Missing required fields"}), 400

        action = data["action"].lower()
        if action not in ["buy", "sell"]:
            return jsonify({"error": "Invalid action"}), 400

        result = xtb_session.place_trade(
            symbol=data["symbol"],
            action=action,
            volume=float(data["volume"])
        )
        
        if "error" in result:
            return jsonify(result), 400
        return jsonify(result)

    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/test-connection")
def test_connection():
    try:
        result = xtb_session.authenticate()
        return jsonify({
            "connected": result,
            "session_id": xtb_session.stream_session_id
        })
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route("/")
def index():
    return "XTB TradingView Webhook Listener is running!"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
