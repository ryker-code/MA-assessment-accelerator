import json
from datetime import datetime


def send_to_room(room_id: str, message: str, mentions: list = None):
    from band import band_send_message
    payload = {"room_id": room_id, "message": message}
    if mentions:
        payload["mentions"] = mentions
    band_send_message(**payload)


def format_agent_message(agent_name: str, status: str, content_summary: str) -> str:
    ts = datetime.utcnow().strftime("%H:%M UTC")
    return f"[{ts}] **{agent_name}** — `{status}`\n{content_summary}"


def post_completion(room_id: str, agent_name: str, output_schema: dict, file_path: str):
    confidence = output_schema.get("confidence_score", 0)
    status = output_schema.get("status", "COMPLETE")
    summary = (
        f"Assessment complete. Status: `{status}` | "
        f"Confidence: `{confidence:.0%}` | "
        f"File: `{file_path}`"
    )
    message = format_agent_message(agent_name, status, summary)
    send_to_room(room_id, message)
