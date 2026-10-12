"""运行配置入口：按需读取，进程环境优先于 .env，不修改进程环境。

模型工厂调用时才读取凭据；管理员名单只读取进程环境。
业务规则、上传限制和文档元数据仍由各自模块负责。
"""
from dataclasses import dataclass, field
import os

from dotenv import dotenv_values

from supportpilot.paths import ROOT


@dataclass(frozen=True)
class ChatConfig:
    api_key: str | None = field(repr=False)
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    model: str = "qwen3.7-plus-2026-05-26"
    timeout: float = 60.0
    max_retries: int = 0


@dataclass(frozen=True)
class EmbeddingConfig:
    api_key: str | None = field(repr=False)
    base_url: str | None = None
    model: str = "text-embedding-v4"
    dimensions: int = 1024
    timeout: float = 60.0
    max_retries: int = 1


def _model_environment() -> dict:
    # 不缓存、不写回 os.environ，测试和不同调用不会留下隐式配置状态。
    return {**dotenv_values(ROOT / ".env"), **os.environ}


def load_chat_config() -> ChatConfig:
    values = _model_environment()
    return ChatConfig(
        api_key=values.get("API_KEY"),
        base_url=values.get("SUPPORTPILOT_CHAT_BASE_URL") or ChatConfig.base_url,
        model=values.get("SUPPORTPILOT_CHAT_MODEL") or ChatConfig.model,
    )


def load_embedding_config() -> EmbeddingConfig:
    values = _model_environment()
    return EmbeddingConfig(
        api_key=values.get("SUPPORTPILOT_EMBEDDING_API_KEY") or values.get("API_KEY"),
        base_url=values.get("SUPPORTPILOT_EMBEDDING_BASE_URL"),
        model=values.get("SUPPORTPILOT_EMBEDDING_MODEL") or EmbeddingConfig.model,
    )


def admin_usernames() -> frozenset[str]:
    """启动时读取；注册账号后显式设置进程变量并重启服务生效。"""
    return frozenset(name.strip().lower()
                     for name in os.getenv("SUPPORTPILOT_ADMIN_USERS", "").split(",")
                     if name.strip())
