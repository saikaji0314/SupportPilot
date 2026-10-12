"""兼容 uvicorn supportpilot.api:app；服务实现位于 server/api.py。"""
from supportpilot.server.api import app, create_app, Runtime

__all__ = ["app", "create_app", "Runtime"]
