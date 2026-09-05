from __future__ import annotations

from pydantic import BaseModel, Field


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=200)


class LoginOut(BaseModel):
    nickname: str
    is_site_admin: bool


class PasswordChangeIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    # Нижняя граница выше, чем у пароля при входе: там мы принимаем любой
    # существующий (в том числе старый короткий), а здесь задаём новый и можем
    # требовать приличную длину. Временный пароль из grant_site_access -- 22
    # символа, так что планка никого не ломает.
    new_password: str = Field(min_length=10, max_length=200)
