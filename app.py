import os
import json
import logging
import redis
from datetime import datetime
from flask import Flask, request, jsonify
from xAPIConnector import *

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Redis setup
REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379')
redis_client = redis.from_url(REDIS_URL)

app = Flask(__name__)

# XTB Credentials
XTB_USER_ID = os.environ.get('XTB_USER_ID', "17190137")
XTB_PASSWORD = os.environ.get('XTB_PASSWORD', "K193652744T")

class PositionState:
    def __init__(self, redis_client):
        self.redis = redis_client

    def _get_key(self, symbol):
        return f"position:{symbol}"

    def can_buy(self, symbol: str) -> bool:
        """Check if we can open a buy position"""
        position = self.redis.get(self._get_key(symbol))
        return position is None or not json.loads(position).get('active', False)

    def can_sell(self, symbol: str) -> bool:
        """Check if we can close (sell) a position"""
        position = self.redis.get(self._get_key(symbol))
        return position is not None and json.loads(position).get('active', False)

    def record_buy(self, symbol: str):
        """Record a buy position"""
        position_data = {
            'active': True,
            'timestamp': datetime.now().isoformat(),
            'type': 'buy'
        }
        self.redis.set(self._get_key(symbol), json.dumps(position_data))

    def record_sell(self, symbol: str):
        """Record a position closure"""
        position_data = {
            'active': False,
            'timestamp': datetime.now().isoformat(),
            'type': 'sell'
        }
        self.redis.set(self._get_key(symbol), json.dumps(position_data))

    def get_position(self, symbol: str):
        """Get current position state"""
        position = self.redis.get(self._get_key(symbol))
        return json.loads(position) if position else None

class XTBSession:
    def __init__(self):
        self.client = None
        self.stream_client = None
        self.stream_session_id = None
        self.position_state = PositionState(redis_client)

    def place_trade(self, symbol: str, action: str, volume: float):
        try:
            # Authenticate if needed
            if not self.client or not self.authenticate():
                logger.error("Authentication failed")
                return {"error": "Authentication failed", "status": False}

            action = action.lower()
            logger.info(f"Attempting {action} for {symbol}")

            # Check position state
            if action == "buy":
                if not self.position_state.can_buy(symbol):
                    logger.warning(f"Cannot buy {symbol} - position exists")
                    return {"error": "Position already exists", "status": False}
            elif action == "sell":
                if not self.position_state.can_sell(symbol):
                    logger.warning(f"Cannot sell {symbol} - no position exists")
                    return {"error": "No position to close", "status": False}

            # Execute trade
            result = self._execute_trade(symbol, action, volume)
            
            # Update state if trade successful
            if result.get("status"):
                if action == "buy":
                    self.position_state.record_buy(symbol)
                else:
                    self.position_state.record_sell(symbol)
                logger.info(f"Trade successful: {action} {symbol}")
            
            return result

        except Exception as e:
            logger.error(f"Trade execution error: {str(e)}")
            return {"error": str(e), "status": False}

    def _execute_trade(self, symbol: str, action: str, volume: float):
        """Execute the actual trade"""
        try:
            if action == "sell":
                return self._close_position(symbol)

            # Handle buy action
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

            logger.info(f"Executing transaction: {transaction_info}")
            response = self.client.execute({
                "command": "tradeTransaction",
                "arguments": {
                    "tradeTransInfo": transaction_info
                }
            })
            
            return response

        except Exception as e:
            logger.error(f"Trade execution error: {str(e)}")
            return {"error": str(e), "status": False}

    def _close_position(self, symbol: str):
        """Close an existing position"""
        try:
            trades = self.client.commandExecute("getTrades", {"openedOnly": True})
            if not trades.get("status"):
                return {"error": "Failed to get trades", "status": False}
                
            position = None
            for trade in trades["returnData"]:
                if trade["symbol"] == symbol and not trade["closed"]:
                    position = trade
                    break
                    
            if not position:
                return {"error": f"No open position found for {symbol}", "status": False}

            transaction_info = {
                "cmd": 1,  # SELL
                "symbol": symbol,
                "volume": float(position["volume"]),
                "order": int(position["order"]),
                "price": float(position["close_price"]),
                "type": 2,  # ORDER_CLOSE
            }

            logger.info(f"Closing position: {transaction_info}")
            return self.client.execute({
                "command": "tradeTransaction",
                "arguments": {
                    "tradeTransInfo": transaction_info
                }
            })

        except Exception as e:
            logger.error(f"Error closing position: {str(e)}")
            return {"error": str(e), "status": False}

    # ... (rest of the XTBSession methods remain the same) ...

# Initialize XTB session
xtb_session = XTBSession()

@app.route("/positions")
def get_positions():
    """Get current positions"""
    if not xtb_session.client:
        if not xtb_session.authenticate():
            return jsonify({"error": "Failed to authenticate"}), 500
    
    trades = xtb_session.client.commandExecute("getTrades", {"openedOnly": True})
    return jsonify(trades)

@app.route("/position/<symbol>")
def get_position(symbol):
    """Get position state for a symbol"""
    position = xtb_session.position_state.get_position(symbol)
    return jsonify({"symbol": symbol, "position": position})

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

        symbol = data["symbol"]
        result = xtb_session.place_trade(symbol=symbol, action=action, volume=volume)
        
        if not result.get("status", False):
            return jsonify(result), 400
            
        return jsonify(result)

    except Exception as e:
        logger.error(f"Webhook processing error: {str(e)}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
