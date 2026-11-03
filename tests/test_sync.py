import base64
import gzip
import tempfile
import unittest
from pathlib import Path

from app.adn import AdnClient, NoProxyError, decode_xml, parse_event, parse_note
from app.store import Store
from app.sync import Syncer

OWNER = "11222333000181"


def note(number, prest, toma, compet, prest_name="ACME SERVICOS LTDA", toma_name="CLIENTE / TESTE"):
    return f'''<NFSe xmlns="http://www.sped.fazenda.gov.br/nfse"><infNFSe><nNFSe>{number}</nNFSe>
      <DPS><infDPS><dCompet>{compet}</dCompet><dhEmi>2026-01-01T10:00:00-03:00</dhEmi>
      <prest><CNPJ>{prest}</CNPJ><xNome>{prest_name}</xNome></prest>
      <toma><CNPJ>{toma}</CNPJ><xNome>{toma_name}</xNome></toma></infDPS></DPS></infNFSe></NFSe>'''.encode()


EVENT = b'''<evento xmlns="urn:x"><infEvento><chNFSe>KEY1</chNFSe>
  <dhEvento>2026-09-02T10:00:00-03:00</dhEvento><xDesc>Cancelamento de NFS-e</xDesc></infEvento></evento>'''


def item(nsu, xml, kind="NFSE", key=""):
    return {"NSU": nsu, "TipoDocumento": kind, "ChaveAcesso": key,
            "ArquivoXml": base64.b64encode(gzip.compress(xml)).decode()}


class FakeClient(AdnClient):
    """Responde como o ADN: devolve os itens com NSU maior que o pedido, 2 por lote."""
    def __init__(self, items, error=None):
        super().__init__(None, "99999999000191")
        self.items, self.error, self.calls = items, error, []

    def fetch(self, nsu, target):
        self.calls.append(self._url(nsu, target))
        if self.error: raise self.error
        rest = [i for i in self.items if i["NSU"] > nsu][:2]
        return {"StatusProcessamento": "DOCUMENTOS_LOCALIZADOS", "LoteDFe": rest} if rest else None


class ParseTests(unittest.TestCase):
    def test_decode_gzip_base64(self):
        xml = note(1, OWNER, "1", "2026-08-01")
        self.assertEqual(decode_xml(base64.b64encode(gzip.compress(xml)).decode()), xml)

    def test_direction_and_owner_name(self):
        info = parse_note(note(7, OWNER, "52998224725", "2026-08-15"), OWNER)
        self.assertEqual((info.direction, info.date, info.number, info.counterpart, info.owner_name),
                         ("Emitidas", "2026-08-15", "7", "CLIENTE / TESTE", "ACME SERVICOS LTDA"))
        info = parse_note(note(8, "52998224725", OWNER, "2026-08-15", "FORNECEDOR", "ACME"), OWNER)
        self.assertEqual((info.direction, info.counterpart, info.owner_name), ("Recebidas", "FORNECEDOR", "ACME"))

    def test_event(self):
        ev = parse_event(EVENT)
        self.assertEqual((ev.note_key, ev.description, ev.date), ("KEY1", "Cancelamento de NFS-e", "2026-09-02"))


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "out"
        self.store = Store(Path(self.tmp.name) / "t.db")

    def tearDown(self):
        self.store.db.close(); self.tmp.cleanup()

    def test_full_sync_layout_events_and_incremental(self):
        items = [item(1, note(10, OWNER, "52998224725", "2026-08-15"), key="KEY1"),
                 item(2, note(11, "52998224725", OWNER, "2026-09-03", "FORN X", "ACME SERVICOS LTDA")),
                 item(3, EVENT, kind="EVENTO")]
        client = FakeClient(items)
        result = Syncer(client, self.store, self.root).run_one(OWNER)
        self.assertEqual((result.status, result.new_files), ("ok", 3))
        self.assertIn("cnpjConsulta=" + OWNER, client.calls[0])

        base = self.root / f"ACME SERVICOS LTDA - {OWNER}"
        files = sorted(str(p.relative_to(base)).replace("\\", "/") for p in base.rglob("*.xml"))
        self.assertEqual(files, [
            "2026/08/Emitidas/10_CLIENTE TESTE_1.xml",
            "2026/08/Eventos/10_Cancelamento de NFS-e_3.xml",   # evento vai para o mês da nota
            "2026/09/Recebidas/11_FORN X_2.xml",
        ])
        self.assertEqual(self.store.company(OWNER).last_nsu, 3)

        # Segunda rodada: começa do NSU 3 e não encontra nada novo.
        client.items.append(item(4, note(12, OWNER, "52998224725", "2026-10-01"), key="KEY2"))
        again = Syncer(client, self.store, self.root).run_one(OWNER)
        self.assertEqual((again.status, again.new_files), ("ok", 1))
        self.assertTrue(client.calls[-2].startswith("https://adn.nfse.gov.br/contribuintes/DFe/3?"))
        self.assertTrue((base / "2026/10/Emitidas").is_dir())

    def test_competence_filter_keeps_only_period_and_nsu(self):
        items = [item(1, note(10, OWNER, "52998224725", "2026-08-15"), key="KEY1"),
                 item(2, note(11, "52998224725", OWNER, "2026-09-03", "FORN X", "ACME SERVICOS LTDA")),
                 item(3, EVENT, kind="EVENTO"),
                 item(4, note(12, OWNER, "52998224725", "2026-10-01"))]
        self.store.save_company(self.store.company(OWNER).__class__(OWNER, last_nsu=2))
        client = FakeClient(items)
        result = Syncer(client, self.store, self.root).run_one(OWNER, competence=("2026-08", "2026-08"))
        self.assertEqual((result.status, result.new_files), ("ok", 2))
        self.assertTrue(client.calls[0].startswith("https://adn.nfse.gov.br/contribuintes/DFe/0?"))
        base = self.root / f"ACME SERVICOS LTDA - {OWNER}"
        files = sorted(str(p.relative_to(base)).replace("\\", "/") for p in base.rglob("*.xml"))
        self.assertEqual(files, ["2026/08/Emitidas/10_CLIENTE TESTE_1.xml",
                                 "2026/08/Eventos/10_Cancelamento de NFS-e_3.xml"])
        self.assertEqual(self.store.company(OWNER).last_nsu, 2)  # filtro não mexe no incremental

        empty = Syncer(client, self.store, self.root).run_one(OWNER, competence=("2025-01", "2025-12"))
        self.assertEqual(empty.status, "vazio")

    def test_own_certificate_does_not_send_cnpj_consulta(self):
        client = FakeClient([])
        client.owner = OWNER
        result = Syncer(client, self.store, self.root).run_one(OWNER)
        self.assertEqual(result.status, "vazio")
        self.assertNotIn("Consulta", client.calls[0])

    def test_cpf_uses_cpf_consulta(self):
        client = FakeClient([])
        Syncer(client, self.store, self.root).run_one("52998224725")
        self.assertIn("cpfConsulta=52998224725", client.calls[0])

    def test_no_proxy_is_reported_and_keeps_going(self):
        client = FakeClient([], error=NoProxyError("Não há procuração"))
        result = Syncer(client, self.store, self.root).run_one(OWNER)
        self.assertEqual(result.status, "sem_procuracao")


if __name__ == "__main__":
    unittest.main()
