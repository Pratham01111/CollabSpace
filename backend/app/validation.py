"""Bounds shared by request schemas and path parameters.

Primary keys are Postgres ``integer`` (int4). A larger id cannot exist, and
passing one to the database is an error rather than "no rows", so ids are
bounded before they get that far: out of range is a 422, not a 500.
"""

MAX_ID = 2**31 - 1

# Task text limits. Titles match the column; descriptions are TEXT in the
# database, but one request should not be able to store megabytes.
MAX_TITLE_LENGTH = 255
MAX_DESCRIPTION_LENGTH = 10_000
