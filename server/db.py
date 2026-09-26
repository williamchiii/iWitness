import os

import psycopg
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ["DATABASE_URL"]


def connect() -> psycopg.Connection:
    return psycopg.connect(DATABASE_URL, connect_timeout=10)
