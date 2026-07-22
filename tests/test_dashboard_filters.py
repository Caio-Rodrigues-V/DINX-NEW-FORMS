from datetime import date
import unittest

from dashboard_metrics import calculate_stats, filter_records_by_date, resolve_date_filter


class DashboardFiltersTest(unittest.TestCase):
    def test_defaults_to_today_and_accepts_all_period(self):
        selected, value, label = resolve_date_filter("", today=date(2026, 7, 21))
        self.assertEqual(selected, date(2026, 7, 21))
        self.assertEqual(value, "2026-07-21")
        self.assertEqual(label, "Hoje")

        selected, value, label = resolve_date_filter("all", today=date(2026, 7, 21))
        self.assertIsNone(selected)
        self.assertEqual(value, "all")
        self.assertEqual(label, "Todo o periodo")

    def test_uses_brasilia_day_when_record_was_saved_in_utc(self):
        records = [
            {"lead_id": "before-midnight", "created_at": "2026-07-21T02:59:59+0000"},
            {"lead_id": "after-midnight", "created_at": "2026-07-21T03:00:00+0000"},
        ]

        filtered = filter_records_by_date(records, date(2026, 7, 21))

        self.assertEqual([record["lead_id"] for record in filtered], ["after-midnight"])

    def test_calculates_approved_and_qualified_totals(self):
        sent_records = [
            {"lead_id": "1", "decision": "approved"},
            {"lead_id": "2", "decision": "pending"},
            {"lead_id": "3", "decision": "accepted"},
        ]
        rejected_records = [{"lead_id": "4"}, {"lead_id": "5"}]

        stats = calculate_stats(
            sent_records,
            rejected_records,
            {"5"},
            [{"lead_id": "6"}],
            total_sent=257,
        )

        self.assertEqual(
            stats,
            {
                "total_sent": 257,
                "sent": 3,
                "approved": 1,
                "qualified": 1,
                "rejected": 2,
                "invalid": 1,
                "filtered": 1,
            },
        )


if __name__ == "__main__":
    unittest.main()
