import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


def _get_env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return int(raw)


@dataclass(frozen=True)
class Config:
    token: str
    admin_id: int
    chat_id: int
    thread_payments: int
    thread_teams: int
    data_file: str
    rent_price: int
    bank_fee: int
    min_for_three_teams: int



def load_config() -> Config:
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise ValueError("BOT_TOKEN не найден в переменных окружения!")
    return Config(
        token=token,
        admin_id=_get_env_int("ADMIN_ID", 296231879),
        chat_id=_get_env_int("CHAT_ID", -1003543317401),
        thread_payments=_get_env_int("THREAD_PAYMENTS", 4),
        thread_teams=_get_env_int("THREAD_TEAMS", 5),
        data_file=os.getenv("DATA_FILE", "football_data.json"),
        rent_price=_get_env_int("RENT_PRICE", 5400),
        bank_fee=_get_env_int("BANK_FEE", 400),
        min_for_three_teams=_get_env_int("MIN_FOR_THREE_TEAMS", 14),
    )
