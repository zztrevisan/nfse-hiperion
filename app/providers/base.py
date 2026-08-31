from abc import ABC, abstractmethod
from collections.abc import Iterable

from ..models import Company, DownloadedDocument


class Provider(ABC):
    @abstractmethod
    def download(self, company: Company, password: str, year: int, month: int,
                 directions: set[str]) -> Iterable[DownloadedDocument]:
        raise NotImplementedError
