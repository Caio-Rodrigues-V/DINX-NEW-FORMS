import json
import unittest

from redis_batch import load_json_details


class FakeRedisClient:
    def __init__(self, values):
        self.values = values
        self.mget_calls = []

    def mget(self, keys):
        self.mget_calls.append(keys)
        return [self.values.get(key) for key in keys]


class RedisBatchTest(unittest.TestCase):
    def test_loads_many_records_with_one_mget_per_batch(self):
        values = {
            f"detail:{lead_id}": json.dumps({"lead_id": lead_id})
            for lead_id in ("1", "2", "3")
        }
        client = FakeRedisClient(values)

        details, invalid_ids = load_json_details(
            client,
            ["1", "2", "3"],
            "detail:",
            batch_size=2,
        )

        self.assertEqual(set(details), {"1", "2", "3"})
        self.assertEqual(invalid_ids, [])
        self.assertEqual(len(client.mget_calls), 2)
        self.assertEqual(client.mget_calls[0], ["detail:1", "detail:2"])

    def test_skips_missing_and_malformed_details(self):
        client = FakeRedisClient(
            {
                "detail:valid": json.dumps({"lead_id": "valid"}),
                "detail:broken": "not-json",
            }
        )

        details, invalid_ids = load_json_details(
            client,
            ["valid", "missing", "broken"],
            "detail:",
        )

        self.assertEqual(details, {"valid": {"lead_id": "valid"}})
        self.assertEqual(invalid_ids, ["broken"])


if __name__ == "__main__":
    unittest.main()
