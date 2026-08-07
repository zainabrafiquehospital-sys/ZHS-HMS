from typing import Generic, TypeVar

from app.shared.repository.base_repository import BaseRepository

RepositoryType = TypeVar("RepositoryType", bound=BaseRepository)


class BaseService(Generic[RepositoryType]):
    """Generic service base. Feature modules subclass this with their own
    repository type and business rules; no business logic lives here."""

    def __init__(self, repository: RepositoryType) -> None:
        self.repository = repository
