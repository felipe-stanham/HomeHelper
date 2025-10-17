"""
Port Manager for HomeHelper

Manages dynamic port allocation for applications in the configured range.
Handles port assignment, tracking, and cleanup for both service and Streamlit apps.
"""

import json
import logging
import socket
from pathlib import Path
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, asdict
from datetime import datetime

from ..core.config import ConfigManager


@dataclass
class PortAllocation:
    """Port allocation information"""
    port: int
    app_id: str
    app_type: str  # 'service' or 'streamlit'
    allocated_at: datetime
    status: str  # 'allocated', 'in_use', 'released'
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization"""
        data = asdict(self)
        data['allocated_at'] = self.allocated_at.isoformat()
        return data
    
    @classmethod
    def from_dict(cls, data: dict) -> 'PortAllocation':
        """Create from dictionary"""
        data['allocated_at'] = datetime.fromisoformat(data['allocated_at'])
        return cls(**data)


class PortManager:
    """Manages dynamic port allocation for applications"""
    
    def __init__(self, config_manager: ConfigManager):
        self.config_manager = config_manager
        self.logger = logging.getLogger("homehelper.port_manager")
        
        # Get port range from config
        config = config_manager.config
        self.port_start = config.process_manager.port_range.start
        self.port_end = config.process_manager.port_range.end
        
        # Port allocation tracking (in-memory only)
        self.allocations: Dict[int, PortAllocation] = {}
        self.app_ports: Dict[str, int] = {}  # app_id -> port mapping
        
        self.logger.info(f"Initialized port manager (range: {self.port_start}-{self.port_end})")
    
    def _is_port_available(self, port: int) -> bool:
        """Check if a port is available for binding"""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.bind(('localhost', port))
                return True
        except OSError:
            return False
    
    def allocate_port(self, app_id: str, app_type: str, preferred_port: Optional[int] = None) -> Optional[int]:
        """
        Allocate a port for an application
        
        Args:
            app_id: Unique application identifier
            app_type: Type of application ('service' or 'streamlit')
            preferred_port: Preferred port number (if available)
            
        Returns:
            Allocated port number or None if no ports available
        """
        # Check if app already has a port allocated
        if app_id in self.app_ports:
            existing_port = self.app_ports[app_id]
            allocation = self.allocations[existing_port]
            
            # If port is still available, reuse it
            if self._is_port_available(existing_port):
                allocation.status = 'allocated'
                allocation.allocated_at = datetime.now()
                self.logger.info(f"Reusing existing port {existing_port} for app {app_id}")
                return existing_port
            else:
                # Port is in use by something else, release it
                self.release_port(app_id)
        
        # Try preferred port first
        if preferred_port and self.port_start <= preferred_port <= self.port_end:
            if preferred_port not in self.allocations and self._is_port_available(preferred_port):
                return self._allocate_specific_port(app_id, app_type, preferred_port)
        
        # Find next available port in range
        for port in range(self.port_start, self.port_end + 1):
            if port not in self.allocations and self._is_port_available(port):
                return self._allocate_specific_port(app_id, app_type, port)
        
        self.logger.error(f"No available ports in range {self.port_start}-{self.port_end}")
        return None
    
    def _allocate_specific_port(self, app_id: str, app_type: str, port: int) -> int:
        """Allocate a specific port to an application"""
        allocation = PortAllocation(
            port=port,
            app_id=app_id,
            app_type=app_type,
            allocated_at=datetime.now(),
            status='allocated'
        )
        
        self.allocations[port] = allocation
        self.app_ports[app_id] = port
        
        self.logger.info(f"Allocated port {port} to {app_type} app {app_id}")
        return port
    
    def release_port(self, app_id: str) -> bool:
        """
        Release a port allocated to an application
        
        Args:
            app_id: Application identifier
            
        Returns:
            True if port was released, False if not found
        """
        if app_id not in self.app_ports:
            self.logger.warning(f"No port allocated to app {app_id}")
            return False
        
        port = self.app_ports[app_id]
        allocation = self.allocations[port]
        allocation.status = 'released'
        
        # Remove from tracking
        del self.app_ports[app_id]
        del self.allocations[port]
        
        self.logger.info(f"Released port {port} from app {app_id}")
        return True
    
    def get_app_port(self, app_id: str) -> Optional[int]:
        """Get the port allocated to an application"""
        return self.app_ports.get(app_id)
    
    def mark_port_in_use(self, app_id: str) -> bool:
        """Mark an allocated port as in use"""
        if app_id not in self.app_ports:
            return False
        
        port = self.app_ports[app_id]
        if port in self.allocations:
            self.allocations[port].status = 'in_use'
            self.logger.debug(f"Marked port {port} as in use for app {app_id}")
            return True
        
        return False
    
    def get_allocated_ports(self) -> List[PortAllocation]:
        """Get all current port allocations"""
        return list(self.allocations.values())
    
    def get_available_ports(self) -> List[int]:
        """Get list of available ports in the configured range"""
        available = []
        for port in range(self.port_start, self.port_end + 1):
            if port not in self.allocations and self._is_port_available(port):
                available.append(port)
        return available
    
    def cleanup_stale_allocations(self) -> int:
        """
        Clean up stale port allocations (ports that are allocated but not in use)
        
        Returns:
            Number of stale allocations cleaned up
        """
        cleaned = 0
        stale_apps = []
        
        for app_id, port in self.app_ports.items():
            allocation = self.allocations[port]
            
            # If port is allocated but actually available, it's stale
            if allocation.status == 'allocated' and self._is_port_available(port):
                # Check if allocation is old (more than 1 hour)
                age = datetime.now() - allocation.allocated_at
                if age.total_seconds() > 3600:  # 1 hour
                    stale_apps.append(app_id)
        
        for app_id in stale_apps:
            if self.release_port(app_id):
                cleaned += 1
        
        if cleaned > 0:
            self.logger.info(f"Cleaned up {cleaned} stale port allocations")
        
        return cleaned
    
    def get_port_statistics(self) -> dict:
        """Get port allocation statistics"""
        total_ports = self.port_end - self.port_start + 1
        allocated_ports = len(self.allocations)
        available_ports = len(self.get_available_ports())
        
        status_counts = {}
        app_type_counts = {}
        
        for allocation in self.allocations.values():
            status_counts[allocation.status] = status_counts.get(allocation.status, 0) + 1
            app_type_counts[allocation.app_type] = app_type_counts.get(allocation.app_type, 0) + 1
        
        return {
            'total_ports': total_ports,
            'allocated_ports': allocated_ports,
            'available_ports': available_ports,
            'port_range': f"{self.port_start}-{self.port_end}",
            'status_breakdown': status_counts,
            'app_type_breakdown': app_type_counts,
            'utilization_percent': round((allocated_ports / total_ports) * 100, 1)
        }
