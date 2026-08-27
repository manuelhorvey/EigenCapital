"""Structured Logging — JSON logging for machine consumption.

Provides consistent, structured logging across all EigenCapital modules.
Every log entry includes:
- Timestamp (ISO 8601 UTC)
- Module name
- Log level
- Message
- Structured data (key-value pairs)
- Correlation ID (for trade reconstruction)

Design principles:
- Machine-readable (JSON format)
- Human-readable (text fallback)
- Bounded output (no excessive nesting)
- Filterable by module, level, correlation
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional


class LogLevel(str, Enum):
    """Log levels for structured logging."""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class StructuredLogger:
    """Structured JSON logger for machine consumption.
    
    Usage:
        logger = StructuredLogger("execution")
        logger.info("order_submitted", order_id="12345", symbol="EURUSD")
    """
    
    def __init__(
        self,
        module_name: str,
        log_file: Optional[str] = None,
        min_level: LogLevel = LogLevel.INFO,
    ) -> None:
        """Initialize structured logger.
        
        Args:
            module_name: Name of the module (e.g., "execution", "risk")
            log_file: Optional file path for log output
            min_level: Minimum log level to output
        """
        self._module_name = module_name
        self._min_level = min_level
        
        # Set up Python logging
        self._logger = logging.getLogger(f"eigencapital.{module_name}")
        self._logger.setLevel(logging.DEBUG)
        
        # JSON formatter
        formatter = logging.Formatter("%(message)s")
        
        # Console handler (stderr)
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setFormatter(formatter)
        self._logger.addHandler(console_handler)
        
        # File handler (if specified)
        if log_file:
            file_handler = logging.FileHandler(log_file)
            file_handler.setFormatter(formatter)
            self._logger.addHandler(file_handler)
    
    def _log(
        self,
        level: LogLevel,
        event: str,
        data: Optional[Dict[str, Any]] = None,
        correlation_id: Optional[str] = None,
        error: Optional[Exception] = None,
    ) -> None:
        """Log a structured event.
        
        Args:
            level: Log level
            event: Event name (e.g., "order_submitted")
            data: Structured data (key-value pairs)
            correlation_id: Trade correlation ID (optional)
            error: Exception to log (optional)
        """
        # Check minimum level
        level_order = [LogLevel.DEBUG, LogLevel.INFO, LogLevel.WARNING, LogLevel.ERROR, LogLevel.CRITICAL]
        if level_order.index(level) < level_order.index(self._min_level):
            return
        
        # Build log entry
        entry: Dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "module": self._module_name,
            "level": level.value,
            "event": event,
        }
        
        if correlation_id:
            entry["correlation_id"] = correlation_id
        
        if data:
            entry["data"] = data
        
        if error:
            entry["error"] = {
                "type": type(error).__name__,
                "message": str(error),
            }
        
        # Format for logging
        message = json.dumps(entry, default=str)
        
        # Log at appropriate Python level
        if level == LogLevel.DEBUG:
            self._logger.debug(message)
        elif level == LogLevel.INFO:
            self._logger.info(message)
        elif level == LogLevel.WARNING:
            self._logger.warning(message)
        elif level == LogLevel.ERROR:
            self._logger.error(message)
        elif level == LogLevel.CRITICAL:
            self._logger.critical(message)
    
    def debug(self, event: str, **data: Any) -> None:
        """Log debug event."""
        self._log(LogLevel.DEBUG, event, data)
    
    def info(self, event: str, **data: Any) -> None:
        """Log info event."""
        self._log(LogLevel.INFO, event, data)
    
    def warning(self, event: str, **data: Any) -> None:
        """Log warning event."""
        self._log(LogLevel.WARNING, event, data)
    
    def error(self, event: str, error: Optional[Exception] = None, **data: Any) -> None:
        """Log error event."""
        self._log(LogLevel.ERROR, event, data, error=error)
    
    def critical(self, event: str, error: Optional[Exception] = None, **data: Any) -> None:
        """Log critical event."""
        self._log(LogLevel.CRITICAL, event, data, error=error)
    
    def trade(
        self,
        event: str,
        correlation_id: str,
        **data: Any,
    ) -> None:
        """Log trade event with correlation ID.
        
        Args:
            event: Event name (e.g., "order_submitted")
            correlation_id: Trade correlation ID for reconstruction
            **data: Additional structured data
        """
        self._log(LogLevel.INFO, event, data, correlation_id=correlation_id)


# Module-level loggers for common components
_loggers: Dict[str, StructuredLogger] = {}


def get_logger(module_name: str) -> StructuredLogger:
    """Get or create a structured logger for a module.
    
    Args:
        module_name: Module name (e.g., "execution", "risk", "reconciliation")
        
    Returns:
        StructuredLogger instance
    """
    if module_name not in _loggers:
        _loggers[module_name] = StructuredLogger(module_name)
    return _loggers[module_name]
