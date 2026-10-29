"""Configure isolated storage BEFORE any test module imports the application."""
import os,tempfile
from pathlib import Path
_database_dir=tempfile.TemporaryDirectory(prefix='ecologic-tests-')
os.environ['DATABASE_URL']='sqlite:///'+str(Path(_database_dir.name)/'test.db')
os.environ['OPENROUTER_API_KEY']=''
os.environ['ENVIRONMENT']='development'
os.environ['COOKIE_SECURE']='false'

def pytest_sessionfinish(session,exitstatus):
 from backend.db import engine
 engine.dispose()
 _database_dir.cleanup()
