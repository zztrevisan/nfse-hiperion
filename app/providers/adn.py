import base64
import gzip
import json
import re
import ssl
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import ObjectIdentifier

from .base import Provider
from ..models import Company, DownloadedDocument

ADN_BASE = "https://adn.nfse.gov.br/contribuintes/DFe"
TRANSIENT = {429, 502, 503, 504}
CNPJ_OID = ObjectIdentifier("2.16.76.1.3.3")


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _first(parent: ET.Element | None, *names: str) -> str:
    if parent is None:
        return ""
    wanted = set(names)
    for node in parent.iter():
        if _local(node.tag) in wanted and node.text and node.text.strip():
            return node.text.strip()
    return ""


def _container(root: ET.Element, *names: str) -> ET.Element | None:
    wanted = set(names)
    return next((node for node in root.iter() if _local(node.tag) in wanted), None)


def _safe(value: str, fallback: str) -> str:
    value = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", value or "").strip(" ._")
    return value[:50] or fallback


def decode_xml(encoded: str) -> bytes:
    raw = base64.b64decode(encoded, validate=True)
    try:
        return gzip.decompress(raw)
    except (gzip.BadGzipFile, OSError):
        return raw


def parse_note(xml: bytes, owner: str) -> tuple[str, str, str, str]:
    root = ET.fromstring(xml)
    prestador = _container(root, "emit", "prest")
    tomador = _container(root, "toma", "tomador")
    prestador_cnpj = _digits(_first(prestador, "CNPJ", "CPF"))
    tomador_cnpj = _digits(_first(tomador, "CNPJ", "CPF"))
    if prestador_cnpj == owner:
        direction, counterpart = "Emitidas", _first(tomador, "xNome", "xRazSoc")
    elif tomador_cnpj == owner:
        direction, counterpart = "Recebidas", _first(prestador, "xNome", "xRazSoc", "xFant")
    else:
        direction, counterpart = "Outros", ""
    competence = _first(root, "dCompet")[:7] or _first(root, "dhEmi", "dhProc")[:7]
    return direction, competence, _first(root, "nNFSe", "nDPS"), counterpart


def parse_event(xml: bytes) -> tuple[str, str, str, str]:
    root = ET.fromstring(xml)
    referenced_key = _digits(_first(root, "chNFSe"))
    description = _first(root, "xDesc") or "Evento"
    reason = _first(root, "xMotivo")
    event_month = _first(root, "dhEvento", "dhProc")[:7]
    return referenced_key, description, reason, event_month


class AdnProvider(Provider):
    max_batches = 2000
    delay = 0.7

    def download(self, company: Company, password: str, year: int, month: int,
                 directions: set[str]) -> Iterable[DownloadedDocument]:
        wanted = f"{year}-{month:02d}"
        note_index: dict[str, tuple[str, str, str]] = {}
        pending_events: list[tuple[dict, bytes]] = []
        with tempfile.TemporaryDirectory(prefix="nfse-a1-") as temp:
            context, certificate_cnpj = self._context(company.certificate_path, password, Path(temp))
            query_cnpj = company.cnpj if certificate_cnpj and certificate_cnpj != company.cnpj else ""
            nsu, last_request = 0, 0.0
            for _ in range(self.max_batches):
                remaining = self.delay - (time.monotonic() - last_request)
                if remaining > 0:
                    time.sleep(remaining)
                payload = self._fetch(context, nsu, query_cnpj)
                last_request = time.monotonic()
                if payload is None:
                    break
                batch = payload.get("LoteDFe") or []
                if payload.get("StatusProcessamento") == "NENHUM_DOCUMENTO_LOCALIZADO" or not batch:
                    break
                highest = nsu
                for item in batch:
                    item_nsu = int(item.get("NSU") or 0)
                    highest = max(highest, item_nsu)
                    if not item.get("ArquivoXml"):
                        continue
                    try:
                        xml = decode_xml(item["ArquivoXml"])
                        if item.get("TipoDocumento") == "EVENTO":
                            pending_events.append((item, xml))
                            continue
                        direction, competence, number, counterpart = parse_note(xml, company.cnpj)
                    except Exception as exc:
                        raise RuntimeError(f"NSU {item_nsu}: XML inválido ({exc})") from exc
                    key = _digits(str(item.get("ChaveAcesso") or ""))
                    if key:
                        note_index[key] = (direction, competence, number)
                    if direction not in directions or competence != wanted:
                        continue
                    unique = str(item_nsu or _digits(str(item.get("ChaveAcesso") or ""))[-9:] or "sem-nsu")
                    filename = f"{_safe(number, 'SEM-NUMERO')}_{_safe(counterpart, 'SEM-NOME')}_{unique}.xml"
                    yield DownloadedDocument(direction, filename, xml)
                if highest <= nsu:
                    raise RuntimeError(f"ADN não avançou após o NSU {nsu}")
                nsu = highest
            else:
                raise RuntimeError(f"limite de {self.max_batches} lotes atingido no NSU {nsu}")

        for item, xml in pending_events:
            item_nsu = int(item.get("NSU") or 0)
            try:
                referenced, description, reason, event_month = parse_event(xml)
            except Exception as exc:
                raise RuntimeError(f"NSU {item_nsu}: evento XML inválido ({exc})") from exc
            original = note_index.get(referenced)
            if original:
                direction, competence, number = original
            else:
                direction, competence, number = "", event_month, "SEM-NUMERO"
            if direction not in directions or competence != wanted:
                continue
            label = _safe(description, "Evento")
            if reason:
                label += "_" + _safe(reason, "")[:35]
            filename = f"{_safe(number, 'SEM-NUMERO')}_{label}_{item_nsu or 'sem-nsu'}.xml"
            yield DownloadedDocument(direction, filename, xml, "Eventos")

    def _context(self, pfx: Path, password: str, temp: Path) -> tuple[ssl.SSLContext, str]:
        try:
            key, cert, chain = pkcs12.load_key_and_certificates(
                pfx.read_bytes(), password.encode("utf-8") if password else None
            )
        except Exception as exc:
            raise RuntimeError("não foi possível abrir o A1; confira arquivo e senha") from exc
        if key is None or cert is None:
            raise RuntimeError("o A1 não contém certificado e chave privada")
        expiry = getattr(cert, "not_valid_after_utc", cert.not_valid_after.replace(tzinfo=timezone.utc))
        if expiry < datetime.now(timezone.utc):
            raise RuntimeError(f"certificado vencido em {expiry:%d/%m/%Y}")
        cert_file, key_file = temp / "cert.pem", temp / "key.pem"
        cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM) + b"".join(
            item.public_bytes(serialization.Encoding.PEM) for item in (chain or [])
        ))
        key_file.write_bytes(key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        ))
        context = ssl.create_default_context()
        context.load_cert_chain(str(cert_file), str(key_file))
        attrs = cert.subject.get_attributes_for_oid(CNPJ_OID)
        return context, _digits(attrs[0].value) if attrs else ""

    def _fetch(self, context: ssl.SSLContext, nsu: int, query_cnpj: str) -> dict | None:
        query = "?lote=true" + (
            "&cnpjConsulta=" + urllib.parse.quote(query_cnpj) if query_cnpj else ""
        )
        url, last_error = f"{ADN_BASE}/{nsu}{query}", ""
        for attempt in range(5):
            request = urllib.request.Request(url, headers={
                "Accept": "application/json", "Cache-Control": "no-cache", "User-Agent": "NFSeLote/0.1"
            })
            try:
                with urllib.request.urlopen(request, context=context, timeout=60) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                if exc.code == 404:
                    return None
                last_error = self._error(exc.code, body)
                if exc.code not in TRANSIENT:
                    raise RuntimeError(last_error) from exc
                time.sleep(min(8, int(exc.headers.get("Retry-After", "0") or 0) or 2 ** (attempt + 1)))
            except (urllib.error.URLError, TimeoutError, ssl.SSLError) as exc:
                raise RuntimeError(f"falha de conexão mTLS com a ADN: {exc}") from exc
            except json.JSONDecodeError as exc:
                raise RuntimeError("ADN respondeu conteúdo inválido em vez de JSON") from exc
        raise RuntimeError(last_error or "ADN indisponível após cinco tentativas")

    @staticmethod
    def _error(status: int, body: str) -> str:
        detail = ""
        try:
            payload = json.loads(body)
            errors = payload.get("Erros") or payload.get("erros") or []
            detail = "; ".join(str(item.get("Descricao") or item.get("descricao") or "") for item in errors).strip("; ")
        except Exception:
            if body and not body.lstrip().startswith("<"):
                detail = body[:300]
        return f"ADN HTTP {status}" + (f" — {detail}" if detail else "")
