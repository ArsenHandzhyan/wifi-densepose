"""
Hardware abstraction layer for WiFi-DensePose system.

The package intentionally avoids eager re-exports of optional SSH-backed
modules so imports like `src.core.router_interface` do not require `asyncssh`
unless the legacy hardware compatibility surface is imported directly.
"""
