import tempfile
import unittest
from pathlib import Path

from app.folders import business_name_key, child_folder, find_a1_certificate, legal_name_from_folder, locate_company_folder, monthly_folders, normalize
from app.service import safe_filename


class FolderTests(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(normalize("Comércio São João Ltda."), "COMERCIO SAO JOAO LTDA")

    def test_legal_suffix_does_not_break_match(self):
        self.assertEqual(business_name_key("YU SHEN MINIMERCADO LTDA"), business_name_key("YU SHEN MINIMERCADO"))

    def test_locates_fiscal_folder_without_ltda_suffix(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            company = root / "023 - YU SHEN MINIMERCADO"
            company.mkdir()
            self.assertEqual(locate_company_folder(root, "07339957000106", "YU SHEN MINIMERCADO LTDA"), company)

    def test_first_match_creates_cnpj_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            company = root / "023 - Comércio São João Ltda"
            company.mkdir()
            found = locate_company_folder(root, "12.345.678/0001-90", "COMERCIO SAO JOAO LTDA")
            self.assertEqual(found, company)
            self.assertEqual((company / ".nfse-cnpj").read_text(), "12345678000190")

    def test_monthly_structure(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = Path(tmp) / "02. FISCAL" / "ARQUIVOS" / "SERVIÇOS"
            (services / "PRESTADOS" / "PORTAL NACIONAL").mkdir(parents=True)
            (services / "TOMADOS" / "PORTAL NACIONAL").mkdir(parents=True)
            folders = monthly_folders(Path(tmp), 2026, 7)
            self.assertTrue(folders["Emitidas"].is_dir())
            self.assertTrue(folders["Recebidas"].is_dir())
            self.assertEqual(folders["Emitidas"].name, "07.2026")
            self.assertIn("PRESTADOS", folders["Emitidas"].parts)
            self.assertIn("TOMADOS", folders["Recebidas"].parts)

    def test_creates_missing_fiscal_structure(self):
        with tempfile.TemporaryDirectory() as tmp:
            folders = monthly_folders(Path(tmp), 2026, 7, {"Recebidas"})
            self.assertTrue(folders["Recebidas"].is_dir())
            self.assertEqual(
                folders["Recebidas"],
                Path(tmp) / "02. FISCAL" / "ARQUIVOS" / "SERVIÇOS" / "TOMADOS" / "PORTAL NACIONAL" / "07.2026",
            )

    def test_only_selected_direction_is_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            issued = Path(tmp) / "02. FISCAL" / "ARQUIVOS" / "SERVIÇOS" / "PRESTADOS" / "PORTAL NACIONAL"
            issued.mkdir(parents=True)
            folders = monthly_folders(Path(tmp), 2026, 7, {"Emitidas"})
            self.assertEqual(set(folders), {"Emitidas"})
            self.assertTrue((issued / "07.2026").is_dir())

    def test_fiscal_path_tolerates_punctuation_and_accents(self):
        with tempfile.TemporaryDirectory() as tmp:
            portal = Path(tmp) / "02 - Fiscal" / "Arquivos" / "Servicos" / "Prestados" / "Portal  Nacional"
            portal.mkdir(parents=True)
            folders = monthly_folders(Path(tmp), 2026, 8, {"Emitidas"})
            self.assertEqual(folders["Emitidas"], Path(tmp) / "02. FISCAL" / "ARQUIVOS" / "SERVIÇOS" / "PRESTADOS" / "PORTAL NACIONAL" / "08.2026")

    def test_missing_segment_reports_available_folders(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "2. CONTABIL").mkdir()
            with self.assertRaisesRegex(FileNotFoundError, "2. CONTABIL"):
                child_folder(Path(tmp), "02. FISCAL")

    def test_rejects_path_traversal(self):
        with self.assertRaises(ValueError):
            safe_filename("../nota.xml")

    def test_real_folder_layout_discovers_certificate(self):
        with tempfile.TemporaryDirectory() as tmp:
            company = Path(tmp) / "023 - YU SHEN MINIMERCADO LTDA"
            cert_dir = company / "CERTIFICADO DIGITAL"
            cert_dir.mkdir(parents=True)
            cert = cert_dir / "YU SHEN MINIMERCADO LTDA.pfx"
            cert.write_bytes(b"test")
            self.assertEqual(legal_name_from_folder(company), "YU SHEN MINIMERCADO LTDA")
            self.assertEqual(find_a1_certificate(company), cert)


if __name__ == "__main__":
    unittest.main()
