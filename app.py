import os
import json
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# XTB API Credentials (set these as environment variables)
XTB_API_URL = os.getenv("XTB_API_URL", "https://ws.xtb.com/demo")  # Default to demo API
XTB_USER_ID = os.getenv("17190137")  # XTB user ID (set this in environment variables)
XTB_PASSWORD = os.getenv("K193652744T")  # XTB password (set this in environment variables)

# Global session ID for XTB API
session_id = None

# Authenticate with XTB API
def authenticate():
    global session_id
    payload = {"userId": XTB_USER_ID, "password": XTB_PASSWORD}
    try:
        response = requests.post(f"{XTB_API_URL}/login", json=payload)
        response_data = response.json()
        if response.status_code == 200 and response_data.get("status"):
            session_id = response_data["streamSessionId"]
            print("[INFO] Authenticated with XTB!")
            return True
        else:
            print("[ERROR] Authentication failed:", response_data)
            return False
    except Exception as e:
        print("[ERROR] Exception during authentication:", e)
        return False

# Place a trade order
def place_order(symbol, action, volume):
    if not session_id:
        print("[INFO] No active session. Attempting authentication...")
        if not authenticate():
            return {"error": "Failed to authenticate with XTB API"}

    order_type = 0 if action == "buy" else 1  # 0 = Buy, 1 = Sell
    payload = {
        "cmd": order_type,
        "symbol": symbol,
        "volume": volume,
        "type": 0,  # Market order
    }
    headers = {"Content-Type": "application/json", "Cookie": f"X-Auth-Token={session_id}"}

    try:
        response = requests.post(f"{XTB_API_URL}/tradeTransaction", json=payload, headers=headers)
        response_data = response.json()
        if response.status_code == 200:
            print("[INFO] Trade order placed:", response_data)
            return response_data
        else:
            print("[ERROR] Failed to place order:", response_data)
            return {"error": response_data}
    except Exception as e:
        print("[ERROR] Exception during order placement:", e)
        return {"error": str(e)}

# Webhook endpoint for TradingView alerts
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.json
        print("[INFO] Webhook received:", data)

        # Extract signal information from the alert
        action = data.get("action")  # "buy" or "sell"
        symbol = data.get("symbol", "EURUSD")  # Default symbol is EURUSD
        volume = float(data.get("volume", 0.1))  # Default volume is 0.1 lots

        if action not in ["buy", "sell"]:
            print("[ERROR] Invalid action in webhook payload:", action)
            return jsonify({"error": "Invalid action in webhook payload"}), 400

        # Place the order via XTB API
        result = place_order(symbol, action, volume)
        print("[INFO] Order result:", result)

        return jsonify(result)

    except Exception as e:
        print("[ERROR] Error processing webhook:", e)
        return jsonify({"error": str(e)}), 500

@app.route("/")
def index():
    return "XTB TradingView Webhook Listener is running!"

if __name__ == "__main__":
    # Use the PORT environment variable required by Heroku
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
