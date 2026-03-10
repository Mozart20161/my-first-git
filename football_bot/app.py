import logging
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .config import Config
from .state import BotState
from .storage import save_state
from .utils import format_lineups, parse_float_arg, parse_int_arg, validate_date, validate_time


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
        f"💰 С носа: {price} ₽\n"
        f"🏦 В БАНКЕ: {state.bank_total} ₽\n"
        "💸 Оплата: +79537904028\n"
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
            except TelegramBadRequest as e:
                if "message is not modified" in str(e).lower():
                    return
            except Exception:
                pass
        msg = await safe_send(cfg.chat_id, text, reply_markup=build_kb(), message_thread_id=cfg.thread_payments)
        if msg:
            state.match_data["message_id"] = msg.message_id
            save_state(cfg.data_file, state)

    def admin(message: types.Message) -> bool:
        return message.from_user.id == cfg.admin_id

    def _tour_active() -> bool:
        return bool(state.tournament_data.get("active"))

    def _tour_text() -> str:
        tour = state.tournament_data
        if not tour or not tour.get("active"):
            return "🏆 Турнир не запущен"
        teams = tour["teams"]
        current = tour["current_pair"]
        waiting = tour["waiting"]
        lines = [
            "🏆 ТУРНИР 3х3 (winner stays)",
            f"Сейчас: {current[0]} vs {current[1]} | ждет: {waiting}",
            "",
            "Таблица:",
        ]
        sorted_rows = sorted(teams.items(), key=lambda x: (x[1]["points"], x[1]["wins"]), reverse=True)
        for idx, (name, row) in enumerate(sorted_rows, 1):
            lines.append(f"{idx}. {name}: {row['points']} очк (В:{row['wins']} Н:{row['draws']} П:{row['losses']})")
        return "\n".join(lines)

    def _tour_kb() -> types.InlineKeyboardMarkup:
        tour = state.tournament_data
        current = tour["current_pair"]
        b = InlineKeyboardBuilder()
        b.button(text=f"✅ Победа {current[0]}", callback_data=f"tour_win:{current[0]}")
        b.button(text="🤝 Ничья", callback_data="tour_draw")
        b.button(text=f"✅ Победа {current[1]}", callback_data=f"tour_win:{current[1]}")
        b.adjust(1)
        return b.as_markup()

    async def _render_tour_message() -> None:
        tour = state.tournament_data
        text = _tour_text()
        msg_id = tour.get("message_id")
        if msg_id:
            try:
                await bot.edit_message_text(
                    text=text,
                    chat_id=cfg.chat_id,
                    message_id=msg_id,
                    reply_markup=_tour_kb() if _tour_active() else None,
                )
                return
            except TelegramBadRequest as e:
                if "message is not modified" in str(e).lower():
                    return
            except Exception:
                pass
        msg = await safe_send(
            cfg.chat_id,
            text,
            reply_markup=_tour_kb() if _tour_active() else None,
            message_thread_id=cfg.thread_teams,
        )
        if msg:
            tour["message_id"] = msg.message_id

    def _apply_result(winner: str | None) -> None:
        tour = state.tournament_data
        t1, t2 = tour["current_pair"]
        waiting = tour["waiting"]
        teams = tour["teams"]
        streak = tour["streak"]

        if winner is None:
            teams[t1]["points"] += 1
            teams[t2]["points"] += 1
            teams[t1]["draws"] += 1
            teams[t2]["draws"] += 1
            if streak.get(t1, 0) >= 2 and streak.get(t2, 0) < 2:
                sit = t1
            elif streak.get(t2, 0) >= 2 and streak.get(t1, 0) < 2:
                sit = t2
            else:
                sit = t1
            stay = t2 if sit == t1 else t1
            next_pair = [stay, waiting]
            next_waiting = sit
        else:
            loser = t2 if winner == t1 else t1
            teams[winner]["points"] += 3
            teams[winner]["wins"] += 1
            teams[loser]["losses"] += 1
            next_pair = [winner, waiting]
            next_waiting = loser

        teams[t1]["matches"] += 1
        teams[t2]["matches"] += 1
        new_streak = {}
        for name in teams.keys():
            if name in next_pair:
                new_streak[name] = streak.get(name, 0) + 1 if name in (t1, t2) else 1
            else:
                new_streak[name] = 0
        tour["current_pair"] = next_pair
        tour["waiting"] = next_waiting
        tour["streak"] = new_streak

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
            if player.get("paid"):
                await cb.answer("Оплата уже отмечена", show_alert=True)
                return
            player["paid"] = True
            state.bank_total += cfg.bank_fee
            save_state(cfg.data_file, state)
        await refresh_message()
        await cb.answer("Оплата отмечена")



    @dp.message(Command("help"))
    async def help_cmd(message: types.Message):
        lines = [
            "Доступные команды:",
            "/help — показать это сообщение",
            "/players — список записавшихся",
            "/lineup — сформировать команды по рейтингам",
        ]
        if admin(message):
            lines.extend([
                "/setdate <дд.мм>",
                "/settime <чч:мм>",
                "/setlimit <число>",
                "/bank <сумма>",
                "/setrating <имя> <рейтинг>",
                "/tour_start — начать турнир (3 команды)",
                "/tour_end — завершить турнир и обновить рейтинги",
                "/table — показать таблицу турнира",
            ])
        await message.answer("\n".join(lines))

    @dp.message(Command("players"))
    async def players(message: types.Message):
        if not state.players:
            await message.answer("Пока никто не записался")
            return
        text = ["Игроки в списке:"]
        for i, p in enumerate(state.players, 1):
            paid = "✅" if p.get("paid") else "❌"
            rating = state.ratings.get(p["name"], 5.0)
            text.append(f"{i}. {p['name']} | рейтинг: {rating:.1f} | оплата: {paid}")
        await message.answer("\n".join(text))

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
            t1, t2 = [], []
            for i, name in enumerate(names):
                (t1 if i % 4 in (0, 3) else t2).append(name)
            state.last_teams = {"красные": t1, "белые": t2}
        async with state.lock:
            save_state(cfg.data_file, state)
        lineup_text = format_lineups(state.last_teams)
        await safe_send(cfg.chat_id, f"Составы готовы\n\n{lineup_text}", message_thread_id=cfg.thread_teams)

    @dp.message(Command("tour_start"))
    async def tour_start(message: types.Message):
        if not admin(message):
            return
        async with state.lock:
            teams = state.last_teams or {}
            names = [n for n in ("красные", "белые", "зеленые") if isinstance(teams.get(n), list)]
            if len(names) != 3:
                await message.answer("Сначала сформируй 3 команды через /lineup")
                return
            state.tournament_data = {
                "active": True,
                "teams": {n: {"points": 0, "wins": 0, "draws": 0, "losses": 0, "matches": 0} for n in names},
                "current_pair": [names[0], names[1]],
                "waiting": names[2],
                "streak": {names[0]: 1, names[1]: 1, names[2]: 0},
                "message_id": None,
            }
            save_state(cfg.data_file, state)
        await _render_tour_message()

    @dp.callback_query(F.data.startswith("tour_win:"))
    async def tour_win(cb: types.CallbackQuery):
        if cb.from_user.id != cfg.admin_id:
            await cb.answer("Только админ", show_alert=True)
            return
        winner = cb.data.split(":", 1)[1]
        async with state.lock:
            if not _tour_active():
                await cb.answer("Турнир не запущен", show_alert=True)
                return
            if winner not in state.tournament_data.get("current_pair", []):
                await cb.answer("Победитель должен быть из текущей пары", show_alert=True)
                return
            _apply_result(winner)
            save_state(cfg.data_file, state)
        await _render_tour_message()
        await cb.answer("Результат записан")

    @dp.callback_query(F.data == "tour_draw")
    async def tour_draw(cb: types.CallbackQuery):
        if cb.from_user.id != cfg.admin_id:
            await cb.answer("Только админ", show_alert=True)
            return
        async with state.lock:
            if not _tour_active():
                await cb.answer("Турнир не запущен", show_alert=True)
                return
            _apply_result(None)
            save_state(cfg.data_file, state)
        await _render_tour_message()
        await cb.answer("Ничья записана")

    @dp.message(Command("table"))
    async def table(message: types.Message):
        await message.answer(_tour_text())

    @dp.message(Command("tour_end"))
    async def tour_end(message: types.Message):
        if not admin(message):
            return
        async with state.lock:
            if not _tour_active():
                await message.answer("Турнир не запущен")
                return
            teams = state.tournament_data["teams"]
            avg = sum(v["points"] for v in teams.values()) / max(len(teams), 1)
            rosters = state.last_teams or {}
            for team_name, row in teams.items():
                delta = 0.2 * (row["points"] - avg)
                for player_name in rosters.get(team_name, []):
                    old = state.ratings.get(player_name, 5.0)
                    state.ratings[player_name] = min(10.0, max(1.0, round(old + delta, 2)))
            state.tournament_data["active"] = False
            save_state(cfg.data_file, state)
        await _render_tour_message()
        await message.answer("Турнир завершен, рейтинги обновлены")

    @dp.message(Command("tour_start"))
    async def tour_start(message: types.Message):
        if not admin(message):
            return
        async with state.lock:
            teams = state.last_teams or {}
            names = [n for n in ("красные", "белые", "зеленые") if isinstance(teams.get(n), list)]
            if len(names) != 3:
                await message.answer("Сначала сформируй 3 команды через /lineup")
                return
            state.tournament_data = {
                "active": True,
                "teams": {n: {"points": 0, "wins": 0, "draws": 0, "losses": 0, "matches": 0} for n in names},
                "current_pair": [names[0], names[1]],
                "waiting": names[2],
                "streak": {names[0]: 1, names[1]: 1, names[2]: 0},
                "message_id": None,
            }
            save_state(cfg.data_file, state)
        await _render_tour_message()

    @dp.callback_query(F.data.startswith("tour_win:"))
    async def tour_win(cb: types.CallbackQuery):
        if cb.from_user.id != cfg.admin_id:
            await cb.answer("Только админ", show_alert=True)
            return
        winner = cb.data.split(":", 1)[1]
        async with state.lock:
            if not _tour_active():
                await cb.answer("Турнир не запущен", show_alert=True)
                return
            if winner not in state.tournament_data.get("current_pair", []):
                await cb.answer("Победитель должен быть из текущей пары", show_alert=True)
                return
            _apply_result(winner)
            save_state(cfg.data_file, state)
        await _render_tour_message()
        await cb.answer("Результат записан")

    @dp.callback_query(F.data == "tour_draw")
    async def tour_draw(cb: types.CallbackQuery):
        if cb.from_user.id != cfg.admin_id:
            await cb.answer("Только админ", show_alert=True)
            return
        async with state.lock:
            if not _tour_active():
                await cb.answer("Турнир не запущен", show_alert=True)
                return
            _apply_result(None)
            save_state(cfg.data_file, state)
        await _render_tour_message()
        await cb.answer("Ничья записана")

    @dp.message(Command("table"))
    async def table(message: types.Message):
        await message.answer(_tour_text())

    @dp.message(Command("tour_end"))
    async def tour_end(message: types.Message):
        if not admin(message):
            return
        async with state.lock:
            if not _tour_active():
                await message.answer("Турнир не запущен")
                return
            teams = state.tournament_data["teams"]
            avg = sum(v["points"] for v in teams.values()) / max(len(teams), 1)
            rosters = state.last_teams or {}
            for team_name, row in teams.items():
                delta = 0.2 * (row["points"] - avg)
                for player_name in rosters.get(team_name, []):
                    old = state.ratings.get(player_name, 5.0)
                    state.ratings[player_name] = min(10.0, max(1.0, round(old + delta, 2)))
            state.tournament_data["active"] = False
            save_state(cfg.data_file, state)
        await _render_tour_message()
        await message.answer("Турнир завершен, рейтинги обновлены")

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
