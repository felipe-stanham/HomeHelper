"""
Unit tests for system monitoring utilities
"""
import pytest
from unittest.mock import patch, mock_open, MagicMock
import psutil

from homehelper.utils.system_monitor import SystemMonitor


class TestSystemMonitor:
    """Test system monitoring functionality"""
    
    def setup_method(self):
        """Setup test instance"""
        self.monitor = SystemMonitor()
    
    @patch('psutil.cpu_percent')
    @patch('os.getloadavg')
    @patch('psutil.cpu_count')
    def test_get_cpu_metrics(self, mock_cpu_count, mock_loadavg, mock_cpu_percent):
        """Test CPU metrics collection"""
        mock_cpu_percent.return_value = 25.5
        mock_loadavg.return_value = (0.8, 0.6, 0.9)
        mock_cpu_count.return_value = 4
        
        metrics = self.monitor._get_cpu_metrics()
        
        assert metrics['usage_percent'] == 25.5
        assert metrics['load_avg_1m'] == 0.8
        assert metrics['load_avg_5m'] == 0.6
        assert metrics['load_avg_15m'] == 0.9
        assert metrics['core_count'] == 4
    
    @patch('psutil.virtual_memory')
    def test_get_memory_metrics(self, mock_memory):
        """Test memory metrics collection"""
        mock_memory.return_value = MagicMock(
            total=8 * 1024 * 1024 * 1024,  # 8GB
            used=6 * 1024 * 1024 * 1024,   # 6GB
            available=2 * 1024 * 1024 * 1024,  # 2GB
            percent=75.0,
            free=1 * 1024 * 1024 * 1024    # 1GB
        )
        
        metrics = self.monitor._get_memory_metrics()
        
        assert metrics['total_mb'] == 8192
        assert metrics['used_mb'] == 6144
        assert metrics['available_mb'] == 2048
        assert metrics['percent'] == 75.0
        assert metrics['free_mb'] == 1024
    
    @patch('psutil.disk_usage')
    def test_get_disk_metrics(self, mock_disk):
        """Test disk metrics collection"""
        mock_disk.return_value = MagicMock(
            total=32 * 1024 * 1024 * 1024,  # 32GB
            used=16 * 1024 * 1024 * 1024,   # 16GB
            free=16 * 1024 * 1024 * 1024    # 16GB
        )
        
        metrics = self.monitor._get_disk_metrics()
        
        assert metrics['total_gb'] == 32.0
        assert metrics['used_gb'] == 16.0
        assert metrics['free_gb'] == 16.0
        assert metrics['percent'] == 50.0
    
    @patch('builtins.open', new_callable=mock_open, read_data='45000')
    @patch('pathlib.Path.exists')
    def test_get_temperature_metrics_thermal_zone(self, mock_exists, mock_file):
        """Test temperature reading from thermal zone"""
        mock_exists.return_value = True
        
        metrics = self.monitor._get_temperature_metrics()
        
        assert metrics['cpu_celsius'] == 45.0
    
    @patch('pathlib.Path.exists')
    @patch('psutil.sensors_temperatures')
    def test_get_temperature_metrics_psutil(self, mock_sensors, mock_exists):
        """Test temperature reading from psutil sensors"""
        mock_exists.return_value = False
        mock_sensors.return_value = {
            'cpu_thermal': [MagicMock(current=42.5)]
        }
        
        metrics = self.monitor._get_temperature_metrics()
        
        assert metrics['cpu_thermal_celsius'] == 42.5
    
    @patch('pathlib.Path.exists')
    @patch('psutil.sensors_temperatures')
    def test_get_temperature_metrics_unavailable(self, mock_sensors, mock_exists):
        """Test temperature when no sensors available"""
        mock_exists.return_value = False
        mock_sensors.return_value = {}
        
        metrics = self.monitor._get_temperature_metrics()
        
        assert metrics['cpu_celsius'] is None
    
    @patch('psutil.Process')
    def test_get_process_metrics_success(self, mock_process_class):
        """Test successful process metrics collection"""
        mock_process = MagicMock()
        mock_process.name.return_value = "test_process"
        mock_process.status.return_value = "running"
        mock_process.cpu_percent.return_value = 15.5
        mock_process.memory_info.return_value = MagicMock(rss=100 * 1024 * 1024)  # 100MB
        mock_process.memory_percent.return_value = 5.2
        mock_process.create_time.return_value = 1000000000
        mock_process.num_threads.return_value = 3
        mock_process.cmdline.return_value = ["python", "app.py", "--port", "8101"]
        
        mock_process_class.return_value = mock_process
        
        with patch('time.time', return_value=1000003600):  # 1 hour later
            metrics = self.monitor.get_process_metrics(1234)
        
        assert metrics['pid'] == 1234
        assert metrics['name'] == "test_process"
        assert metrics['status'] == "running"
        assert metrics['cpu_percent'] == 15.5
        assert metrics['memory_mb'] == 100
        assert metrics['memory_percent'] == 5.2
        assert metrics['uptime_seconds'] == 3600
        assert metrics['num_threads'] == 3
        assert metrics['cmdline'] == "python app.py --port"
    
    @patch('psutil.Process')
    def test_get_process_metrics_not_found(self, mock_process_class):
        """Test process metrics when process not found"""
        mock_process_class.side_effect = psutil.NoSuchProcess(1234)
        
        metrics = self.monitor.get_process_metrics(1234)
        
        assert metrics is None
    
    @patch('psutil.process_iter')
    def test_get_processes_by_name(self, mock_process_iter):
        """Test finding processes by name pattern"""
        mock_proc1 = MagicMock()
        mock_proc1.info = {'pid': 1234, 'name': 'homehelper-main'}
        
        mock_proc2 = MagicMock()
        mock_proc2.info = {'pid': 5678, 'name': 'other_process'}
        
        mock_process_iter.return_value = [mock_proc1, mock_proc2]
        
        with patch.object(self.monitor, 'get_process_metrics') as mock_get_metrics:
            mock_get_metrics.return_value = {'pid': 1234, 'name': 'homehelper-main'}
            
            processes = self.monitor.get_processes_by_name("homehelper")
            
            assert len(processes) == 1
            assert processes[0]['pid'] == 1234
            mock_get_metrics.assert_called_once_with(1234)
    
    def test_determine_system_status_good(self):
        """Test system status determination - good health"""
        hardware = {
            "cpu": {"usage_percent": 50},
            "memory": {"percent": 60},
            "disk": {"percent": 70},
            "temperature": {"cpu_celsius": 45}
        }
        processes = []
        
        status = self.monitor._determine_system_status(hardware, processes)
        assert status == "good"
    
    def test_determine_system_status_warning_cpu(self):
        """Test system status determination - CPU warning"""
        hardware = {
            "cpu": {"usage_percent": 85},
            "memory": {"percent": 60},
            "disk": {"percent": 70},
            "temperature": {"cpu_celsius": 45}
        }
        processes = []
        
        status = self.monitor._determine_system_status(hardware, processes)
        assert status == "warning"
    
    def test_determine_system_status_warning_temperature(self):
        """Test system status determination - temperature warning"""
        hardware = {
            "cpu": {"usage_percent": 50},
            "memory": {"percent": 60},
            "disk": {"percent": 70},
            "temperature": {"cpu_celsius": 75}
        }
        processes = []
        
        status = self.monitor._determine_system_status(hardware, processes)
        assert status == "warning"
    
    def test_determine_system_status_error(self):
        """Test system status determination - error condition"""
        hardware = {"error": "Hardware monitoring failed"}
        processes = []
        
        status = self.monitor._determine_system_status(hardware, processes)
        assert status == "error"
