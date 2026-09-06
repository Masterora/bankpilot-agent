"""
文件职责：提供认证边界所需的密码与会话安全原语。

主要内容：
- `hash_password` / `verify_password`：密码哈希与校验。
- `validate_new_password`：统一新密码的长度和字符组合规则。
- `DUMMY_PASSWORD_HASH`：减少未知邮箱产生的认证耗时差异。
- `create_session_token` / `hash_session_token`：生成会话令牌并转换为可持久化标识。

关键边界：数据库只保存会话令牌的 HMAC-SHA256 结果，不保存原始令牌。
"""

import hashlib
import hmac
import re
import secrets

from pwdlib import PasswordHash

_password_hash = PasswordHash.recommended()
DUMMY_PASSWORD_HASH = _password_hash.hash("not-a-real-bankpilot-password")
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128


def validate_new_password(password: str) -> str:
    """新密码必须包含 ASCII 大小写字母、数字和非空白符号。"""
    if not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
        raise ValueError("password_length")
    required = (r"[a-z]", r"[A-Z]", r"[0-9]", r"[^A-Za-z0-9\s]")
    if not all(re.search(pattern, password) for pattern in required):
        raise ValueError("password_format")
    return password


def hash_password(password: str) -> str:
    return _password_hash.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """按存储哈希中记录的算法校验密码。"""
    return _password_hash.verify(password, password_hash)


def create_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_session_token(token: str, secret: str) -> str:
    """生成可安全入库的会话标识，原始 Cookie 永不持久化。"""
    return hmac.new(secret.encode(), token.encode(), hashlib.sha256).hexdigest()
