import logging
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .config import Config
from .state import BotState
from .storage import save_state
from .utils import balance_two_teams, format_lineups, parse_float_arg, parse_int_arg, validate_date, validate_time


def build_kb() -> types.InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ Записаться", callback_data="join")
    b.button(text="❌ Сняться", callback_data="leave")
    b.button(text="💳 Оплатил", callback_data="pay")
    b.adjust(1)
    return b.as_markup()


def get_main_text(state: BotState, cfg: Config) -> str:
    count = len(state.players)
    price = round(cfg.rent_price / count) if count else cfg.rent_price
    text = (
        "⚽️ СБОР НА ФУТБОЛ\n"
        f"📅 {state.match_data['date']} в {state.match_data['time']}\n"
        f"📌 Лимит: {state.match_data['limit']}\n"
        f"💰 С носа: {price} ₽ | В банк: +{cfg.bank_fee} ₽\n"
        f"🏦 В БАНКЕ: {state.bank_total} ₽\n"
        "---------------------------\n"
    )
    for i, p in enumerate(state.players, 1):
        text += f"{i}. {p['name']} {'✅' if p.get('paid') else '❌'}\n"
    return text


def create_app(cfg: Config, state: BotState) -> tuple[Bot, Dispatcher, AsyncIOScheduler]:
    bot = Bot(token=cfg.token)
    dp = Dispatcher()

    async def safe_send(*args, **kwargs):
        try:
            return await bot.send_message(*args, **kwargs)
        except Exception as e:
            logging.exception("Ошибка отправки сообщения: %s", e)
            return None

    async def refresh_message():
        text = get_main_text(state, cfg)
        msg_id = state.match_data.get("message_id")
        if msg_id:
            try:
                await bot.edit_message_text(text=text, chat_id=cfg.chat_id, message_id=msg_id, reply_markup=build_kb())
                return
            except Exception:
                pass
        msg = await safe_send(cfg.chat_id, text, reply_markup=build_kb(), message_thread_id=cfg.thread_payments)
        if msg:
            state.match_data["message_id"] = msg.message_id
            save_state(cfg.data_file, state)

    def admin(message: types.Message) -> bool:
        return message.from_user.id == cfg.admin_id

    @dp.callback_query(F.data == "join")
    async def join(cb: types.CallbackQuery):
        async with state.lock:
            if any(p["id"] == cb.from_user.id for p in state.players):
                await cb.answer("Ты уже в списке", show_alert=True)
                return
            if len(state.players) >= state.match_data["limit"]:
                await cb.answer("Лимит игроков уже достигнут", show_alert=True)
                return
            state.players.append({"id": cb.from_user.id, "name": cb.from_user.full_name, "paid": False, "guest": False})
            save_state(cfg.data_file, state)
        await refresh_message()
        await cb.answer("Готово")

    @dp.callback_query(F.data == "leave")
    async def leave(cb: types.CallbackQuery):
        async with state.lock:
            state.players = [p for p in state.players if p["id"] != cb.from_user.id]
            save_state(cfg.data_file, state)
        await refresh_message()
        await cb.answer("Готово")

    @dp.callback_query(F.data == "pay")
    async def pay(cb: types.CallbackQuery):
        async with state.lock:
            player = next((p for p in state.players if p["id"] == cb.from_user.id), None)
            if not player:
                await cb.answer("Сначала запишись", show_alert=True)
                return
            if not player.get("paid"):
                player["paid"] = True
                state.bank_total += cfg.bank_fee
                save_state(cfg.data_file, state)
        await refresh_message()
        await cb.answer("Оплата отмечена")

    @dp.message(Command("setdate"))
    async def setdate(message: types.Message):
        if not admin(message):
            return
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) < 2 or not validate_date(parts[1].strip()):
            await message.answer("Использование: /setdate <дд.мм>")
            return
        async with state.lock:
            state.match_data["date"] = parts[1].strip()
            save_state(cfg.data_file, state)
        await refresh_message()

    @dp.message(Command("settime"))
    async def settime(message: types.Message):
        if not admin(message):
            return
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) < 2 or not validate_time(parts[1].strip()):
            await message.answer("Использование: /settime <чч:мм>")
            return
        async with state.lock:
            state.match_data["time"] = parts[1].strip()
            save_state(cfg.data_file, state)
        await refresh_message()

    @dp.message(Command("setlimit"))
    async def setlimit(message: types.Message):
        if not admin(message):
            return
        value = parse_int_arg(message.text)
        if value is None or value <= 0:
            await message.answer("Использование: /setlimit <число>")
            return
        async with state.lock:
            state.match_data["limit"] = value
            save_state(cfg.data_file, state)
        await refresh_message()

    @dp.message(Command("bank"))
    async def bank(message: types.Message):
        if not admin(message):
            return
        value = parse_int_arg(message.text, allow_negative=True)
        if value is None:
            await message.answer("Использование: /bank <сумма>")
            return
        async with state.lock:
            state.bank_total = value
            save_state(cfg.data_file, state)
        await refresh_message()

    @dp.message(Command("setrating"))
    async def setrating(message: types.Message):
        if not admin(message):
            return
        parsed = parse_float_arg(message.text)
        if parsed is None:
            await message.answer("Использование: /setrating <имя> <рейтинг>")
            return
        name, value = parsed
        async with state.lock:
            state.ratings[name] = value
            save_state(cfg.data_file, state)
        await message.answer("OK")

    @dp.message(Command("setcore"))
    async def setcore(message: types.Message):
        if not admin(message):
            return
        payload = (message.text or "").split(maxsplit=1)
        if len(payload) < 2 or "|" not in payload[1]:
            await message.answer("Использование: /setcore <красные|белые> | <игрок1, игрок2>")
            return
        team_raw, players_raw = payload[1].split("|", maxsplit=1)
        team_name = team_raw.strip().lower()
        if team_name not in ("красные", "белые"):
            await message.answer("Можно фиксировать только команды: красные или белые")
            return
        players = [name.strip() for name in players_raw.split(",") if name.strip()]
        if not players:
            await message.answer("Укажи хотя бы одного игрока")
            return

        async with state.lock:
            pinned = state.tournament_data.setdefault("pinned_teams", {})
            pinned[team_name] = players
            save_state(cfg.data_file, state)
        await message.answer(f"Ядро для {team_name} сохранено")

    @dp.message(Command("clearcore"))
    async def clearcore(message: types.Message):
        if not admin(message):
            return
        async with state.lock:
            state.tournament_data.pop("pinned_teams", None)
            save_state(cfg.data_file, state)
        await message.answer("Фиксация ядра очищена")

    @dp.message(Command("swap"))
    async def swap(message: types.Message):
        if not admin(message):
            return
        payload = (message.text or "").split(maxsplit=1)
        if len(payload) < 2 or "|" not in payload[1]:
            await message.answer("Использование: /swap <игрок1> | <игрок2>")
            return
        p1, p2 = (part.strip() for part in payload[1].split("|", maxsplit=1))
        if not p1 or not p2:
            await message.answer("Использование: /swap <игрок1> | <игрок2>")
            return
        if not state.last_teams:
            await message.answer("Сначала сформируй составы через /lineup")
            return

        async with state.lock:
            team1 = next((team for team, players in state.last_teams.items() if p1 in players), None)
            team2 = next((team for team, players in state.last_teams.items() if p2 in players), None)
            if not team1 or not team2:
                await message.answer("Один из игроков не найден в текущих составах")
                return
            if team1 == team2:
                await message.answer("Игроки уже в одной команде")
                return

            i1 = state.last_teams[team1].index(p1)
            i2 = state.last_teams[team2].index(p2)
            state.last_teams[team1][i1], state.last_teams[team2][i2] = state.last_teams[team2][i2], state.last_teams[team1][i1]
            save_state(cfg.data_file, state)

        lineup_text = format_lineups(state.last_teams, state.ratings)
        await safe_send(cfg.chat_id, f"Составы обновлены\n\n{lineup_text}", message_thread_id=cfg.thread_teams)

    @dp.message(Command("lineup"))
    async def lineup(message: types.Message):
        total = len(state.players)
        if total < 8:
            await message.answer("Недостаточно игроков")
            return
        sorted_players = sorted(state.players, key=lambda x: state.ratings.get(x["name"], 5.0), reverse=True)
        names = [p["name"] for p in sorted_players]
        if total >= cfg.min_for_three_teams:
            sizes = (5, 5, 4) if total == 14 else (5, 5, 5)
            teams = [[] for _ in range(3)]
            sums = [0.0, 0.0, 0.0]
            for player in sorted_players:
                available = [i for i in range(3) if len(teams[i]) < sizes[i]]
                target = min(available, key=lambda i: sums[i])
                teams[target].append(player["name"])
                sums[target] += state.ratings.get(player["name"], 5.0)
            state.last_teams = {"красные": teams[0], "белые": teams[1], "зеленые": teams[2]}
        else:
            pinned = state.tournament_data.get("pinned_teams") if isinstance(state.tournament_data.get("pinned_teams"), dict) else None
            state.last_teams = balance_two_teams(names, state.ratings, pinned)
        async with state.lock:
            save_state(cfg.data_file, state)
        lineup_text = format_lineups(state.last_teams, state.ratings)
        await safe_send(cfg.chat_id, f"Составы готовы\n\n{lineup_text}", message_thread_id=cfg.thread_teams)

    async def create_next_match():
        async with state.lock:
            state.players.clear()
            next_tuesday = datetime.now() + timedelta(days=((1 - datetime.now().weekday()) % 7 or 7))
            state.match_data["date"] = next_tuesday.strftime("%d.%m")
            state.match_data["time"] = "22:00"
            state.match_data["message_id"] = None
            save_state(cfg.data_file, state)
        await refresh_message()

    async def monday_reminder():
        await safe_send(cfg.chat_id, "⏰ Напоминание: завтра футбол!", message_thread_id=cfg.thread_payments)

    async def tuesday_reminder():
        await safe_send(cfg.chat_id, "⚽ Через 30 минут начинаем!", message_thread_id=cfg.thread_payments)

    scheduler = AsyncIOScheduler()
    scheduler.add_job(create_next_match, "cron", day_of_week="sat", hour=12, minute=0, id="create_next_match")
    scheduler.add_job(monday_reminder, "cron", day_of_week="mon", hour=13, minute=0, id="monday_reminder")
    scheduler.add_job(tuesday_reminder, "cron", day_of_week="tue", hour=21, minute=30, id="tuesday_reminder")

    return bot, dp, scheduler
