import os
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
XTB_USER_ID = os.environ.get('XTB_USER_ID', "17190137")
XTB_PASSWORD = os.environ.get('XTB_PASSWORD', "K193652744T")

# Symbol mapping between TradingView and XTB
SYMBOL_MAPPING = {
    "BTCUSD": "BITCOIN",
    "EURUSD": "EURUSD",
    "US500": "US500",
    "SPX500": "US500",
    "SP500": "US500"
}

def convert_symbol(tv_symbol: str) -> str:
    """Convert TradingView symbol to XTB symbol"""
    return SYMBOL_MAPPING.get(tv_symbol, tv_symbol)

class XTBSession:
    def __init__(self):
        self.client = None
        self.stream_client = None
        self.stream_session_id = None

    def authenticate(self):
        try:
            logger.info("Starting authentication process...")
            logger.info(f"Connecting to {DEFAULT_XAPI_ADDRESS}:{DEFAULT_XAPI_PORT}")
            
            self.client = APIClient()
            logger.info("APIClient created successfully")
            
            login_response = self.client.execute(
                loginCommand(userId=XTB_USER_ID, password=XTB_PASSWORD, appName="Python Trading Bot")
            )
            logger.info(f"Raw login response: {login_response}")
            
            if login_response.get('status', False):
                self.stream_session_id = login_response.get('streamSessionId')
                logger.info("Authentication successful")
                return True
            
            logger.error(f"Authentication failed with response: {login_response}")
            return False
        
        except Exception as e:
            logger.error(f"Authentication error: {str(e)}")
            logger.error(f"Error type: {type(e)}")
            import traceback
            logger.error(f"Detailed Traceback: {traceback.format_exc()}")
            return False

    def get_symbol_price(self, symbol: str):
        """Get current market price for a symbol"""
        try:
            symbol_response = self.client.commandExecute("getSymbol", {
                "symbol": symbol
            })
            logger.info(f"Symbol info response: {symbol_response}")
            
            if not symbol_response.get("status"):
                return None
                
            return symbol_response["returnData"]
            
        except Exception as e:
            logger.error(f"Error getting symbol price: {e}")
            return None

    def place_trade(self, symbol: str, action: str, volume: float):
        try:
            # Authenticate if not already authenticated
            if not self.client:
                if not self.authenticate():
                    return {"error": "Failed to authenticate"}

            # Get current market prices
            symbol_info = self.get_symbol_price(symbol)
            if not symbol_info:
                return {"error": "Failed to get symbol price"}
            
            # Select appropriate price based on action
            if action.lower() == "buy":
                price = symbol_info.get("ask", 0)
            else:
                price = symbol_info.get("bid", 0)

            logger.info(f"Using price {price} for {action} order")

            # Determine transaction side
            cmd = TransactionSide.BUY if action.lower() == "buy" else TransactionSide.SELL
            
            transaction_info = {
                "cmd": cmd,
                "symbol": symbol,
                "volume": volume,
                "type": TransactionType.ORDER_OPEN,
                "price": price
            }

            logger.info(f"Placing trade with info: {transaction_info}")

            response = self.client.execute({
                "command": "tradeTransaction",
                "arguments": {
                    "tradeTransInfo": transaction_info
                }
            })
            
            logger.info(f"Trade response: {response}")
            return response
            
        except Exception as e:
            logger.error(f"Trade execution error: {e}")
            return {"error": str(e)}

    def check_connection(self):
        """Check if connection is still valid"""
        try:
            if not self.client:
                return False
            response = self.client.commandExecute('ping')
            return response.get('status', False)
        except:
            return False

# Initialize XTB session
xtb_session = XTBSession()

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.json
        logger.info(f"Received webhook: {data}")

        # Validate incoming webhook data
        required_fields = ["action", "symbol", "volume"]
        if not all(key in data for key in required_fields):
            return jsonify({"error": "Missing required fields"}), 400

        action = data["action"].lower()
        if action not in ["buy", "sell"]:
            return jsonify({"error": "Invalid action"}), 400

        try:
            volume = float(data["volume"])
            if volume <= 0:
                return jsonify({"error": "Volume must be positive"}), 400
        except ValueError:
            return jsonify({"error": "Invalid volume format"}), 400

        # Convert symbol and attempt to place trade
        symbol = convert_symbol(data["symbol"])
        
        result = xtb_session.place_trade(
            symbol=symbol,
            action=action,
            volume=volume
        )
        
        # Handle trade result
        if "error" in result:
            return jsonify(result), 400
        return jsonify(result)

    except Exception as e:
        logger.error(f"Webhook processing error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/test-connection")
def test_connection():
    try:
        result = xtb_session.authenticate()
        return jsonify({
            "connected": result,
            "session_id": xtb_session.stream_session_id or "No session"
        })
    except Exception as e:
        logger.error(f"Connection test error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/check-price")
def check_price():
    """Endpoint to check current price for a symbol"""
    symbol = request.args.get('symbol', 'BITCOIN')
    if not xtb_session.client:
        if not xtb_session.authenticate():
            return jsonify({"error": "Failed to authenticate"}), 500
    
    symbol = convert_symbol(symbol)
    price_info = xtb_session.get_symbol_price(symbol)
    return jsonify(price_info)

@app.route("/ping")
def ping():
    """Check if we still have a valid connection"""
    return jsonify({
        "connected": xtb_session.check_connection()
    })

@app.route("/")
def index():
    return "XTB TradingView Webhook Listener is running!"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
