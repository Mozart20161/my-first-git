from datetime import datetime


def parse_int_arg(text: str | None, allow_negative: bool = False) -> int | None:
    parts = (text or "").split(maxsplit=1)
    if len(parts) < 2:
        return None
    raw = parts[1].strip()
    if not raw or (raw.startswith("-") and not allow_negative):
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def parse_float_arg(text: str | None) -> tuple[str, float] | None:
    parts = (text or "").split(maxsplit=2)
    if len(parts) < 3:
        return None
    try:
        return parts[1].strip(), float(parts[2].replace(",", "."))
    except ValueError:
        return None


def validate_date(value: str) -> bool:
    try:
        datetime.strptime(value, "%d.%m")
        return True
    except ValueError:
        return False


def validate_time(value: str) -> bool:
    try:
        datetime.strptime(value, "%H:%M")
        return True
    except ValueError:
        return False


def format_lineups(
    teams: dict[str, list[str]],
    ratings: dict[str, float] | None = None,
    default_rating: float = 5.0,
) -> str:
    lines: list[str] = []
    ratings = ratings or {}
    for team_name, players in teams.items():
        title = team_name.capitalize()
        total_rating = sum(ratings.get(name, default_rating) for name in players)
        player_list = "\n".join(f"- {name}" for name in players) if players else "- —"
        lines.append(f"{title} (рейтинг: {total_rating:.1f}):\n{player_list}")
    return "\n\n".join(lines)
