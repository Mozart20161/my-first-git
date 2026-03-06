import asyncio
from dataclasses import dataclass, field

DEFAULT_RATINGS = {
    "Александр Беляев": 8.8,
    "Юрец": 8.5,
    "Alex Vegel": 8.4,
    "Никита от Сергея": 7.5,
    "Evgeny Matveev": 7.3,
    "Александр С": 7.3,
    "Alexandr Zaytsev": 7.4,
    "Яковлев": 7.0,
    "Андрей": 6.6,
    "Роман": 5.7,
    "Valery Boronin": 5.8,
    "Andrey": 5.8,
    "Andrew Shumilov": 6.1,
    "Слава": 5.6,
    "Виталий": 5.3,
    "Ruslan": 7.1,
    "Pavel Churilov": 7.0,
    "Сергей": 8.6,
    "Дмитрий Рубцов": 6.8,
}


@dataclass
class BotState:
    players: list[dict] = field(default_factory=list)
    bank_total: int = 0
    match_data: dict = field(default_factory=lambda: {"date": "10.02", "time": "22:00", "limit": 15, "message_id": None})
    ratings: dict[str, float] = field(default_factory=lambda: DEFAULT_RATINGS.copy())
    tournament_data: dict = field(default_factory=dict)
    last_teams: dict | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
