import base64
import gzip
import unittest

from app.providers.adn import decode_xml, parse_event, parse_note


XML = b'''<?xml version="1.0" encoding="UTF-8"?>
<NFSe xmlns="urn:test">
  <infNFSe><nNFSe>123</nNFSe><dCompet>2026-07-15</dCompet>
    <prest><CNPJ>07339957000106</CNPJ><xNome>YU SHEN</xNome></prest>
    <toma><CNPJ>11222333000144</CNPJ><xNome>CLIENTE TESTE</xNome></toma>
  </infNFSe>
</NFSe>'''

EVENT_XML = b'''<evento xmlns="urn:test"><infEvento>
  <chNFSe>12345678901234567890123456789012345678901234</chNFSe>
  <dhEvento>2026-07-20T10:00:00-03:00</dhEvento>
  <xDesc>Cancelamento de NFS-e</xDesc><xMotivo>Erro na emissao</xMotivo>
</infEvento></evento>'''


class AdnParsingTests(unittest.TestCase):
    def test_decodes_gzip_base64(self):
        encoded = base64.b64encode(gzip.compress(XML)).decode()
        self.assertEqual(decode_xml(encoded), XML)

    def test_classifies_issued_by_owner_cnpj(self):
        direction, competence, number, counterpart = parse_note(XML, "07339957000106")
        self.assertEqual(direction, "Emitidas")
        self.assertEqual(competence, "2026-07")
        self.assertEqual(number, "123")
        self.assertEqual(counterpart, "CLIENTE TESTE")

    def test_classifies_received_by_owner_cnpj(self):
        direction, _, _, counterpart = parse_note(XML, "11222333000144")
        self.assertEqual(direction, "Recebidas")
        self.assertEqual(counterpart, "YU SHEN")

    def test_parses_event_description_and_reference(self):
        key, description, reason, month = parse_event(EVENT_XML)
        self.assertEqual(key, "12345678901234567890123456789012345678901234")
        self.assertEqual(description, "Cancelamento de NFS-e")
        self.assertEqual(reason, "Erro na emissao")
        self.assertEqual(month, "2026-07")


if __name__ == "__main__":
    unittest.main()
