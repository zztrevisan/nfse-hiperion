"""Certificado A1 (.pfx/.p12) do procurador: abre, valida e monta o contexto mTLS."""
import os
import ssl
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID, ObjectIdentifier

from .documents import clean

# ICP-Brasil: OID do CNPJ no e-CNPJ e do CPF (dentro dos 8 primeiros dígitos após a data) no e-CPF.
OID_CNPJ = ObjectIdentifier("2.16.76.1.3.3")


@dataclass(frozen=True)
class CertInfo:
    holder: str        # nome do titular (CN)
    document: str      # CNPJ ou CPF do titular, só dígitos ('' se não achou)
    expires: datetime


def _holder_document(cert, common_name: str) -> str:
    attrs = cert.subject.get_attributes_for_oid(OID_CNPJ)
    if attrs:
        return clean(attrs[0].value)
    # e-CPF / e-CNPJ costumam trazer "NOME:DOCUMENTO" no CN.
    if ":" in common_name:
        tail = clean(common_name.rsplit(":", 1)[1])
        if len(tail) in (11, 14):
            return tail
    return ""


def load(pfx: Path, password: str) -> tuple[ssl.SSLContext, CertInfo]:
    try:
        key, cert, chain = pkcs12.load_key_and_certificates(
            Path(pfx).read_bytes(), password.encode("utf-8") if password else None
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"certificado não encontrado: {pfx}") from exc
    except Exception as exc:
        raise RuntimeError("não foi possível abrir o certificado; confira o arquivo e a senha") from exc
    if key is None or cert is None:
        raise RuntimeError("o arquivo não contém certificado e chave privada")

    expires = cert.not_valid_after_utc
    if expires < datetime.now(timezone.utc):
        raise RuntimeError(f"certificado vencido em {expires:%d/%m/%Y}")
    cn_attrs = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    common_name = cn_attrs[0].value if cn_attrs else ""
    info = CertInfo(common_name.split(":")[0].strip(), _holder_document(cert, common_name), expires)

    # O ssl do Python só carrega chave/certificado de arquivo: grava PEM temporário e apaga em seguida.
    pem_cert = cert.public_bytes(serialization.Encoding.PEM) + b"".join(
        c.public_bytes(serialization.Encoding.PEM) for c in (chain or []))
    pem_key = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption())
    context = ssl.create_default_context()
    with tempfile.TemporaryDirectory(prefix="nfse-") as temp:
        cert_file, key_file = os.path.join(temp, "c.pem"), os.path.join(temp, "k.pem")
        Path(cert_file).write_bytes(pem_cert)
        Path(key_file).write_bytes(pem_key)
        context.load_cert_chain(cert_file, key_file)
    return context, info
