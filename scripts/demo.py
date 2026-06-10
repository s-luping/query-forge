import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import AppSessionLocal
from models.system import SystemConfig
db = AppSessionLocal()
try:
    row = db.query(SystemConfig).filter(SystemConfig.key == 'EMBEDDING_MODEL_READY').first()
    if row and str(row.value) == 'true':
        print('已下载')
finally:
    db.close()