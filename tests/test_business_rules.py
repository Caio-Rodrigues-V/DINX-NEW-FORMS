import unittest

from business_rules import (
    children_count_for_tier,
    map_age_tier,
    map_school_type,
    no_children_selected,
    normalize_choice,
    terminal_business_error,
)


class BusinessRulesTest(unittest.TestCase):
    def test_normalizes_meta_labels(self):
        self.assertEqual(normalize_choice("Não tenho filho(a)"), "nao_tenho_filho_a")
        self.assertEqual(normalize_choice("De 3 a 6 anos"), "de_3_a_6_anos")

    def test_maps_eligible_age_answers(self):
        self.assertEqual(map_age_tier("De 3 a 6 anos"), "between3and6")
        self.assertEqual(map_age_tier("De 7 a 12 anos"), "between7and12")
        self.assertEqual(map_age_tier("Ambas as idades"), "both")

    def test_filters_no_children_from_either_question(self):
        self.assertTrue(no_children_selected("Não tenho filho(a)"))
        self.assertTrue(no_children_selected("De 3 a 6 anos", "Não tenho filho(a)"))
        self.assertFalse(no_children_selected("De 3 a 6 anos", "Escola particular"))

    def test_maps_school_answers_without_dangerous_default(self):
        self.assertEqual(map_school_type("Escola pública"), 1)
        self.assertEqual(map_school_type("Escola particular"), 2)
        self.assertIsNone(map_school_type("Resposta desconhecida"))

    def test_derives_children_count_from_age_tier(self):
        self.assertEqual(children_count_for_tier("between3and6"), 1)
        self.assertEqual(children_count_for_tier("between7and12"), 1)
        self.assertEqual(children_count_for_tier("both"), 2)
        self.assertEqual(children_count_for_tier(None), 0)

    def test_identifies_terminal_dinx_business_errors(self):
        self.assertTrue(terminal_business_error("Este e-mail já possui uma solicitação expirada."))
        self.assertTrue(terminal_business_error("Este e-mail já possui acesso ativo ao aplicativo."))
        self.assertFalse(terminal_business_error("Erro temporário ao validar perfil"))


if __name__ == "__main__":
    unittest.main()
