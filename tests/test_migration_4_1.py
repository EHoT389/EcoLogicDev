"""Upgrade old local tables without replacing existing records."""
import json
from sqlalchemy import create_engine,text,inspect
from backend import db


def test_additive_upgrade_preserves_old_projects_and_backfills_zone_memory(tmp_path,monkeypatch):
    engine=create_engine('sqlite:///'+str(tmp_path/'legacy.db'))
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE projects (id VARCHAR PRIMARY KEY, owner_id VARCHAR, assigned_to VARCHAR, name VARCHAR, payload TEXT, result TEXT, updated VARCHAR)'))
        connection.execute(text('CREATE TABLE ai_messages (id VARCHAR PRIMARY KEY, owner_id VARCHAR, question TEXT, answer TEXT, created FLOAT)'))
        connection.execute(text("INSERT INTO projects VALUES ('old','owner',NULL,'Old project','{}','{}','2026-10-29')"))
        connection.execute(text('INSERT INTO ai_messages VALUES (:id,:owner,:question,:answer,:created)'),
                           {'id':'message','owner':'owner','question':json.dumps({'kind':'zone_message_v1','zone_id':'osm-way-12','text':'old question'}),'answer':'old answer','created':1.})
    monkeypatch.setattr(db,'engine',engine)
    db.init_db();db.init_db()
    with engine.connect() as connection:
        assert {'map_state'}.issubset({column['name'] for column in inspect(connection).get_columns('projects')})
        assert connection.execute(text("SELECT name, map_state FROM projects WHERE id='old'")).one()==('Old project',None)
        assert connection.execute(text("SELECT answer,zone_id,context FROM ai_messages WHERE id='message'")).one()==('old answer','osm-way-12','{}')
    engine.dispose()
