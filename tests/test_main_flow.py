import json
import sys
import types
import unittest
from unittest.mock import Mock, patch


class FakeRedisClient:
    def __init__(self):
        self.sets = {}
        self.values = {}

    def sadd(self, key, value):
        self.sets.setdefault(key, set()).add(value)

    def sismember(self, key, value):
        return value in self.sets.get(key, set())

    def set(self, key, value):
        self.values[key] = value


fake_redis_client = FakeRedisClient()
fake_redis = types.ModuleType("redis")
fake_redis.RedisError = RuntimeError
fake_redis.from_url = lambda *args, **kwargs: fake_redis_client
sys.modules.setdefault("redis", fake_redis)

fake_schedule = types.ModuleType("schedule")
fake_schedule.every = Mock()
fake_schedule.run_pending = Mock()
sys.modules.setdefault("schedule", fake_schedule)

fake_dotenv = types.ModuleType("dotenv")
fake_dotenv.load_dotenv = lambda: None
sys.modules.setdefault("dotenv", fake_dotenv)

import main


def raw_lead(age, school):
    return {
        "id": "lead-1",
        "field_data": [
            {"name": "full_name", "values": ["Ana Silva"]},
            {"name": "email", "values": ["ana@example.com"]},
            {"name": "phone_number", "values": ["+5511999999999"]},
            {"name": main.AGE_FIELD, "values": [age]},
            {"name": main.SCHOOL_FIELD, "values": [school]},
        ],
    }


class MainFlowTest(unittest.TestCase):
    def test_builds_documented_payload_for_private_school(self):
        payload = main.parse_lead(raw_lead("De 3 a 6 anos", "Escola particular"))

        self.assertEqual(payload["children_between_age_tier"], "between3and6")
        self.assertEqual(payload["children_count"], 1)
        self.assertEqual(payload["school_type"], 2)
        self.assertEqual(payload["income_range"], "notInformed")
        self.assertEqual(payload["origin"], 1)

    @patch("main.send_to_dinx")
    @patch("main.save_filtered_lead")
    @patch("main.is_invalid", return_value=False)
    @patch("main.is_filtered", return_value=False)
    @patch("main.is_seen", return_value=False)
    def test_no_children_is_filtered_without_dinx_call(
        self,
        _is_seen,
        _is_filtered,
        _is_invalid,
        save_filtered,
        send_to_dinx,
    ):
        result = main.process_raw_lead(raw_lead("Não tenho filho(a)", ""))

        self.assertFalse(result)
        save_filtered.assert_called_once()
        send_to_dinx.assert_not_called()

    def test_reads_top_level_business_error_for_dashboard(self):
        reasons = main.extract_rejection_reason(
            json.dumps({"success": False, "error": "Este e-mail já possui uma solicitação expirada."})
        )

        self.assertEqual(reasons[0]["message"], "Este e-mail já possui uma solicitação expirada.")

    @patch("main.mark_invalid")
    @patch("main.save_rejected_lead")
    @patch("main.requests.post")
    def test_terminal_business_error_is_not_retried(self, post, _save_rejected, mark_invalid):
        response = Mock(status_code=200, text=json.dumps({
            "success": False,
            "approved": False,
            "error": "Este e-mail já possui uma solicitação expirada.",
        }))
        response.json.return_value = json.loads(response.text)
        post.return_value = response

        result = main.send_to_dinx(
            main.parse_lead(raw_lead("De 7 a 12 anos", "Escola pública")),
            "lead-1",
        )

        self.assertFalse(result)
        mark_invalid.assert_called_once_with("lead-1")


if __name__ == "__main__":
    unittest.main()
