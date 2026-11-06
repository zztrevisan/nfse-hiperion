import tempfile
import unittest
from pathlib import Path

from openpyxl import load_workbook

from app import report

OWNER = "11222333000181"


def note(key, number, prest, toma, compet, value, iss="0.00", ret="1"):
    return f'''<NFSe xmlns="http://www.sped.fazenda.gov.br/nfse"><infNFSe Id="NFS{key}"><nNFSe>{number}</nNFSe>
      <valores><vISSQN>{iss}</vISSQN><vLiq>{value}</vLiq></valores>
      <DPS><infDPS><dCompet>{compet}</dCompet>
      <prest><CNPJ>{prest}</CNPJ><xNome>PREST</xNome></prest>
      <toma><CNPJ>{toma}</CNPJ><xNome>TOMA</xNome></toma>
      <serv/><valores><vServPrest><vServ>{value}</vServ></vServPrest>
      <trib><tribMun><tpRetISSQN>{ret}</tpRetISSQN></tribMun></trib></valores></infDPS></DPS></infNFSe></NFSe>'''


CANCEL = '''<evento xmlns="http://www.sped.fazenda.gov.br/nfse"><infEvento><pedRegEvento><infPedReg>
  <chNFSe>K3</chNFSe><e101101><xDesc>Cancelamento de NFS-e</xDesc></e101101></infPedReg></pedRegEvento></infEvento></evento>'''


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        base = self.root / f"ACME LTDA - {OWNER}"
        files = {
            "2026/08/Emitidas/1.xml": note("K1", 1, OWNER, "52998224725", "2026-08-10", "1000.00", "50.00"),
            "2026/08/Emitidas/2.xml": note("K2", 2, OWNER, "52998224725", "2026-08-11", "500.50", "25.03"),
            "2026/08/Emitidas/3.xml": note("K3", 3, OWNER, "52998224725", "2026-08-12", "9999.00"),
            "2026/08/Eventos/3_Cancelamento.xml": CANCEL,
            "2026/08/Recebidas/9.xml": note("K9", 9, "99888777000166", OWNER, "2026-08-05", "300.00", "15.00", "2"),
            "2026/09/Emitidas/4.xml": note("K4", 4, OWNER, "52998224725", "2026-09-01", "200.00"),
        }
        for rel, xml in files.items():
            (base / rel).parent.mkdir(parents=True, exist_ok=True)
            (base / rel).write_text(xml, encoding="utf-8")
        (self.root / "outra pasta qualquer").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_summary_excludes_cancelled(self):
        rows = report.collect(self.root, "2026-08", "2026-08")
        self.assertEqual(len(rows), 4)
        s = report.summarize(rows)[("ACME LTDA", OWNER, "2026-08")]
        self.assertEqual((s.out_count, round(s.out_value, 2), round(s.out_iss, 2)), (2, 1500.50, 75.03))
        self.assertEqual((s.in_count, s.in_value, s.in_iss_withheld, s.cancelled), (1, 300.0, 15.0, 1))
        self.assertEqual(next(r for r in rows if r.number == "3").status, "Cancelada/Substituída")

    def test_period_and_company_filter(self):
        self.assertEqual(len(report.collect(self.root, "2026-08", "2026-09")), 5)
        self.assertEqual(report.collect(self.root, "2026-08", "2026-09", {"52998224725"}), [])

    def test_xlsx(self):
        path = self.root / "r.xlsx"
        report.write_xlsx(path, report.collect(self.root, "2026-08", "2026-09"), "2026-08", "2026-09")
        wb = load_workbook(path)
        self.assertEqual(wb.sheetnames, ["Resumo", "Notas"])
        resumo = list(wb["Resumo"].values)
        self.assertEqual(resumo[1][:5], ("ACME LTDA", OWNER, "2026-08", 2, 1500.5))
        self.assertEqual(resumo[2][2:5], ("2026-09", 1, 200.0))
        self.assertEqual(resumo[3][0], "TOTAL")
        self.assertEqual(wb["Notas"].max_row, 6)


if __name__ == "__main__":
    unittest.main()
