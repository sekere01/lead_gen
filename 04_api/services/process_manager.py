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
from signal import SIGTERM

logger = logging.getLogger(__name__)

# Lock directory for atomic service start
LOCK_DIR = '/tmp/leadgen_locks'

# Mode file path
MODE_FILE = '/tmp/leadgen_control_mode'


@dataclass
class ServiceInfo:
    name: str
    script: str
    status: str  # running, stopped, unknown
    pid: Optional[int] = None
    uptime: Optional[int] = None  # seconds since started
    start_time: Optional[float] = None  # timestamp when service started
    last_seen: Optional[datetime] = None


# Service configuration with service_dir for correct cwd resolution
SERVICES = {
    'discovery': {
        'script': 'run_discovery.sh',
        'service_dir': '01_discovery',
        'port': None,
    },
    'browsing': {
        'script': 'run_browsing.sh',
        'service_dir': '01b_browsing',
        'port': None,
    },
    'enrichment': {
        'script': 'run_enrichment.sh',
        'service_dir': '02_enrichment',
        'port': None,
    },
    'verification': {
        'script': 'run_verification.sh',
        'service_dir': '03_verification',
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
        """Scan for already running service processes using dual detection."""
        for service_name, config in SERVICES.items():
            try:
                # Method 1: Match by script name
                result = subprocess.run(
                    ['pgrep', '-f', config['script']],
                    capture_output=True,
                    text=True
                )
                if result.stdout.strip():
                    pid = int(result.stdout.strip().split()[0])
                    self.running_processes[service_name] = None
                    service_start_times[service_name] = datetime.now().timestamp()
                    logger.info(f"Scanned existing {service_name} (PID: {pid}) via script")
                    continue
                
                # Method 2: Match by service_dir/main.py pattern
                result = subprocess.run(
                    ['pgrep', '-f', f"{config['service_dir']}/venv/bin/python main.py"],
                    capture_output=True,
                    text=True
                )
                if result.stdout.strip():
                    pid = int(result.stdout.strip().split()[0])
                    self.running_processes[service_name] = None
                    service_start_times[service_name] = datetime.now().timestamp()
                    logger.info(f"Scanned existing {service_name} (PID: {pid}) via main.py")
            except Exception as e:
                pass
    
    def get_service_status(self, service_name: str) -> ServiceInfo:
        """Get status of a single service."""
        if service_name not in SERVICES:
            return ServiceInfo(name=service_name, script='', status='unknown')
        
        config = SERVICES[service_name]
        
        # Dual method process detection
        for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'create_time']):
            try:
                cmdline = proc.info.get('cmdline', [])
                if not cmdline:
                    continue
                cmdline_str = ' '.join(cmdline)
                
                # Method 1: Match by script name
                if config['script'] in cmdline_str:
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
                
                # Method 2: Match by service_dir/main.py pattern
                if f"{config['service_dir']}/venv/bin/python" in cmdline_str and 'main.py' in cmdline_str:
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
        """Start a service with atomic lock to prevent duplicates."""
        if service_name not in SERVICES:
            return {'success': False, 'error': f'Unknown service: {service_name}'}
        
        config = SERVICES[service_name]
        script_path = os.path.join(self.project_dir, config['service_dir'], config['script'])
        service_dir = os.path.join(self.project_dir, config['service_dir'])
        
        # Ensure lock directory exists
        os.makedirs(LOCK_DIR, exist_ok=True)
        lock_file = f'{LOCK_DIR}/{service_name}.lock'
        
        # Try to acquire atomic lock (O_EXCL = exclusive creation)
        try:
            fd = os.open(lock_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
        except FileExistsError:
            # Lock exists - check if holder is still alive
            stale = False
            try:
                with open(lock_file, 'r') as f:
                    lock_pid = int(f.read().strip())
                # check if process exists (signal 0 = don't send, just check)
                try:
                    os.kill(lock_pid, 0)
                except OSError:
                    stale = True
                    os.unlink(lock_file)
            except (ValueError, FileNotFoundError):
                stale = True
            
            if not stale:
                return {'success': False, 'error': f'Service {service_name} start already in progress (PID: {lock_pid})'}
            # Stale lock removed - try again
            try:
                fd = os.open(lock_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
            except Exception:
                return {'success': False, 'error': f'Could not acquire lock for {service_name}'}
        
        try:
            # Kill any existing orphan process by script name
            try:
                subprocess.run(
                    ['pkill', '-9', '-f', config['script']],
                    capture_output=True
                )
            except Exception:
                pass
            
            # Also kill by main.py pattern
            try:
                subprocess.run(
                    ['pkill', '-9', '-f', f"{config['service_dir']}/venv/bin/python main.py"],
                    capture_output=True
                )
            except Exception:
                pass
            
            time.sleep(0.5)
            
            # Ensure script is executable
            os.chmod(script_path, 0o755)
            
            # Log file path
            log_file = f'/tmp/{service_name}.out'
            
            # Start the service from the service directory (correct cwd)
            with open(log_file, 'a') as log_out:
                process = subprocess.Popen(
                    [f'./{config["script"]}'],
                    cwd=service_dir,
                    stdout=log_out,
                    stderr=subprocess.STDOUT,
                    start_new_session=True
                )
            
            # Store process reference
            self.running_processes[service_name] = process
            
            # Record start timestamp
            service_start_times[service_name] = datetime.now().timestamp()
            
            # Update lock file with actual service PID (not our PID)
            try:
                with open(lock_file, 'w') as f:
                    f.write(str(process.pid))
            except:
                pass
            
            return {'success': True, 'message': f'Started {service_name}', 'log_file': log_file}
            
        except Exception as e:
            # Release lock on failure
            if os.path.exists(lock_file):
                try:
                    os.unlink(lock_file)
                except:
                    pass
            return {'success': False, 'error': str(e)}
    
    def stop_service(self, service_name: str) -> Dict:
        """Stop a service."""
        if service_name not in SERVICES:
            return {'success': False, 'error': f'Unknown service: {service_name}'}
        
        # Remove lock file if exists
        lock_file = f'{LOCK_DIR}/{service_name}.lock'
        if os.path.exists(lock_file):
            try:
                os.unlink(lock_file)
            except:
                pass
        
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
        time.sleep(1)
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
    
    def get_mode(self) -> str:
        """Get current control mode: 'api' (manual) or 'systemd' (auto)."""
        try:
            if os.path.exists(MODE_FILE):
                with open(MODE_FILE, 'r') as f:
                    mode = f.read().strip()
                    if mode in ('api', 'systemd'):
                        return mode
        except Exception:
            pass
        return 'api'  # Default to manual/API control
    
    def set_mode(self, mode: str) -> Dict:
        """Set control mode and apply changes."""
        if mode not in ('api', 'systemd'):
            return {'success': False, 'error': f'Invalid mode: {mode}. Must be "api" or "systemd"'}
        
        try:
            os.makedirs(os.path.dirname(MODE_FILE) if os.path.dirname(MODE_FILE) else '.', exist_ok=True)
            with open(MODE_FILE, 'w') as f:
                f.write(mode)
            
            # Use absolute paths to avoid PATH issues in subprocess
            SUDO = '/usr/bin/sudo'
            SYSTEMCTL = '/bin/systemctl'
            
            systemd_warning = None
            try:
                if mode == 'systemd':
                    for svc in ['discovery', 'browsing', 'enrichment', 'verification']:
                        status = self.get_service_status(svc)
                        if status.status == 'running':
                            result = subprocess.run([SUDO, SYSTEMCTL, 'enable', f'leadgen-{svc}'], capture_output=True, check=False)
                            if result.returncode != 0:
                                logger.warning(f"Failed to enable leadgen-{svc}: {result.stderr.decode()}")
                        else:
                            subprocess.run([SUDO, SYSTEMCTL, 'enable', f'leadgen-{svc}'], capture_output=True, check=False)
                            result = subprocess.run([SUDO, SYSTEMCTL, 'start', f'leadgen-{svc}'], capture_output=True, check=False)
                            if result.returncode != 0:
                                logger.warning(f"Failed to start leadgen-{svc}: {result.stderr.decode()}")
                else:
                    for svc in ['discovery', 'browsing', 'enrichment', 'verification']:
                        result = subprocess.run([SUDO, SYSTEMCTL, 'stop', f'leadgen-{svc}'], capture_output=True, check=False)
                        if result.returncode != 0:
                            logger.warning(f"Failed to stop leadgen-{svc}: {result.stderr.decode()}")
                        result = subprocess.run([SUDO, SYSTEMCTL, 'disable', f'leadgen-{svc}'], capture_output=True, check=False)
                        if result.returncode != 0:
                            logger.warning(f"Failed to disable leadgen-{svc}: {result.stderr.decode()}")
            except FileNotFoundError as e:
                systemd_warning = f'Mode saved, but systemd commands skipped: {e}'
            
            result = {'success': True, 'mode': mode}
            if systemd_warning:
                result['warning'] = systemd_warning
            return result
        except Exception as e:
            return {'success': False, 'error': str(e)}


process_manager = ProcessManager()
