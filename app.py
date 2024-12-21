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

class PositionState:
    def __init__(self):
        self.positions = {}  # Dictionary to track position states

    def can_buy(self, symbol: str) -> bool:
        """Check if we can open a buy position"""
        return symbol not in self.positions or not self.positions[symbol]['active']

    def can_sell(self, symbol: str) -> bool:
        """Check if we can close (sell) a position"""
        return symbol in self.positions and self.positions[symbol]['active']

    def record_buy(self, symbol: str):
        """Record a buy position"""
        self.positions[symbol] = {'active': True, 'timestamp': datetime.now()}

    def record_sell(self, symbol: str):
        """Record a position closure"""
        if symbol in self.positions:
            self.positions[symbol]['active'] = False

    def update_from_xtb(self, open_positions):
        """Update state based on XTB's actual positions"""
        for symbol in self.positions.keys():
            self.positions[symbol]['active'] = symbol in open_positions

class XTBSession:
    def __init__(self):
        self.client = None
        self.stream_client = None
        self.stream_session_id = None
        self.open_positions = {}
        self.position_state = PositionState()

    def authenticate(self):
        try:
            logger.info("Starting authentication process...")
            self.client = APIClient()
            
            login_response = self.client.execute(
                loginCommand(userId=XTB_USER_ID, password=XTB_PASSWORD, appName="Python Trading Bot")
            )
            
            if login_response.get('status', False):
                self.stream_session_id = login_response.get('streamSessionId')
                logger.info("Authentication successful")
                self.update_positions()
                return True
            
            logger.error(f"Authentication failed with response: {login_response}")
            return False
            
        except Exception as e:
            logger.error(f"Authentication error: {str(e)}")
            return False

    def update_positions(self):
        """Update the current open positions"""
        try:
            trades = self.client.commandExecute("getTrades", {
                "openedOnly": True
            })
            if trades.get("status"):
                self.open_positions = {}
                for trade in trades["returnData"]:
                    if not trade["closed"]:
                        self.open_positions[trade["symbol"]] = trade
                # Update position state based on actual XTB positions
                self.position_state.update_from_xtb(self.open_positions)
                logger.info(f"Updated open positions: {self.open_positions}")
                return trades
            return {"status": False, "error": "Failed to get trades"}
        except Exception as e:
            logger.error(f"Error updating positions: {e}")
            return {"status": False, "error": str(e)}

    def place_trade(self, symbol: str, action: str, volume: float):
        try:
            # Authenticate if needed
            if not self.client:
                if not self.authenticate():
                    return {"error": "Failed to authenticate", "status": False}

            # Update current positions
            self.update_positions()

            # Validate trade based on position state
            if action.lower() == "buy":
                if not self.position_state.can_buy(symbol):
                    return {"error": "Position already exists", "status": False}
            elif action.lower() == "sell":
                if not self.position_state.can_sell(symbol):
                    return {"error": "No position to close", "status": False}

            # Execute the trade
            result = self._execute_trade(symbol, action, volume)
            
            # Update position state if trade was successful
            if result.get("status"):
                if action.lower() == "buy":
                    self.position_state.record_buy(symbol)
                else:
                    self.position_state.record_sell(symbol)
                    
            return result

        except Exception as e:
            logger.error(f"Trade execution error: {e}")
            return {"error": str(e), "status": False}

    def _execute_trade(self, symbol: str, action: str, volume: float):
        """Internal method to execute the actual trade"""
        try:
            if action.lower() == "sell":
                if symbol in self.open_positions:
                    return self.close_position(symbol)
                return {"error": "No position to close", "status": False}

            if action.lower() == "buy":
                symbol_info = self.get_symbol_price(symbol)
                if not symbol_info:
                    return {"error": "Failed to get symbol price", "status": False}
                
                price = symbol_info.get("ask", 0)
                transaction_info = {
                    "cmd": 0,  # BUY
                    "symbol": symbol,
                    "volume": float(volume),
                    "type": 0,  # ORDER_OPEN
                    "price": price
                }

                response = self.client.execute({
                    "command": "tradeTransaction",
                    "arguments": {
                        "tradeTransInfo": transaction_info
                    }
                })
                
                if response.get("status"):
                    self.update_positions()
                return response

        except Exception as e:
            logger.error(f"Trade execution error: {e}")
            return {"error": str(e), "status": False}

    # ... (rest of the XTBSession methods remain the same) ...

# Initialize XTB session
xtb_session = XTBSession()

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.json
        logger.info(f"Received webhook: {data}")

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

        symbol = convert_symbol(data["symbol"])
        result = xtb_session.place_trade(symbol=symbol, action=action, volume=volume)
        
        if not result.get("status", False):
            return jsonify(result), 400
        return jsonify(result)

    except Exception as e:
        logger.error(f"Webhook processing error: {e}")
        return jsonify({"error": str(e)}), 500

# ... (rest of the routes remain the same) ...
