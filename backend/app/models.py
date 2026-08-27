"""
Your schema goes here.

Nothing is prescribed. Design the tables you think this data deserves, with the
keys, constraints, nullability and indexes you think it needs. We read this file
first and it carries the most marks in the exercise.

Create the tables however you like: `Base.metadata.create_all(engine)` from a
script is fine, an Alembic migration is fine, raw SQL in a .sql file is fine.
We are grading the schema, not the migration tool.
"""

from .db import Base  # noqa: F401

# TODO: your models
