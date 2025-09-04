"""
System monitoring utilities for HomeHelper on Raspberry Pi
"""
import os
import time
import psutil
from pathlib import Path
from typing import Dict, Any, Optional, List
import logging


class SystemMonitor:
    """Monitor system hardware and process metrics on Raspberry Pi"""
    
    def __init__(self):
        self.logger = logging.getLogger("homehelper.system_monitor")
    
    def get_hardware_metrics(self) -> Dict[str, Any]:
        """Get comprehensive system hardware metrics"""
        try:
            return {
                "cpu": self._get_cpu_metrics(),
                "memory": self._get_memory_metrics(),
                "disk": self._get_disk_metrics(),
                "temperature": self._get_temperature_metrics(),
                "timestamp": int(time.time())
            }
        except Exception as e:
            self.logger.error(f"Failed to get hardware metrics: {e}")
            return {"error": str(e), "timestamp": int(time.time())}
    
    def _get_cpu_metrics(self) -> Dict[str, Any]:
        """Get CPU usage and load metrics"""
        try:
            # Get CPU usage over 1 second interval
            cpu_percent = psutil.cpu_percent(interval=1)
            
            # Get load averages
            load_avg = os.getloadavg()
            
            # Get CPU count
            cpu_count = psutil.cpu_count()
            
            return {
                "usage_percent": round(cpu_percent, 1),
                "load_avg_1m": round(load_avg[0], 2),
                "load_avg_5m": round(load_avg[1], 2),
                "load_avg_15m": round(load_avg[2], 2),
                "core_count": cpu_count
            }
        except Exception as e:
            self.logger.error(f"Failed to get CPU metrics: {e}")
            return {"error": str(e)}
    
    def _get_memory_metrics(self) -> Dict[str, Any]:
        """Get memory usage metrics"""
        try:
            memory = psutil.virtual_memory()
            
            return {
                "total_mb": memory.total // (1024 * 1024),
                "used_mb": memory.used // (1024 * 1024),
                "available_mb": memory.available // (1024 * 1024),
                "percent": round(memory.percent, 1),
                "free_mb": memory.free // (1024 * 1024)
            }
        except Exception as e:
            self.logger.error(f"Failed to get memory metrics: {e}")
            return {"error": str(e)}
    
    def _get_disk_metrics(self) -> Dict[str, Any]:
        """Get disk usage metrics for root filesystem"""
        try:
            disk = psutil.disk_usage('/')
            
            return {
                "total_gb": round(disk.total / (1024 * 1024 * 1024), 1),
                "used_gb": round(disk.used / (1024 * 1024 * 1024), 1),
                "free_gb": round(disk.free / (1024 * 1024 * 1024), 1),
                "percent": round((disk.used / disk.total) * 100, 1)
            }
        except Exception as e:
            self.logger.error(f"Failed to get disk metrics: {e}")
            return {"error": str(e)}
    
    def _get_temperature_metrics(self) -> Dict[str, Any]:
        """Get CPU temperature from Raspberry Pi thermal sensors"""
        try:
            temp_data = {}
            
            # Try to read CPU temperature from thermal zone
            thermal_path = Path('/sys/class/thermal/thermal_zone0/temp')
            if thermal_path.exists():
                try:
                    with open(thermal_path, 'r') as f:
                        temp_millidegrees = int(f.read().strip())
                        temp_data["cpu_celsius"] = round(temp_millidegrees / 1000.0, 1)
                except Exception as e:
                    self.logger.debug(f"Could not read thermal zone: {e}")
            
            # Try to get temperature from psutil (if available)
            try:
                sensors = psutil.sensors_temperatures()
                if sensors:
                    for name, entries in sensors.items():
                        for entry in entries:
                            if entry.current:
                                temp_data[f"{name}_celsius"] = round(entry.current, 1)
            except Exception as e:
                self.logger.debug(f"psutil temperature sensors not available: {e}")
            
            return temp_data if temp_data else {"cpu_celsius": None}
            
        except Exception as e:
            self.logger.error(f"Failed to get temperature metrics: {e}")
            return {"error": str(e)}
    
    def get_process_metrics(self, pid: int) -> Optional[Dict[str, Any]]:
        """Get metrics for a specific process"""
        try:
            process = psutil.Process(pid)
            
            # Get process info
            with process.oneshot():
                return {
                    "pid": pid,
                    "name": process.name(),
                    "status": process.status(),
                    "cpu_percent": round(process.cpu_percent(), 1),
                    "memory_mb": process.memory_info().rss // (1024 * 1024),
                    "memory_percent": round(process.memory_percent(), 1),
                    "create_time": process.create_time(),
                    "uptime_seconds": int(time.time() - process.create_time()),
                    "num_threads": process.num_threads(),
                    "cmdline": " ".join(process.cmdline()[:3])  # First 3 args only
                }
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess) as e:
            self.logger.debug(f"Could not get metrics for PID {pid}: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Error getting process metrics for PID {pid}: {e}")
            return None
    
    def get_processes_by_name(self, name_pattern: str) -> List[Dict[str, Any]]:
        """Get metrics for all processes matching name pattern"""
        processes = []
        
        try:
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    if name_pattern.lower() in proc.info['name'].lower():
                        metrics = self.get_process_metrics(proc.info['pid'])
                        if metrics:
                            processes.append(metrics)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception as e:
            self.logger.error(f"Error searching for processes with pattern '{name_pattern}': {e}")
        
        return processes
    
    def get_homehelper_processes(self) -> List[Dict[str, Any]]:
        """Get metrics for all HomeHelper-related processes"""
        patterns = ["homehelper", "streamlit", "uvicorn"]
        all_processes = []
        
        for pattern in patterns:
            processes = self.get_processes_by_name(pattern)
            all_processes.extend(processes)
        
        # Remove duplicates by PID
        seen_pids = set()
        unique_processes = []
        for proc in all_processes:
            if proc['pid'] not in seen_pids:
                seen_pids.add(proc['pid'])
                unique_processes.append(proc)
        
        return unique_processes
    
    def get_system_summary(self) -> Dict[str, Any]:
        """Get a summary of system status"""
        try:
            hardware = self.get_hardware_metrics()
            homehelper_procs = self.get_homehelper_processes()
            
            return {
                "hardware": hardware,
                "processes": {
                    "homehelper_count": len(homehelper_procs),
                    "homehelper_processes": homehelper_procs
                },
                "status": self._determine_system_status(hardware, homehelper_procs),
                "timestamp": int(time.time())
            }
        except Exception as e:
            self.logger.error(f"Failed to get system summary: {e}")
            return {
                "error": str(e),
                "timestamp": int(time.time())
            }
    
    def _determine_system_status(self, hardware: Dict[str, Any], processes: List[Dict[str, Any]]) -> str:
        """Determine overall system health status"""
        try:
            # Check for hardware issues
            if "error" in hardware:
                return "error"
            
            cpu_usage = hardware.get("cpu", {}).get("usage_percent", 0)
            memory_usage = hardware.get("memory", {}).get("percent", 0)
            disk_usage = hardware.get("disk", {}).get("percent", 0)
            temp = hardware.get("temperature", {}).get("cpu_celsius")
            
            # Warning thresholds for Raspberry Pi 5
            if cpu_usage > 80:
                return "warning"
            if memory_usage > 85:
                return "warning"
            if disk_usage > 90:
                return "warning"
            if temp and temp > 70:  # Raspberry Pi throttles at ~80°C
                return "warning"
            
            return "good"
            
        except Exception:
            return "unknown"
