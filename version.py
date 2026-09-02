"""Lightweight shared version module.

Provides APP_VERSION for use in app, desktop, and --version (frozen-safe, no side effects).
Importing this module has no heavy dependencies and works in PyInstaller bundles.
"""
from __future__ import annotations

APP_VERSION = "0.4.3"
