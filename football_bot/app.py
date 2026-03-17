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
from .utils import (
    balance_two_teams,
    clamp_rating,
    format_lineups,
    get_three_team_rating_deltas,
    get_two_team_rating_delta,
    parse_float_arg,
    parse_int_arg,
    validate_date,
    validate_time,
)


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

    def _rating_key(player_id: int) -> str:
        return f"id:{player_id}"

    def _get_rating(player: dict) -> float:
        player_id = player.get("id")
        name = player.get("name")
        if isinstance(player_id, int):
            keys = (_rating_key(player_id), str(player_id))
            for key in keys:
                value = state.ratings.get(key)
                if isinstance(value, (int, float)):
                    return float(value)
            if isinstance(name, str):
                legacy = state.ratings.get(name)
                if isinstance(legacy, (int, float)):
                    state.ratings[_rating_key(player_id)] = float(legacy)
                    return float(legacy)
        return float(state.ratings.get(name, 5.0)) if isinstance(name, str) else 5.0

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
        if not isinstance(tour, dict):
            return
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
            save_state(cfg.data_file, state)

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
            guest = next(
                (
                    p
                    for p in state.players
                    if p.get("guest") and isinstance(p.get("id"), int) and p["id"] < 0 and p["name"].lower() == cb.from_user.full_name.lower()
                ),
                None,
            )
            if guest:
                old_guest_id = guest["id"]
                guest["id"] = cb.from_user.id
                guest["guest"] = False
                guest["name"] = cb.from_user.full_name
                old_key = _rating_key(old_guest_id)
                new_key = _rating_key(cb.from_user.id)
                if old_key in state.ratings and new_key not in state.ratings:
                    state.ratings[new_key] = float(state.ratings[old_key])
            if len(state.players) >= state.match_data["limit"]:
                await cb.answer("Лимит игроков уже достигнут", show_alert=True)
                return
            if not guest:
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
                "/addplayer <имя> — добавить игрока вручную",
                "/removeplayer <имя|номер> — удалить игрока вручную",
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
            rating = _get_rating(p)
            text.append(f"{i}. {p['name']} | рейтинг: {rating:.1f} | оплата: {paid}")
        await message.answer("\n".join(text))

    @dp.message(Command("addplayer"))
    async def addplayer(message: types.Message):
        if not admin(message):
            return
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            await message.answer("Использование: /addplayer <имя>")
            return
        name = parts[1].strip()
        async with state.lock:
            if len(state.players) >= state.match_data["limit"]:
                await message.answer("Лимит игроков уже достигнут")
                return
            if any(p["name"].lower() == name.lower() for p in state.players):
                await message.answer("Игрок с таким именем уже в списке")
                return
            guest_id = -1
            existing_ids = {p["id"] for p in state.players if isinstance(p.get("id"), int)}
            while guest_id in existing_ids:
                guest_id -= 1
            state.players.append({"id": guest_id, "name": name, "paid": False, "guest": True})
            save_state(cfg.data_file, state)
        await refresh_message()
        await message.answer("Игрок добавлен")

    @dp.message(Command("removeplayer"))
    async def removeplayer(message: types.Message):
        if not admin(message):
            return
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            await message.answer("Использование: /removeplayer <имя|номер>")
            return
        target = parts[1].strip()
        removed = False
        async with state.lock:
            if target.isdigit():
                idx = int(target)
                if 1 <= idx <= len(state.players):
                    state.players.pop(idx - 1)
                    removed = True
            else:
                before = len(state.players)
                state.players = [p for p in state.players if p["name"].lower() != target.lower()]
                removed = len(state.players) != before
            if removed:
                save_state(cfg.data_file, state)
        if removed:
            await refresh_message()
            await message.answer("Игрок удален")
        else:
            await message.answer("Игрок не найден")

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
            player = next((p for p in state.players if p["name"].lower() == name.lower()), None)
            if player and isinstance(player.get("id"), int):
                state.ratings[_rating_key(player["id"])] = value
            else:
                state.ratings[name] = value
            save_state(cfg.data_file, state)
        await message.answer("OK")

    @dp.message(Command("result"))
    async def result_cmd(message: types.Message):
        if not admin(message):
            return
        if not state.last_teams or set(state.last_teams.keys()) != {"красные", "белые"}:
            await message.answer("Команда работает только для формата из 2 команд после /lineup")
            return

        parts = (message.text or "").split(maxsplit=1)
        if len(parts) < 2 or ":" not in parts[1]:
            await message.answer("Использование: /result <счет_красные:счет_белые>")
            return
        try:
            red_raw, white_raw = parts[1].split(":", maxsplit=1)
            red_score, white_score = int(red_raw.strip()), int(white_raw.strip())
        except ValueError:
            await message.answer("Счет должен быть целым, пример: /result 7:5")
            return

        diff = abs(red_score - white_score)
        delta = get_two_team_rating_delta(diff)
        if red_score == white_score:
            await message.answer("Ничья: рейтинги не изменены")
            return

        winner, loser = ("красные", "белые") if red_score > white_score else ("белые", "красные")

        async with state.lock:
            for player in state.last_teams[winner]:
                old = state.ratings.get(player, 5.0)
                state.ratings[player] = round(clamp_rating(old + delta), 2)
            for player in state.last_teams[loser]:
                old = state.ratings.get(player, 5.0)
                state.ratings[player] = round(clamp_rating(old - delta), 2)

            history = state.tournament_data.setdefault("rating_history", [])
            history.append({
                "mode": "2teams",
                "score": f"{red_score}:{white_score}",
                "winner": winner,
                "delta": delta,
            })
            save_state(cfg.data_file, state)

        await message.answer(f"Рейтинги обновлены. Победили {winner}, изменение: ±{delta}")

    @dp.message(Command("tournament"))
    async def tournament_cmd(message: types.Message):
        if not admin(message):
            return
        if not state.last_teams or set(state.last_teams.keys()) != {"красные", "белые", "зеленые"}:
            await message.answer("Команда работает только для формата из 3 команд после /lineup")
            return

        parts = (message.text or "").split()
        if len(parts) != 4:
            await message.answer("Использование: /tournament <очки_красные> <очки_белые> <очки_зеленые>")
            return
        try:
            red_points, white_points, green_points = int(parts[1]), int(parts[2]), int(parts[3])
        except ValueError:
            await message.answer("Очки должны быть целыми числами")
            return

        points = {"красные": red_points, "белые": white_points, "зеленые": green_points}
        deltas = get_three_team_rating_deltas(points)

        async with state.lock:
            for team_name, players in state.last_teams.items():
                team_delta = deltas.get(team_name, 0.0)
                for player in players:
                    old = state.ratings.get(player, 5.0)
                    state.ratings[player] = round(clamp_rating(old + team_delta), 2)

            history = state.tournament_data.setdefault("rating_history", [])
            history.append({
                "mode": "3teams",
                "points": points,
                "deltas": deltas,
            })
            save_state(cfg.data_file, state)

        changes_text = ", ".join(f"{team}: {delta:+.2f}" for team, delta in deltas.items())
        await message.answer(f"Турнирные рейтинги обновлены ({changes_text})")

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
        if not admin(message):
            return
        total = len(state.players)
        if total < 8:
            await message.answer("Недостаточно игроков")
            return
        sorted_players = sorted(state.players, key=_get_rating, reverse=True)
        names = [p["name"] for p in sorted_players]
        if total >= cfg.min_for_three_teams:
            sizes = (5, 5, 4) if total == 14 else (5, 5, 5)
            teams = [[] for _ in range(3)]
            sums = [0.0, 0.0, 0.0]
            for player in sorted_players:
                available = [i for i in range(3) if len(teams[i]) < sizes[i]]
                target = min(available, key=lambda i: sums[i])
                teams[target].append(player["name"])
                sums[target] += _get_rating(player)
            state.last_teams = {"красные": teams[0], "белые": teams[1], "зеленые": teams[2]}
        else:
            pinned = state.tournament_data.get("pinned_teams") if isinstance(state.tournament_data.get("pinned_teams"), dict) else None
            state.last_teams = balance_two_teams(names, state.ratings, pinned)
        async with state.lock:
            save_state(cfg.data_file, state)
        lineup_text = format_lineups(state.last_teams, state.ratings)
        await safe_send(cfg.chat_id, f"Составы готовы\n\n{lineup_text}", message_thread_id=cfg.thread_teams)

    @dp.message(Command(commands=["tourstart", "tour_start"]))
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
                "roster_snapshot": {name: list(teams.get(name, [])) for name in names},
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

    @dp.message(Command(commands=["tourend", "tour_end"]))
    async def tour_end(message: types.Message):
        if not admin(message):
            return
        async with state.lock:
            if not _tour_active():
                await message.answer("Турнир не запущен")
                return
            teams = state.tournament_data["teams"]
            avg = sum(v["points"] for v in teams.values()) / max(len(teams), 1)
            rosters = state.tournament_data.get("roster_snapshot") if isinstance(state.tournament_data.get("roster_snapshot"), dict) else {}
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
                "team_player_ids": {
                    team_name: [p["id"] for p in state.players if p["name"] in teams.get(team_name, []) and isinstance(p.get("id"), int)]
                    for team_name in names
                },
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
            team_player_ids = state.tournament_data.get("team_player_ids", {})
            for team_name, row in teams.items():
                delta = 0.2 * (row["points"] - avg)
                for player_id in team_player_ids.get(team_name, []):
                    if not isinstance(player_id, int):
                        continue
                    key = _rating_key(player_id)
                    player = next((p for p in state.players if p.get("id") == player_id), None)
                    old = _get_rating(player) if player else float(state.ratings.get(key, 5.0))
                    state.ratings[key] = min(10.0, max(1.0, round(old + delta, 2)))
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
