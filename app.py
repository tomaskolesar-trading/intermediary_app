import os
import json
import requests
from flask import Flask, request, jsonify
from websocket import create_connection

app = Flask(__name__)

# XTB API Credentials
XTB_API_URL = "https://xapi.xtb.com"
XTB_USER_ID = os.getenv("XTB_USER_ID")  # Add your XTB user ID here or as an environment variable
XTB_PASSWORD = os.getenv("XTB_PASSWORD")  # Add your XTB password here or as an environment variable

# Global session ID for XTB API
session_id = None

# Authenticate with XTB
def authenticate():
    global session_id
    payload = {"userId": XTB_USER_ID, "password": XTB_PASSWORD}
    response = requests.post(f"{XTB_API_URL}/login", json=payload)
    if response.status_code == 200 and response.json().get("status"):
        session_id = response.json()["streamSessionId"]
        print("Authenticated with XTB!")
        return True
    else:
        print("Authentication failed:", response.text)
        return False

# Place a trade order
def place_order(symbol, action, volume):
    if not session_id:
        if not authenticate():
            return {"error": "Failed to authenticate with XTB API"}

    order_type = 0 if action == "buy" else 1  # 0 = Buy, 1 = Sell
    payload = {
        "streamSessionId": session_id,
        "symbol": symbol,
        "cmd": order_type,
        "volume": volume,
        "type": 0,  # Market order
    }

    response = requests.post(f"{XTB_API_URL}/tradeTransaction", json=payload)
    if response.status_code == 200:
        return response.json()
    else:
        return {"error": response.text}

# Webhook endpoint for TradingView alerts
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.json
        print("Webhook received:", data)

        # Extract signal information
        action = data.get("action")  # "buy" or "sell"
        symbol = data.get("symbol", "EURUSD")  # Default symbol is EURUSD
        volume = float(data.get("volume", 0.1))  # Default volume is 0.1 lots

        if action not in ["buy", "sell"]:
            return jsonify({"error": "Invalid action in webhook payload"}), 400

        # Place the order via XTB API
        result = place_order(symbol, action, volume)
        print("Order result:", result)

        return jsonify(result)

    except Exception as e:
        print("Error processing webhook:", e)
        return jsonify({"error": str(e)}), 500

@app.route("/")
def index():
    return "XTB TradingView Webhook Listener is running!"

if __name__ == "__main__":
    # Use the PORT environment variable required by Heroku
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
