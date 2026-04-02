import os
import json
import hashlib
import hmac
import base64
import requests
from flask import Flask, request, abort

app = Flask(__name__)

CHANNEL_SECRET = os.environ.get("CHANNEL_SECRET", "")
CHANNEL_ACCESS_TOKEN = os.environ.get("CHANNEL_ACCESS_TOKEN", "")
SOURCE_GROUP_ID = os.environ.get("SOURCE_GROUP_ID", "")
TARGET_GROUP_IDS_STR = os.environ.get("TARGET_GROUP_IDS", "")
TARGET_GROUP_IDS = [g.strip() for g in TARGET_GROUP_IDS_STR.split(",") if g.strip()]

PUSH_URL = "https://api.line.me/v2/bot/message/push"

known_groups = {}


def verify_signature(body: bytes, signature: str) -> bool:
    hash_val = hmac.new(
        CHANNEL_SECRET.encode("utf-8"), body, hashlib.sha256
    ).digest()
    expected = base64.b64encode(hash_val).decode("utf-8")
    return hmac.compare_digest(expected, signature)


def push_message(group_id: str, messages: list):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {CHANNEL_ACCESS_TOKEN}",
    }
    payload = {"to": group_id, "messages": messages}
    resp = requests.post(PUSH_URL, headers=headers, json=payload, timeout=10)
    print(f"Push to {group_id}: {resp.status_code} {resp.text}")
    return resp


def forward_event(event: dict):
    event_type = event.get("type")
    source = event.get("source", {})
    source_type = source.get("type")
    group_id = source.get("groupId", "")

    if event_type == "join" and source_type == "group":
        print(f"[JOIN] Bot joined group: {group_id}")
        known_groups[group_id] = True
        return

    if event_type != "message" or source_type != "group":
        return

    if SOURCE_GROUP_ID and group_id != SOURCE_GROUP_ID:
        return

    if not SOURCE_GROUP_ID:
        print(f"[DEBUG] Message from group {group_id} - please set SOURCE_GROUP_ID")
        return

    if not TARGET_GROUP_IDS:
        print("[DEBUG] TARGET_GROUP_IDS not set - cannot forward")
        return

    msg = event.get("message", {})
    msg_type = msg.get("type")

    forward_messages = []

    if msg_type == "text":
        text = msg.get("text", "")
        forward_messages = [{"type": "text", "text": f"[Forward]\n{text}"}]

    elif msg_type == "image":
        message_id = msg.get("id")
        forward_messages = [
            {"type": "text", "text": "📷 [Forward] Received an image, check source group"}
        ]

    elif msg_type == "sticker":
        package_id = msg.get("packageId")
        sticker_id = msg.get("stickerId")
        forward_messages = [
            {"type": "sticker", "packageId": package_id, "stickerId": sticker_id}
        ]

    else:
        forward_messages = [
            {"type": "text", "text": f"[Forward] Received {msg_type} message"}
        ]

    for target_id in TARGET_GROUP_IDS:
        push_message(target_id, forward_messages)


@app.route("/", methods=["GET"])
def health():
    return "LINE Forward Bot Running OK", 200


@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data()

    if not verify_signature(body, signature):
        print("[ERROR] Signature verification failed")
        abort(400)

    try:
        data = json.loads(body)
        events = data.get("events", [])
        for event in events:
            forward_event(event)
    except Exception as e:
        print(f"[ERROR] Event processing error: {e}")

    return "OK", 200


@app.route("/groups", methods=["GET"])
def list_groups():
    return json.dumps({"known_groups": list(known_groups.keys())}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
