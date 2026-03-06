import json
import os
from typing import Any

from .state import BotState


def _validate_players(value: Any) -> list[dict]:
    if not isinstance(value, list):
        return []
    out = []
    for p in value:
        if isinstance(p, dict) and isinstance(p.get("id"), int) and isinstance(p.get("name"), str):
            out.append({"id": p["id"], "name": p["name"], "paid": bool(p.get("paid")), "guest": bool(p.get("guest"))})
    return out


def _validate_match_data(value: Any) -> dict:
    result = {"date": "10.02", "time": "22:00", "limit": 15, "message_id": None}
    if isinstance(value, dict):
        if isinstance(value.get("date"), str):
            result["date"] = value["date"]
        if isinstance(value.get("time"), str):
            result["time"] = value["time"]
        if isinstance(value.get("limit"), int) and value["limit"] > 0:
            result["limit"] = value["limit"]
        if isinstance(value.get("message_id"), int):
            result["message_id"] = value["message_id"]
    return result


def save_state(path: str, state: BotState) -> None:
    payload = {
        "players": state.players,
        "bank_total": state.bank_total,
        "match_data": state.match_data,
        "ratings": state.ratings,
        "tournament_data": state.tournament_data,
        "last_teams": state.last_teams,
    }
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def load_state(path: str, state: BotState) -> None:
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    state.players = _validate_players(data.get("players", []))
    state.bank_total = data.get("bank_total", 0) if isinstance(data.get("bank_total", 0), int) else 0
    state.match_data = _validate_match_data(data.get("match_data", {}))
    if isinstance(data.get("ratings"), dict):
        for k, v in data["ratings"].items():
            try:
                state.ratings[k] = float(v)
            except (TypeError, ValueError):
                pass
    state.tournament_data = data.get("tournament_data", {}) if isinstance(data.get("tournament_data"), dict) else {}
    lt = data.get("last_teams")
    state.last_teams = lt if isinstance(lt, dict) else None
