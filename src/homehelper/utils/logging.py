"""
Shared logging utilities for HomeHelper apps
"""
import logging
import logging.handlers
from pathlib import Path
from typing import Optional


def setup_app_logger(
    app_id: str, 
    logs_dir: Optional[Path] = None,
    level: str = "INFO",
    max_bytes: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 5
) -> logging.Logger:
    """
    Setup a logger for a HomeHelper app with file and console handlers
    
    Args:
        app_id: Unique identifier for the app
        logs_dir: Directory to store log files (creates subdirectory for app)
        level: Logging level (DEBUG, INFO, WARNING, ERROR)
        max_bytes: Maximum size of each log file before rotation
        backup_count: Number of backup files to keep
    
    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(f"homehelper.{app_id}")
    
    # Avoid duplicate handlers if logger already configured
    if logger.handlers:
        return logger
    
    logger.setLevel(getattr(logging, level.upper()))
    
    # Create formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - [%(name)s] - %(message)s'
    )
    
    # Setup file handler if logs directory provided
    if logs_dir:
        app_log_dir = logs_dir / app_id
        app_log_dir.mkdir(parents=True, exist_ok=True)
        
        log_file = app_log_dir / f"{app_id}.log"
        file_handler = logging.handlers.RotatingFileHandler(
            log_file, 
            maxBytes=max_bytes, 
            backupCount=backup_count
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    
    # Setup console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    return logger


def get_app_logger(app_id: str) -> logging.Logger:
    """
    Get existing logger for an app or create a basic one
    
    Args:
        app_id: Unique identifier for the app
    
    Returns:
        Logger instance
    """
    logger_name = f"homehelper.{app_id}"
    logger = logging.getLogger(logger_name)
    
    # If no handlers, setup basic console logging
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - [%(name)s] - %(message)s'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    
    return logger


def setup_main_logger(logs_dir: Path, level: str = "INFO") -> logging.Logger:
    """
    Setup the main HomeHelper application logger
    
    Args:
        logs_dir: Directory to store log files
        level: Logging level
    
    Returns:
        Configured main logger
    """
    return setup_app_logger(
        app_id="main",
        logs_dir=logs_dir,
        level=level,
        max_bytes=20 * 1024 * 1024,  # 20MB for main app
        backup_count=10
    )


class LogFileReader:
    """Utility class for reading and parsing HomeHelper log files"""
    
    def __init__(self, logs_dir: Path):
        self.logs_dir = Path(logs_dir)
    
    def get_app_log_files(self, app_id: str) -> list[Path]:
        """Get all log files for a specific app"""
        app_log_dir = self.logs_dir / app_id
        if not app_log_dir.exists():
            return []
        
        log_files = []
        # Main log file
        main_log = app_log_dir / f"{app_id}.log"
        if main_log.exists():
            log_files.append(main_log)
        
        # Rotated log files
        for i in range(1, 11):  # Check up to 10 backup files
            backup_log = app_log_dir / f"{app_id}.log.{i}"
            if backup_log.exists():
                log_files.append(backup_log)
        
        return sorted(log_files, key=lambda x: x.stat().st_mtime, reverse=True)
    
    def read_recent_logs(
        self, 
        app_id: str, 
        lines: int = 100,
        level_filter: Optional[str] = None
    ) -> list[str]:
        """
        Read recent log entries for an app
        
        Args:
            app_id: App identifier
            lines: Number of recent lines to read
            level_filter: Filter by log level (DEBUG, INFO, WARNING, ERROR)
        
        Returns:
            List of log lines
        """
        log_files = self.get_app_log_files(app_id)
        if not log_files:
            return []
        
        all_lines = []
        
        # Read from most recent file first
        for log_file in log_files:
            try:
                with open(log_file, 'r') as f:
                    file_lines = f.readlines()
                    
                    # Apply level filter if specified
                    if level_filter:
                        file_lines = [
                            line for line in file_lines 
                            if f" - {level_filter.upper()} - " in line
                        ]
                    
                    all_lines.extend(file_lines)
                    
                    # Stop if we have enough lines
                    if len(all_lines) >= lines:
                        break
                        
            except Exception as e:
                # Skip files that can't be read
                continue
        
        # Return most recent lines
        return all_lines[-lines:] if all_lines else []
    
    def get_available_apps(self) -> list[str]:
        """Get list of apps that have log directories"""
        if not self.logs_dir.exists():
            return []
        
        apps = []
        for item in self.logs_dir.iterdir():
            if item.is_dir() and not item.name.startswith('.'):
                apps.append(item.name)
        
        return sorted(apps)
