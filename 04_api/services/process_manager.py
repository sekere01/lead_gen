"""
Process Manager Service
Manages the pipeline services (start, stop, restart, status)
"""
import os
import subprocess
import psutil
import logging
from typing import Dict, List, Optional
from datetime import datetime
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ServiceInfo:
    name: str
    script: str
    status: str  # running, stopped, unknown
    pid: Optional[int] = None
    uptime: Optional[int] = None  # seconds since started
    start_time: Optional[float] = None  # timestamp when service started
    last_seen: Optional[datetime] = None


# Service configuration
SERVICES = {
    'discovery': {
        'script': 'run_discovery.sh',
        'port': None,
    },
    'browsing': {
        'script': 'run_browsing.sh',
        'port': None,
    },
    'enrichment': {
        'script': 'run_enrichment.sh',
        'port': None,
    },
    'verification': {
        'script': 'run_verification.sh',
        'port': None,
    },
}

# Track service start timestamps
service_start_times: Dict[str, float] = {}


class ProcessManager:
    """Manages pipeline service processes."""
    
    def __init__(self):
        # Path to process_manager.py is /04_api/services/process_manager.py
        # We need to go up 2 levels to get to project root
        self.services_dir = os.path.dirname(os.path.abspath(__file__))
        self.api_dir = os.path.dirname(self.services_dir)
        self.project_dir = os.path.dirname(self.api_dir)
        self.running_processes: Dict[str, subprocess.Popen] = {}
        
        # Scan for any existing service processes on boot
        self.scan_existing_processes()
    
    def scan_existing_processes(self):
        """Scan for already running service processes."""
        for service_name, config in SERVICES.items():
            try:
                result = subprocess.run(
                    ['pgrep', '-f', config['script']],
                    capture_output=True,
                    text=True
                )
                if result.stdout.strip():
                    pid = int(result.stdout.strip().split()[0])
                    self.running_processes[service_name] = None  # We didn't start it, but it's running
                    service_start_times[service_name] = datetime.now().timestamp()
                    logger.info(f"Scanned existing {service_name} (PID: {pid})")
            except Exception as e:
                pass
    
    def get_service_status(self, service_name: str) -> ServiceInfo:
        """Get status of a single service."""
        if service_name not in SERVICES:
            return ServiceInfo(name=service_name, script='', status='unknown')
        
        config = SERVICES[service_name]
        script_path = os.path.join(self.project_dir, config['script'])
        
        # Check if process is running by matching the script name
        for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'create_time']):
            try:
                cmdline = proc.info.get('cmdline', [])
                if cmdline and config['script'] in ' '.join(cmdline):
                    uptime = int(datetime.now().timestamp() - proc.info['create_time'])
                    start_time = service_start_times.get(service_name)
                    return ServiceInfo(
                        name=service_name,
                        script=config['script'],
                        status='running',
                        pid=proc.info['pid'],
                        uptime=uptime,
                        start_time=start_time,
                        last_seen=datetime.now()
                    )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        
        return ServiceInfo(
            name=service_name,
            script=config['script'],
            status='stopped',
            pid=None,
            uptime=None,
            start_time=None,
            last_seen=None
        )
    
    def get_all_services_status(self) -> List[ServiceInfo]:
        """Get status of all services."""
        return [self.get_service_status(name) for name in SERVICES.keys()]
    
    def start_service(self, service_name: str) -> Dict:
        """Start a service."""
        if service_name not in SERVICES:
            return {'success': False, 'error': f'Unknown service: {service_name}'}
        
        config = SERVICES[service_name]
        script_path = os.path.join(self.project_dir, config['script'])
        
        # Kill any existing orphan process by script name
        try:
            subprocess.run(
                ['pkill', '-9', '-f', config['script']],
                capture_output=True
            )
        except Exception:
            pass
        
        time.sleep(0.5)
        
        try:
            # Ensure script is executable
            os.chmod(script_path, 0o755)
            
            # Log file path
            log_file = f'/tmp/{service_name}.out'
            
            # Start the service - fire and forget, return immediately
            with open(log_file, 'a') as log_out:
                process = subprocess.Popen(
                    [f'./{config["script"]}'],
                    cwd=self.project_dir,
                    stdout=log_out,
                    stderr=subprocess.STDOUT,
                    start_new_session=True
                )
            
            # Store process reference
            self.running_processes[service_name] = process
            
            # Record start timestamp - let dashboard poll pick up actual status
            service_start_times[service_name] = datetime.now().timestamp()
            return {'success': True, 'message': f'Started {service_name}', 'log_file': log_file}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def stop_service(self, service_name: str) -> Dict:
        """Stop a service."""
        if service_name not in SERVICES:
            return {'success': False, 'error': f'Unknown service: {service_name}'}
        
        status = self.get_service_status(service_name)
        if status.status != 'running' or not status.pid:
            return {'success': False, 'error': f'Service {service_name} is not running'}
        
        try:
            os.kill(status.pid, 9)
            # Remove start timestamp
            if service_name in service_start_times:
                del service_start_times[service_name]
            return {'success': True, 'message': f'Stopped {service_name}'}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def restart_service(self, service_name: str) -> Dict:
        """Restart a service."""
        result = self.stop_service(service_name)
        if not result.get('success'):
            return result
        return self.start_service(service_name)
    
    def get_health_status(self) -> Dict:
        """Get overall pipeline health."""
        services = self.get_all_services_status()
        running = sum(1 for s in services if s.status == 'running')
        total = len(services)
        
        health = 'healthy' if running >= 1 else 'unhealthy'
        return {
            'health': health,
            'services_running': running,
            'services_total': total,
            'services': [
                {
                    'name': s.name,
                    'status': s.status,
                    'uptime': s.uptime
                }
                for s in services
            ]
        }
    
    def refresh_status(self) -> Dict:
        """Refresh service status cache."""
        # Status is always fresh because get_service_status checks psutil each time
        return {'success': True}


process_manager = ProcessManager()