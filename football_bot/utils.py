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
    parts = (text or "").split()
    if len(parts) < 3:
        return None
    raw_name = " ".join(parts[1:-1]).strip()
    raw_rating = parts[-1].strip()
    if not raw_name:
        return None
    try:
        return raw_name, float(raw_rating.replace(",", "."))
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


def clamp_rating(value: float, min_rating: float = 3.0, max_rating: float = 9.5) -> float:
    return max(min_rating, min(max_rating, value))


def get_two_team_rating_delta(score_diff: int, k: float = 0.1) -> float:
    if score_diff <= 0:
        return 0.0
    if score_diff == 1:
        return round(k * 0.35, 3)
    if score_diff == 2:
        return round(k * 0.7, 3)
    return round(k, 3)


def get_three_team_rating_deltas(points: dict[str, int], k: float = 0.12, max_delta: float = 0.2) -> dict[str, float]:
    if not points:
        return {}
    avg = sum(points.values()) / len(points)
    spread = max(points.values()) - min(points.values())
    spread_factor = 1.0 if spread >= 4 else (0.7 if spread >= 2 else 0.4)

    deltas: dict[str, float] = {}
    for team, value in points.items():
        normalized = value - avg
        delta = normalized * k * spread_factor
        if delta > max_delta:
            delta = max_delta
        if delta < -max_delta:
            delta = -max_delta
        deltas[team] = round(delta, 3)
    return deltas


def balance_two_teams(
    names: list[str],
    ratings: dict[str, float] | None = None,
    pinned_teams: dict[str, list[str]] | None = None,
    default_rating: float = 5.0,
) -> dict[str, list[str]]:
    ratings = ratings or {}
    pinned_teams = pinned_teams or {}
    team_names = ("красные", "белые")
    targets = {team_names[0]: (len(names) + 1) // 2, team_names[1]: len(names) // 2}

    available_names = set(names)
    used: set[str] = set()
    teams: dict[str, list[str]] = {}
    sums: dict[str, float] = {}

    for team in team_names:
        team_pins = []
        for player in pinned_teams.get(team, []):
            if player in available_names and player not in used:
                team_pins.append(player)
                used.add(player)
        teams[team] = team_pins
        sums[team] = sum(ratings.get(player, default_rating) for player in team_pins)

    remaining = [name for name in names if name not in used]

    for name in remaining:
        candidates = [team for team in team_names if len(teams[team]) < targets[team]]
        if not candidates:
            candidates = list(team_names)
        target = min(candidates, key=lambda team: (sums[team], len(teams[team])))
        teams[target].append(name)
        sums[target] += ratings.get(name, default_rating)

    return teams


def format_lineups(
    teams: dict[str, list[str]],
    ratings: dict[str, float] | None = None,
    default_rating: float = 5.0,
) -> str:
    lines: list[str] = []
    ratings = ratings or {}
    totals: list[float] = []
    for team_name, players in teams.items():
        title = team_name.capitalize()
        total_rating = sum(ratings.get(name, default_rating) for name in players)
        totals.append(total_rating)
        player_list = "\n".join(f"- {name}" for name in players) if players else "- —"
        lines.append(f"{title} (рейтинг: {total_rating:.1f}):\n{player_list}")
    if len(totals) == 2:
        diff = abs(totals[0] - totals[1])
        lines.append(f"Разница рейтингов: {diff:.1f}")
    return "\n\n".join(lines)
