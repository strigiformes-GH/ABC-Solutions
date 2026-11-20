# connect alembic to the db config/models


from alembic import context
from sqlalchemy import create_engine, pool
from config import Config
from database.create_db import db
import models  # populate tables

target_metadata = db.metadata

if context.is_offline_mode():
    context.configure(url=Config.SQLALCHEMY_DATABASE_URI, target_metadata=target_metadata,
                      literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(Config.SQLALCHEMY_DATABASE_URI, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata,
                          compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
