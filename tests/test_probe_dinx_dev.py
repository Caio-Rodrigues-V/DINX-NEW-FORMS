import unittest

from probe_dinx_dev import ensure_dev_url, interpret_response


class ProbeDinxDevTest(unittest.TestCase):
    def test_blocks_non_dev_hosts(self):
        with self.assertRaises(ValueError):
            ensure_dev_url("https://bff.prd.dinx.app/service")
        with self.assertRaises(ValueError):
            ensure_dev_url("http://bff.dev.dinx.app/service")

    def test_interprets_approved_and_pending(self):
        self.assertEqual(
            interpret_response(200, {"success": True, "approved": True})["automation_result"],
            "approved",
        )
        self.assertEqual(
            interpret_response(200, {"success": True, "approved": False})["automation_result"],
            "pending",
        )

    def test_interprets_business_error(self):
        result = interpret_response(200, {"success": False, "approved": False, "error": "Duplicado"})
        self.assertTrue(result["communication_ok"])
        self.assertEqual(result["automation_result"], "business_error")
        self.assertEqual(result["detail"], "Duplicado")

    def test_rejects_invalid_schema(self):
        self.assertFalse(interpret_response(200, {})["communication_ok"])
        self.assertFalse(interpret_response(500, {})["communication_ok"])

    def test_identifies_dev_authentication_error(self):
        result = interpret_response(401, {"code": "unauthenticated"})
        self.assertFalse(result["communication_ok"])
        self.assertEqual(result["automation_result"], "authentication_error")


if __name__ == "__main__":
    unittest.main()
