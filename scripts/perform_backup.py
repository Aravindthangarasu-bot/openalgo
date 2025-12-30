import shutil
import os
import datetime

def create_backup():
    # Configuration
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    source_dir = os.path.dirname(os.path.abspath(__file__)) # Assumes script is in root or scripts/
    if source_dir.endswith('scripts'):
         source_dir = os.path.dirname(source_dir) # Go up one level to root 'openalgo'
    
    # Destination: ../backups/backup_YYYYMMDD_HHMMSS
    backup_root = os.path.join(os.path.dirname(source_dir), 'backups')
    backup_dir = os.path.join(backup_root, f'backup_{timestamp}')
    
    print(f"Source: {source_dir}")
    print(f"Destination: {backup_dir}")
    
    # Ignore patterns
    ignore_patterns = shutil.ignore_patterns(
        'venv', 
        '__pycache__', 
        '.git', 
        'node_modules', 
        '*.pyc', 
        '.DS_Store',
        'test_output.log',
        'test_output_2.log',
        'app.log' # Optional: Skip large logs
    )
    
    try:
        if not os.path.exists(backup_root):
            os.makedirs(backup_root)
            
        shutil.copytree(source_dir, backup_dir, ignore=ignore_patterns)
        print(f"✅ Backup created successfully at: {backup_dir}")
        return backup_dir
    except Exception as e:
        print(f"❌ Backup failed: {e}")
        return None

if __name__ == "__main__":
    create_backup()
