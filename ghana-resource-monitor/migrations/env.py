from alembic import context
from sqlalchemy import create_engine

from db.models import Base

config = context.config
target_metadata = Base.metadata


def run_migrations_online():
    engine = create_engine(config.get_main_option("sqlalchemy.url"))
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


run_migrations_online()
