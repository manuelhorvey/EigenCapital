# EigenCapital Cross-Platform Abstraction Layer
#
# Centralises all platform-specific logic behind well-defined interfaces.
# Business logic elsewhere in the codebase should depend on these
# abstractions rather than on sys.platform, os.name, or hardcoded paths.
#
# Usage:
#   from eigencapital.platform import detect, PlatformType
#   plat = detect()
#   if plat.is_windows:
#       ...
#   elif plat.is_linux:
#       ...

from __future__ import annotations

from eigencapital.platform.detector import PlatformDetector, PlatformType, detect
from eigencapital.platform.paths import (
    PathResolver,
    resolve_data_dir,
    resolve_log_dir,
    resolve_config_dir,
    resolve_model_dir,
    resolve_backup_dir,
    resolve_cache_dir,
    resolve_project_root,
)
from eigencapital.platform.signals import (
    ShutdownManager,
    install_graceful_shutdown,
    register_shutdown_handler,
)
from eigencapital.platform.process import (
    ProcessInfo,
    find_process_by_name,
    kill_process,
    is_process_running,
    wait_for_port,
)
from eigencapital.platform.mt5_strategies import (
    MT5LaunchStrategy,
    MT5Environment,
    WineMT5Strategy,
    NativeWindowsMT5Strategy,
    get_strategy as get_mt5_strategy,
)
from eigencapital.platform.mt5_bridge_manager import (
    MT5BridgeManager,
    BridgeManagerConfig,
)

__all__ = [
    "PlatformDetector",
    "PlatformType",
    "detect",
    "PathResolver",
    "resolve_data_dir",
    "resolve_log_dir",
    "resolve_config_dir",
    "resolve_model_dir",
    "resolve_backup_dir",
    "resolve_cache_dir",
    "resolve_project_root",
    "ShutdownManager",
    "install_graceful_shutdown",
    "register_shutdown_handler",
    "ProcessInfo",
    "find_process_by_name",
    "kill_process",
    "is_process_running",
    "wait_for_port",
    "MT5LaunchStrategy",
    "MT5Environment",
    "WineMT5Strategy",
    "NativeWindowsMT5Strategy",
    "get_mt5_strategy",
    "MT5BridgeManager",
    "BridgeManagerConfig",
]
