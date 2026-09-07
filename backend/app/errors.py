from __future__ import annotations


class ServiceError(Exception):
    """Ошибка бизнес-логики сервиса. Роутеры ловят конкретные подклассы и
    отдают .message как текст 4xx-ответа (см. app/routers/*)."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)
