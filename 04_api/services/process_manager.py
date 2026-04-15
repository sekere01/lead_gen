"""
Process Manager Service
Manages the pipeline services (start, stop, restart, status)
"""
import os
import psutil
import logging
from typing import Dict, List, Optional
from datetime import datetime
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ServiceInfo:
    name: str
    script: str
    status: str  # running, stopped, unknown
    pid: Optional[int] = None
    uptime: Optional[int] = None  # seconds
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


class ProcessManager:
    """Manages pipeline service processes."""
    
    def __init__(self):
        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    def get_service_status(self, service_name: str) -> ServiceInfo:
        """Get status of a single service."""
        if service_name not in SERVICES:
            return ServiceInfo(name=service_name, script='', status='unknown')
        
        config = SERVICES[service_name]
        script_path = os.path.join(self.base_dir, config['script'])
        
        # Check if process is running by matching the script name
        for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'create_time']):
            try:
                cmdline = proc.info.get('cmdline', [])
                if cmdline and config['script'] in ' '.join(cmdline):
                    uptime = int(datetime.now().timestamp() - proc.info['create_time'])
                    return ServiceInfo(
                        name=service_name,
                        script=config['script'],
                        status='running',
                        pid=proc.info['pid'],
                        uptime=uptime,
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
        script_path = os.path.join(self.base_dir, config['script'])
        
        # Check if already running
        status = self.get_service_status(service_name)
        if status.status == 'running':
            return {'success': False, 'error': f'Service {service_name} is already running'}
        
        try:
            os.system(f'cd {self.base_dir} && ./{config["script"]} > /dev/null 2>&1 &')
            return {'success': True, 'message': f'Started {service_name}'}
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