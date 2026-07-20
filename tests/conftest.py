import os


# Keep unit tests on SQLite for speed/isolation; MySQL defaults are covered by smoke tests.
os.environ["META_DB_TYPE"] = "sqlite"
os.environ["META_DATABASE_URL"] = ""
