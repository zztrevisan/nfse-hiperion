"""Lista de CNPJ/CPF: leitura de texto livre ou TXT e validação dos dígitos verificadores."""
import re

# CNPJ alfanumérico (a partir de 07/2026) e o numérico antigo usam o mesmo cálculo:
# cada caractere vale ord(c) - 48, então '0'..'9' continuam valendo 0..9.
_CNPJ_RE = re.compile(r"(?<![0-9A-Z])[0-9A-Z]{2}\.?[0-9A-Z]{3}\.?[0-9A-Z]{3}/?[0-9A-Z]{4}-?\d{2}(?![0-9A-Z])")
_CPF_RE = re.compile(r"(?<!\d)\d{3}\.?\d{3}\.?\d{3}-?\d{2}(?!\d)")


def clean(value: str) -> str:
    return re.sub(r"[^0-9A-Z]", "", (value or "").upper())


def _dv(base: str, weights: list[int]) -> int:
    rest = sum((ord(c) - 48) * w for c, w in zip(base, weights)) % 11
    return 0 if rest < 2 else 11 - rest


def valid_cnpj(value: str) -> bool:
    value = clean(value)
    if len(value) != 14 or not value[-2:].isdigit() or len(set(value)) == 1:
        return False
    w1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    d1 = _dv(value[:12], w1)
    d2 = _dv(value[:12] + str(d1), [6] + w1)
    return value[-2:] == f"{d1}{d2}"


def valid_cpf(value: str) -> bool:
    value = clean(value)
    if len(value) != 11 or not value.isdigit() or len(set(value)) == 1:
        return False
    d1 = _dv(value[:9], list(range(10, 1, -1)))
    d2 = _dv(value[:9] + str(d1), list(range(11, 1, -1)))
    return value[-2:] == f"{d1}{d2}"


def valid_document(value: str) -> bool:
    return valid_cnpj(value) or valid_cpf(value)


def fmt(value: str) -> str:
    v = clean(value)
    if len(v) == 14:
        return f"{v[:2]}.{v[2:5]}.{v[5:8]}/{v[8:12]}-{v[12:]}"
    if len(v) == 11:
        return f"{v[:3]}.{v[3:6]}.{v[6:9]}-{v[9:]}"
    return v


def parse_list(text: str) -> tuple[list[str], list[str]]:
    """Extrai CNPJ/CPF de um texto qualquer (um por linha, com nome, separado por ; etc.).

    Devolve (válidos sem repetição, na ordem; inválidos encontrados).
    """
    text = (text or "").upper()
    found, invalid = [], []

    def take(match: re.Match) -> str:
        doc = clean(match.group())
        (found if valid_cnpj(doc) else invalid).append(doc)
        return " "

    rest = _CNPJ_RE.sub(take, text)
    for match in _CPF_RE.finditer(rest):
        doc = clean(match.group())
        (found if valid_cpf(doc) else invalid).append(doc)
    return list(dict.fromkeys(found)), list(dict.fromkeys(invalid))
