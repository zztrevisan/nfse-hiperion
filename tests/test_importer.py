import unittest
from pathlib import Path

from app.importer import password_from_filename, read_sieg_companies


class ImporterTests(unittest.TestCase):
    def test_reads_sieg_export(self):
        source = Path(__file__).resolve().parents[1] / "Cadastros-31-08-2026.xlsx"
        if not source.is_file():
            self.skipTest("planilha de exemplo não disponível")
        companies = read_sieg_companies(source)
        self.assertGreater(len(companies), 250)
        self.assertTrue(all(len(item["cnpj"]) == 14 for item in companies))

    def test_extracts_password_from_filename(self):
        password, source = password_from_filename(Path("EMPRESA LTDA Senha Abc123.pfx"))
        self.assertEqual(password, "Abc123")
        self.assertEqual(source, "nome do arquivo")

    def test_uses_default_password(self):
        password, source = password_from_filename(Path("EMPRESA LTDA.pfx"))
        self.assertEqual(password, "1234")
        self.assertEqual(source, "padrão 1234")


if __name__ == "__main__":
    unittest.main()
