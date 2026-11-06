"""Cliente da API de distribuição de DF-e do ADN (NFS-e Nacional) com mTLS.

GET /contribuintes/DFe/{NSU}?lote=true[&cnpjConsulta=X | &cpfConsulta=X]
devolve os documentos com NSU maior que o informado. Com cnpjConsulta, o certificado
conectado consulta outra inscrição — vale para procuração eletrônica no e-CAC
(contador → cliente) e para matriz → filial.
"""
import base64
import gzip
import json
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterator
from dataclasses import dataclass

ADN_BASE = "https://adn.nfse.gov.br/contribuintes/DFe"
TRANSIENT = {429, 500, 502, 503, 504}


class AdnError(RuntimeError):
    pass


class NoProxyError(AdnError):
    """A empresa não deu procuração ao titular do certificado."""


@dataclass
class Document:
    nsu: int
    kind: str          # "NFSE" ou "EVENTO"
    access_key: str
    xml: bytes


def decode_xml(encoded: str) -> bytes:
    raw = base64.b64decode(encoded)
    try:
        return gzip.decompress(raw)
    except (gzip.BadGzipFile, OSError):
        return raw


def _error_text(status: int, body: str) -> str:
    detail = ""
    try:
        payload = json.loads(body)
        errors = payload.get("Erros") or payload.get("erros") or []
        detail = "; ".join(str(e.get("Descricao") or e.get("descricao") or "") for e in errors).strip("; ")
        detail = detail or str(payload.get("Mensagem") or payload.get("message") or "")
    except Exception:
        if body and not body.lstrip().startswith("<"):
            detail = body[:300]
    return f"ADN HTTP {status}" + (f" — {detail}" if detail else "")


class AdnClient:
    delay = 0.7          # intervalo mínimo entre requisições (o ADN devolve 429 se apertar)
    max_batches = 5000   # trava contra loop infinito

    def __init__(self, context: ssl.SSLContext, owner_document: str = ""):
        self.context, self.owner = context, owner_document
        self._last = 0.0

    def _url(self, nsu: int, target: str) -> str:
        url = f"{ADN_BASE}/{nsu}?lote=true"
        if target and target != self.owner:
            param = "cpfConsulta" if len(target) == 11 else "cnpjConsulta"
            url += f"&{param}={urllib.parse.quote(target)}"
        return url

    def fetch(self, nsu: int, target: str) -> dict | None:
        """Um lote a partir do NSU. None = não há nada depois desse NSU (HTTP 404)."""
        url, last_error = self._url(nsu, target), ""
        for attempt in range(5):
            wait = self.delay - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            request = urllib.request.Request(url, headers={
                "Accept": "application/json", "Cache-Control": "no-cache", "User-Agent": "NFSe-Hiperion/2.0"})
            try:
                with urllib.request.urlopen(request, context=self.context, timeout=60) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                last_error = _error_text(exc.code, body)
                # Decide só pela descrição do erro: o corpo do 404 de "fim da caixa" também
                # tem campos com "procura…" e não significa falta de procuração.
                if "procura" in last_error.lower():
                    raise NoProxyError(last_error) from exc
                if exc.code == 404:
                    return None
                if exc.code not in TRANSIENT:
                    raise AdnError(last_error) from exc
                retry = exc.headers.get("Retry-After", "")
                time.sleep(min(30, int(retry) if retry.isdigit() else 2 ** (attempt + 1)))
            except (urllib.error.URLError, TimeoutError, ssl.SSLError) as exc:
                last_error = f"falha de conexão com o ADN: {getattr(exc, 'reason', exc)}"
                time.sleep(2 ** (attempt + 1))
            except json.JSONDecodeError as exc:
                raise AdnError("o ADN respondeu algo que não é JSON") from exc
            finally:
                self._last = time.monotonic()
        raise AdnError(last_error or "ADN indisponível após cinco tentativas")

    def batches(self, target: str, after_nsu: int,
                cancelled: Callable[[], bool] = lambda: False) -> Iterator[tuple[int, list[Document]]]:
        """Percorre a caixa da inscrição a partir de after_nsu.

        Gera (maior NSU do lote, documentos) — quem consome grava os arquivos e só
        então salva o NSU, assim uma queda no meio não pula nada.
        """
        nsu = after_nsu
        for _ in range(self.max_batches):
            if cancelled():
                return
            payload = self.fetch(nsu, target)
            if payload is None:
                return
            batch = payload.get("LoteDFe") or []
            if payload.get("StatusProcessamento") == "NENHUM_DOCUMENTO_LOCALIZADO" or not batch:
                return
            docs, highest = [], nsu
            for item in batch:
                item_nsu = int(item.get("NSU") or 0)
                highest = max(highest, item_nsu)
                if item.get("ArquivoXml"):
                    docs.append(Document(item_nsu, str(item.get("TipoDocumento") or "NFSE").upper(),
                                         re.sub(r"\W", "", str(item.get("ChaveAcesso") or "")),
                                         decode_xml(item["ArquivoXml"])))
            if highest <= nsu:
                raise AdnError(f"o ADN não avançou depois do NSU {nsu}")
            yield highest, docs
            nsu = highest
        raise AdnError(f"limite de {self.max_batches} lotes atingido no NSU {nsu}")


# ── Leitura dos XML ──────────────────────────────────────────────────────────

def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _find(parent: ET.Element | None, *names: str) -> str:
    if parent is None:
        return ""
    wanted = set(names)
    for node in parent.iter():
        if _local(node.tag) in wanted and node.text and node.text.strip():
            return node.text.strip()
    return ""


def _block(root: ET.Element, *names: str) -> ET.Element | None:
    wanted = set(names)
    return next((n for n in root.iter() if _local(n.tag) in wanted), None)


@dataclass
class NoteInfo:
    direction: str     # Emitidas | Recebidas | Outros
    date: str          # AAAA-MM-DD usada para a pasta (competência; se faltar, emissão)
    number: str
    counterpart: str   # nome do outro lado da nota
    owner_name: str    # razão social da empresa consultada, como aparece na nota


def parse_note(xml: bytes, owner: str) -> NoteInfo:
    root = ET.fromstring(xml)
    prest = _block(root, "emit", "prest")
    toma = _block(root, "toma", "tomador")
    prest_doc = re.sub(r"\W", "", _find(prest, "CNPJ", "CPF")).upper()
    toma_doc = re.sub(r"\W", "", _find(toma, "CNPJ", "CPF")).upper()
    prest_name = _find(prest, "xNome", "xRazSoc", "xFant")
    toma_name = _find(toma, "xNome", "xRazSoc")
    if prest_doc == owner:
        direction, counterpart, owner_name = "Emitidas", toma_name, prest_name
    elif toma_doc == owner:
        direction, counterpart, owner_name = "Recebidas", prest_name, toma_name
    else:  # intermediário ou CNPJ diferente (ex.: nota da filial caiu na matriz)
        direction, counterpart, owner_name = "Outros", prest_name, ""
    date = _find(root, "dCompet")[:10] or _find(root, "dhEmi", "dhProc")[:10]
    return NoteInfo(direction, date, _find(root, "nNFSe", "nDPS"), counterpart, owner_name)


@dataclass
class EventInfo:
    note_key: str
    description: str
    date: str


def parse_event(xml: bytes) -> EventInfo:
    root = ET.fromstring(xml)
    return EventInfo(re.sub(r"\W", "", _find(root, "chNFSe")),
                     _find(root, "xDesc") or "Evento",
                     _find(root, "dhEvento", "dhProc")[:10])
