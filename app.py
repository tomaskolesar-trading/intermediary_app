import os
import json
import logging
import redis
from datetime import datetime
from flask import Flask, request, jsonify
from xAPIConnector import *
import time

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Redis setup with SSL configuration
REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379')
try:
    redis_client = redis.from_url(
        REDIS_URL,
        ssl_cert_reqs=None  # Ignore SSL certificate verification
    )
except Exception as e:
    logger.error(f"Redis connection error: {str(e)}")
    redis_client = None

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

class PositionState:
    def __init__(self, redis_client):
        self.redis = redis_client

    def _get_key(self, symbol):
        return f"position:{symbol}"

    def can_buy(self, symbol: str) -> bool:
        """Check if we can open a buy position"""
        if not self.redis:
            return True
        position = self.redis.get(self._get_key(symbol))
        return position is None or not json.loads(position).get('active', False)

    def can_sell(self, symbol: str) -> bool:
        """Check if we can close (sell) a position"""
        if not self.redis:
            return True
        position = self.redis.get(self._get_key(symbol))
        return position is not None and json.loads(position).get('active', False)

    def record_buy(self, symbol: str):
        """Record a buy position"""
        if not self.redis:
            return
        position_data = {
            'active': True,
            'timestamp': datetime.now().isoformat(),
            'type': 'buy'
        }
        try:
            self.redis.set(self._get_key(symbol), json.dumps(position_data))
        except Exception as e:
            logger.error(f"Error recording buy: {str(e)}")

    def record_sell(self, symbol: str):
        """Record a position closure"""
        if not self.redis:
            return
        position_data = {
            'active': False,
            'timestamp': datetime.now().isoformat(),
            'type': 'sell'
        }
        try:
            self.redis.set(self._get_key(symbol), json.dumps(position_data))
        except Exception as e:
            logger.error(f"Error recording sell: {str(e)}")

    def get_position(self, symbol: str):
        """Get current position state"""
        if not self.redis:
            return None
        try:
            position = self.redis.get(self._get_key(symbol))
            return json.loads(position) if position else None
        except Exception as e:
            logger.error(f"Error getting position: {str(e)}")
            return None

class XTBSession:
    def __init__(self):
        self.client = None
        self.stream_client = None
        self.stream_session_id = None
        self.position_state = PositionState(redis_client)
        self.last_auth_time = 0
        self.auth_timeout = 300  # 5 minutes timeout

    def authenticate(self, force=False):
        """Authenticate with XTB API with retry logic"""
        current_time = time.time()
        
        # Return cached client if still valid
        if not force and self.client and (current_time - self.last_auth_time) < self.auth_timeout:
            return True

        try:
            # Close existing connection if any
            if self.client:
                try:
                    self.client.disconnect()
                except:
                    pass
                self.client = None

            max_retries = 3
            retry_delay = 2  # seconds

            for attempt in range(max_retries):
                try:
                    logger.info(f"Authentication attempt {attempt + 1}/{max_retries}")
                    self.client = APIClient()
                    
                    login_response = self.client.execute(
                        loginCommand(userId=XTB_USER_ID, password=XTB_PASSWORD, appName="Python Trading Bot")
                    )
                    
                    if login_response.get('status', False):
                        self.stream_session_id = login_response.get('streamSessionId')
                        self.last_auth_time = current_time
                        logger.info("Authentication successful")
                        return True
                    
                    logger.error(f"Authentication failed on attempt {attempt + 1}: {login_response}")
                    
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        retry_delay *= 2  # Exponential backoff
                    
                except Exception as e:
                    logger.error(f"Authentication error on attempt {attempt + 1}: {str(e)}")
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        retry_delay *= 2
            
            return False
            
        except Exception as e:
            logger.error(f"Fatal authentication error: {str(e)}")
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
            # Force new authentication
            if not self.authenticate(force=True):
                logger.error("Failed to authenticate for trade")
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

# Initialize XTB session
xtb_session = XTBSession()

@app.route("/")
def index():
    """Root endpoint - health check"""
    return "XTB TradingView Webhook Listener is running!"

@app.route("/webhook", methods=["POST"])
def webhook():
    """Handle incoming webhook requests"""
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
        logger.error(f"Webhook processing error: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route("/positions")
def get_positions():
    """Get current positions"""
    try:
        if not xtb_session.authenticate():
            return jsonify({"error": "Failed to authenticate"}), 500
        
        trades = xtb_session.client.commandExecute("getTrades", {"openedOnly": True})
        return jsonify(trades)
    except Exception as e:
        logger.error(f"Error getting positions: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route("/position/<symbol>")
def get_position(symbol):
    """Get position state for a symbol"""
    try:
        position = xtb_session.position_state.get_position(symbol)
        return jsonify({"symbol": symbol, "position": position})
    except Exception as e:
        logger.error(f"Error getting position state: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route("/test-connection")
def test_connection():
    """Test XTB connection with detailed status"""
    try:
        # Force new authentication
        result = xtb_session.authenticate(force=True)
        
        if result:
            return jsonify({
                "connected": True,
                "session_id": xtb_session.stream_session_id,
                "auth_time": datetime.fromtimestamp(xtb_session.last_auth_time).isoformat()
            })
        else:
            return jsonify({
                "connected": False,
                "error": "Authentication failed",
                "last_attempt": datetime.fromtimestamp(xtb_session.last_auth_time).isoformat() if xtb_session.last_auth_time > 0 else None
            }), 500
            
    except Exception as e:
        logger.error(f"Connection test error: {e}")
        return jsonify({
            "connected": False,
            "error": str(e)
        }), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
