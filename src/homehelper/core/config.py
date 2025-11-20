"""
Configuration management for HomeHelper
"""
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


class RedisConfig(BaseModel):
    host: str = "localhost"
    port: int = 6379
    db: int = 0


class EventSubscriberConfig(BaseModel):
    max_events: int = 100
    channels: list[str] = ["homehelper:events:*"]


class LoggingConfig(BaseModel):
    level: str = "INFO"
    format: str = "%(asctime)s - %(levelname)s - [%(name)s] - %(message)s"


class PortRange(BaseModel):
    start: int = 8100
    end: int = 8199


class ProcessManagerConfig(BaseModel):
    data_dir: str = "/opt/homehelper/data"
    logs_dir: str = "/opt/homehelper/logs"
    streamlit_port: int = 8501
    streamlit_ttl_seconds: int = 300
    port_range: PortRange = Field(default_factory=PortRange)


class SystemConfig(BaseModel):
    main_port: int = 8000
    host: str = "0.0.0.0"


class HomeHelperConfig(BaseSettings):
    redis: RedisConfig = Field(default_factory=RedisConfig)
    event_subscriber: EventSubscriberConfig = Field(default_factory=EventSubscriberConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    process_manager: ProcessManagerConfig = Field(default_factory=ProcessManagerConfig)
    health_check_interval_seconds: int = 60
    system: SystemConfig = Field(default_factory=SystemConfig)

    class Config:
        env_prefix = "HOMEHELPER_"
        case_sensitive = False


class ConfigManager:
    """Manages HomeHelper configuration from JSON file and environment variables"""
    
    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = config_path or Path("config/config.json")
        self._config: Optional[HomeHelperConfig] = None
        self.logger = logging.getLogger("homehelper.config")
    
    def load_config(self) -> HomeHelperConfig:
        """Load configuration from file and environment variables"""
        config_data = {}
        
        # Load from JSON file if it exists
        if self.config_path.exists():
            try:
                with open(self.config_path, 'r') as f:
                    config_data = json.load(f)
                self.logger.info(f"Loaded configuration from {self.config_path}")
            except Exception as e:
                self.logger.error(f"Failed to load config from {self.config_path}: {e}")
        else:
            self.logger.warning(f"Config file not found at {self.config_path}, using defaults")
        
        # Create config object (will also load from environment variables)
        self._config = HomeHelperConfig(**config_data)
        return self._config
    
    @property
    def config(self) -> HomeHelperConfig:
        """Get current configuration, loading if necessary"""
        if self._config is None:
            self.load_config()
        return self._config
    
    def save_config(self, config_path: Optional[Path] = None) -> None:
        """Save current configuration to JSON file"""
        if self._config is None:
            raise ValueError("No configuration loaded")
        
        save_path = config_path or self.config_path
        save_path.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            with open(save_path, 'w') as f:
                json.dump(self._config.model_dump(), f, indent=2)
            self.logger.info(f"Saved configuration to {save_path}")
        except Exception as e:
            self.logger.error(f"Failed to save config to {save_path}: {e}")
            raise
    
    def get_redis_url(self) -> str:
        """Get Redis connection URL"""
        redis_config = self.config.redis
        return f"redis://{redis_config.host}:{redis_config.port}/{redis_config.db}"
    
    def get_data_dir(self, app_name: Optional[str] = None) -> Path:
        """Get data directory path, optionally for specific app"""
        base_dir = Path(self.config.process_manager.data_dir)
        if app_name:
            return base_dir / app_name
        return base_dir
    
    def get_logs_dir(self, app_name: Optional[str] = None) -> Path:
        """Get logs directory path, optionally for specific app"""
        base_dir = Path(self.config.process_manager.logs_dir)
        if app_name:
            return base_dir / app_name
        return base_dir


# Global config manager instance
config_manager = ConfigManager()
