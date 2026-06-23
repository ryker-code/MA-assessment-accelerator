"""
Band communication utilities — direct REST API integration.

Each agent posts using its own API key so all 9 appear as distinct
identities in the Band chat room. Credentials loaded from agent_config.yaml.
"""
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

BAND_REST_URL = os.environ.get("BAND_REST_URL", "https://app.band.ai/")

# Map agent short-names → agent_config.yaml keys and Band handles
_AGENT_META = {
    "coordinator":            {"cfg": "coordinator",         "handle": "m-a-coordinator"},
    "seller-country-agent":   {"cfg": "country_agent",       "handle": "seller-country-agent"},
    "seller-sector-agent":    {"cfg": "sector_agent",        "handle": "seller-sector-agent"},
    "seller-company-agent":   {"cfg": "company_agent",       "handle": "seller-company-agent"},
    "buyer-country-agent":    {"cfg": "buyer_country_agent", "handle": "buyer-country-agent"},
    "buyer-sector-agent":     {"cfg": "buyer_sector_agent",  "handle": "buyer-sector-agent"},
    "buyer-company-agent":    {"cfg": "buyer_company_agent", "handle": "buyer-company-agent"},
    "risk-agent":             {"cfg": "risk_agent",          "handle": "risk-agent"},
    "deal-rationale-agent":   {"cfg": "deal_rationale_agent","handle": "deal-rationale-agent"},
    # Legacy aliases — used by old assessments and handle_message paths
    "country-agent":          {"cfg": "country_agent",       "handle": "seller-country-agent"},
    "sector-agent":           {"cfg": "sector_agent",        "handle": "seller-sector-agent"},
    "company-agent":          {"cfg": "company_agent",       "handle": "seller-company-agent"},
}

_configs: dict = {}


def _load_configs() -> dict:
    global _configs
    if _configs:
        return _configs
    # Look for agent_config.yaml in the project root (two levels up from this file)
    here = Path(__file__).resolve().parent
    for candidate in [here.parent.parent / "agent_config.yaml", Path("agent_config.yaml")]:
        if candidate.exists():
            import yaml
            with open(candidate) as f:
                _configs = yaml.safe_load(f) or {}
            return _configs
    return {}


def _agent_api_key(agent_name: str) -> str:
    cfg_key = _AGENT_META.get(agent_name, {}).get("cfg", agent_name.replace("-", "_"))
    return _load_configs().get(cfg_key, {}).get("api_key", "")


def _agent_uuid(agent_name: str) -> str:
    cfg_key = _AGENT_META.get(agent_name, {}).get("cfg", agent_name.replace("-", "_"))
    return _load_configs().get(cfg_key, {}).get("agent_id", "")


def _agent_handle(agent_name: str) -> str:
    handle = _AGENT_META.get(agent_name, {}).get("handle", agent_name)
    # Band handle format for agents: owner/slug
    return f"satwaksahoo/{handle}"


def create_assessment_room() -> str:
    """
    Coordinator creates a new Band chat room and adds all 8 sub-agents as participants.
    Returns the room_id or "" on failure.
    """
    coord_key = _agent_api_key("coordinator")
    if not coord_key:
        logger.warning("No coordinator API key in agent_config.yaml — skipping room creation")
        return ""
    try:
        from thenvoi_rest import RestClient, ChatRoomRequest, ParticipantRequest
        from band.client.rest import DEFAULT_REQUEST_OPTIONS

        client = RestClient(api_key=coord_key, base_url=BAND_REST_URL)

        # Create the room (coordinator is owner automatically)
        # Response is wrapped: resp.data is the ChatRoom object
        resp = client.agent_api_chats.create_agent_chat(
            chat=ChatRoomRequest(),
            request_options=DEFAULT_REQUEST_OPTIONS,
        )
        chat_room = resp.data if hasattr(resp, "data") else resp
        room_id = chat_room.id
        logger.info("Created Band room: %s", room_id)

        # Add all sub-agents as participants
        for agent_name in _AGENT_META:
            if agent_name == "coordinator":
                continue
            uuid = _agent_uuid(agent_name)
            if uuid:
                try:
                    client.agent_api_participants.add_agent_chat_participant(
                        chat_id=room_id,
                        participant=ParticipantRequest(participant_id=uuid),
                        request_options=DEFAULT_REQUEST_OPTIONS,
                    )
                    logger.debug("Added %s (%s) to room %s", agent_name, uuid, room_id)
                except Exception as exc:
                    logger.debug("Could not add %s: %s", agent_name, exc)

        return room_id
    except Exception as exc:
        logger.warning("Band room creation failed: %s", exc)
        return ""


def post_as_agent(
    sender: str,
    room_id: str,
    content: str,
    mention_agents: Optional[list] = None,
) -> bool:
    """
    Post a message to a Band room as a specific agent.

    sender:         agent short-name ("coordinator", "risk-agent", …)
    room_id:        Band chat room UUID
    content:        message text (may include @handle mentions)
    mention_agents: list of agent short-names to @mention (≥1 required by Band API)
                    Defaults to ["coordinator"] for sub-agents, ["deal-rationale-agent"] for coordinator.
    """
    if not room_id:
        return False

    api_key = _agent_api_key(sender)
    if not api_key:
        logger.debug("No API key for %s — skipping Band post", sender)
        return False

    # Default fallback mention
    if not mention_agents:
        mention_agents = ["coordinator"] if sender != "coordinator" else ["deal-rationale-agent"]

    try:
        from thenvoi_rest import RestClient, ChatMessageRequest, ChatMessageRequestMentionsItem
        from band.client.rest import DEFAULT_REQUEST_OPTIONS

        client = RestClient(api_key=api_key, base_url=BAND_REST_URL)

        mention_items = []
        for m in mention_agents:
            uuid = _agent_uuid(m)
            if uuid:
                mention_items.append(ChatMessageRequestMentionsItem(
                    id=uuid,
                    handle=_agent_handle(m),
                    name=_AGENT_META.get(m, {}).get("handle", m),
                ))

        if not mention_items:
            logger.debug("No valid mention UUIDs for %s — skipping post", sender)
            return False

        client.agent_api_messages.create_agent_chat_message(
            chat_id=room_id,
            message=ChatMessageRequest(content=content, mentions=mention_items),
            request_options=DEFAULT_REQUEST_OPTIONS,
        )
        return True
    except Exception as exc:
        logger.debug("Band post failed for %s: %s", sender, exc)
        return False


def format_agent_message(agent_name: str, status: str, content_summary: str) -> str:
    ts = datetime.utcnow().strftime("%H:%M UTC")
    return f"[{ts}] {agent_name} | {status}\n{content_summary}"


# --- Legacy wrappers (used by individual agent files' handle_message paths) ---

def send_to_room(room_id: str, message: str, mentions: list = None):
    """Post as coordinator (legacy interface)."""
    post_as_agent("coordinator", room_id, message)


def post_completion(room_id: str, agent_name: str, output_schema: dict, file_path: str):
    confidence = output_schema.get("confidence_score", 0)
    status = output_schema.get("status", "COMPLETE")
    msg = format_agent_message(
        agent_name, status,
        f"Confidence: {confidence:.0%} | File: {file_path}"
    )
    post_as_agent(agent_name, room_id, msg, mention_agents=["coordinator"])
