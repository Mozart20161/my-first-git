import tempfile
import unittest
from pathlib import Path

from football_bot.state import BotState
from football_bot.storage import load_state, save_state


class StorageTests(unittest.TestCase):
    def test_save_and_load(self):
        state = BotState()
        state.players = [{"id": 1, "name": "Test", "paid": True, "guest": False}]
        state.bank_total = 123
        state.last_teams = {"красные": ["Test"]}

        with tempfile.TemporaryDirectory() as td:
            path = str(Path(td) / 'data.json')
            save_state(path, state)

            loaded = BotState()
            load_state(path, loaded)
            self.assertEqual(loaded.bank_total, 123)
            self.assertEqual(len(loaded.players), 1)
            self.assertEqual(loaded.last_teams, {"красные": ["Test"]})


if __name__ == '__main__':
    unittest.main()
