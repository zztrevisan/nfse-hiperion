import unittest

from app.documents import fmt, parse_list, valid_cnpj, valid_cpf


class DocumentTests(unittest.TestCase):
    def test_valid_numeric_cnpj(self):
        self.assertTrue(valid_cnpj("11.222.333/0001-81"))
        self.assertFalse(valid_cnpj("11.222.333/0001-82"))
        self.assertFalse(valid_cnpj("00000000000000"))

    def test_valid_alphanumeric_cnpj(self):
        # Exemplo oficial da Receita para o CNPJ alfanumérico.
        self.assertTrue(valid_cnpj("12.ABC.345/01DE-35"))
        self.assertFalse(valid_cnpj("12.ABC.345/01DE-36"))

    def test_valid_cpf(self):
        self.assertTrue(valid_cpf("529.982.247-25"))
        self.assertFalse(valid_cpf("529.982.247-24"))

    def test_parse_messy_text(self):
        text = """EMPRESA A;11.222.333/0001-81
        11222333000181  (repetido)
        cliente b - 12abc34501de35
        52998224725 pessoa física
        99.999.999/9999-99 errado"""
        docs, invalid = parse_list(text)
        self.assertEqual(docs, ["11222333000181", "12ABC34501DE35", "52998224725"])
        self.assertEqual(invalid, ["99999999999999"])

    def test_format(self):
        self.assertEqual(fmt("11222333000181"), "11.222.333/0001-81")
        self.assertEqual(fmt("52998224725"), "529.982.247-25")


if __name__ == "__main__":
    unittest.main()
