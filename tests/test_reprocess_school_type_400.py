import unittest

from reprocess_school_type_400 import is_school_type_decode_400


class ReprocessSchoolType400Test(unittest.TestCase):
    def test_accepts_exact_temporary_api_failure(self):
        record = {
            "status": 400,
            "response": (
                "cannot decode field "
                "site.beta_access.v1.RequestBetaAccessRequest.school_type "
                "from JSON: 1"
            ),
        }

        self.assertTrue(is_school_type_decode_400(record))

    def test_accepts_error_stored_in_reasons(self):
        record = {
            "status": "400",
            "response": "",
            "reasons": [
                {
                    "message": (
                        "cannot decode field RequestBetaAccessRequest.school_type "
                        "from JSON: 2"
                    )
                }
            ],
        }

        self.assertTrue(is_school_type_decode_400(record))

    def test_rejects_other_400_errors(self):
        self.assertFalse(
            is_school_type_decode_400(
                {"status": 400, "response": "Erro na validacao dos dados"}
            )
        )

    def test_rejects_same_message_with_non_400_status(self):
        self.assertFalse(
            is_school_type_decode_400(
                {
                    "status": "business_error",
                    "response": (
                        "cannot decode field RequestBetaAccessRequest.school_type "
                        "from JSON: 1"
                    ),
                }
            )
        )


if __name__ == "__main__":
    unittest.main()
