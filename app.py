"""Vercel ASGI entry point; also usable with uvicorn app:app."""

from src.api.main import app

__all__ = ["app"]
