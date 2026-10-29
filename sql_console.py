"""A bounded SELECT language, not a general MySQL command executor."""
from connection import mysql_command, database_sql, database_environment

import json
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent / 'vendor'))
import sqlglot
from sqlglot import exp

from mysql_access import CONTAINER, DatabaseError
from settings import DEFAULTS, SettingsStore

SCHEMAS = ('acore_characters', 'acore_world')
MAX_ROWS = 200
SAFE_NODES = set('''Select From Where Group Having Order Ordered Limit Offset Join Subquery Union Intersect Except
Column Identifier Table TableAlias Alias Star Literal Null Boolean Paren Tuple Distinct EQ NEQ GT GTE LT LTE
And Or Not In Between Like ILike Is Add Sub Mul Div Mod Neg Case If When Exists Count Sum Avg Min Max Coalesce
Abs Round Lower Upper Length Concat Substring Cast DataType DataTypeParam Nullif'''.split())


class QueryError(ValueError):
    pass


def normalize_query(query, schema, tables, row_limit=MAX_ROWS):
    if schema not in SCHEMAS or not isinstance(query, str) or not 1 <= len(query) <= 16000:
        raise QueryError('Choose an allowed database and enter one SELECT query (maximum 16000 characters).')
    # MySQL executable comments are rejected rather than silently interpreting different SQL.
    if any(marker in query for marker in ('/*', '*/', '\\', '\x00')):
        raise QueryError('Block comments, backslash/client commands and NUL bytes are not supported.')
    try:
        statements = sqlglot.parse(query, read='mysql')
    except Exception as exc:
        raise QueryError('Cannot parse that SELECT query. Check its MySQL syntax.') from exc
    if len(statements) != 1 or not isinstance(statements[0], (exp.Select, exp.Union)):
        raise QueryError('Only one SELECT query is allowed; commands and writes are disabled.')
    tree = statements[0]
    nodes = list(tree.walk())
    if len(nodes) > 1000:
        raise QueryError('Query is too complex.')
    for node in nodes:
        if type(node).__name__ not in SAFE_NODES:
            raise QueryError(f'Unsupported SQL construct: {type(node).__name__}. Only read-only SELECTs are allowed.')
        node.comments = None
        if isinstance(node, exp.Identifier) and not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', node.this):
            raise QueryError('Identifiers must use letters, digits and underscores.')
        if isinstance(node, exp.Table):
            database = node.db or schema
            if node.catalog or (database, node.name) not in tables:
                raise QueryError('That table/view is unavailable under the current policy '
                                 'or outside the game databases.')
            node.set('db', exp.to_identifier(database))
        if isinstance(node, exp.Column) and (node.catalog or (node.db and node.db not in SCHEMAS)):
            raise QueryError('Privileged schemas are unavailable.')
    # Reserialize the validated AST. Raw user text never enters the MySQL client input stream.
    sql = tree.sql(dialect='mysql', identify=True, comments=False)
    suffix = f' LIMIT {row_limit + 1}' if row_limit is not None else ''
    return f'SELECT * FROM ({sql}) AS dashboard_result' + suffix


def execute_select(sql, row_limit=MAX_ROWS, execution_timeout=True):
    # PREPARE accepts one statement. A hex string prevents MySQL client commands and delimiter injection.
    encoded = database_sql(sql).encode('utf-8').hex()
    script = f'''SET SESSION TRANSACTION READ ONLY;
SET SESSION sql_mode='STRICT_TRANS_TABLES,NO_ENGINE_SUBSTITUTION';
SET SESSION MAX_EXECUTION_TIME={3000 if execution_timeout else 0};
SET SESSION lock_wait_timeout=2;
START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY;
SET @dashboard_sql=CONVERT(0x{encoded} USING utf8mb4);
PREPARE dashboard_read FROM @dashboard_sql;
EXECUTE dashboard_read;
DEALLOCATE PREPARE dashboard_read;
COMMIT;
'''
    command = mysql_command(xml=True)
    try:
        result = subprocess.run(command, env=database_environment(), input=script, text=True, encoding='utf-8', capture_output=True,
                                timeout=8 if execution_timeout else None, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise QueryError('Database unavailable or query timed out.') from exc
    if result.returncode:
        code = re.search(r'ERROR (\d+)', result.stderr)
        suffix = f' (MySQL {code[1]})' if code else ''
        raise QueryError('Query rejected or timed out' + suffix + '. Check table/column names and SELECT syntax.')
    if len(result.stdout) > 2_000_000:
        raise QueryError('Result too large. Select fewer columns or shorter text fields.')
    try:
        root = ET.fromstring(result.stdout)
        records = root.findall('row')
        columns = [field.attrib['name'] for field in records[0]] if records else []
        if len(columns) > 200:
            raise QueryError('Select at most 200 result columns.')
        values = [[None if field.attrib.get('{http://www.w3.org/2001/XMLSchema-instance}nil') == 'true'
                   else (field.text or '') for field in row] for row in records[:row_limit]]
        
        from connection import schema
        reverse = {schema(n): 'acore_' + n for n in ('characters', 'world')}
        for index, column in enumerate(columns):
            if column == 'TABLE_SCHEMA':
                for row in values: row[index] = reverse.get(row[index], row[index])
        return {'columns': columns, 'rows': values,
                'truncated': row_limit is not None and len(records) > row_limit, 'limit': row_limit}
    except ET.ParseError as exc:
        raise QueryError('Unexpected database result format.') from exc


class SqlConsole:
    def __init__(self, catalog_reader=None, executor=execute_select, settings=None):
        self.catalog_reader = catalog_reader or (lambda sql: execute_select(sql, row_limit=3000))
        self.executor = executor
        self.lock = threading.Lock()
        self.catalog_time = float('-inf')
        self.tables = set()
        self.settings = settings or SettingsStore()
        self.catalog_base_only = None

    def catalog(self, policy=None):
        policy = policy or self.settings.get()['sql']
        base_only = policy['base_tables_only']
        with self.lock:
            if time.monotonic() - self.catalog_time > 60 or self.catalog_base_only != base_only:
                # Trusted metadata query; never accepts a browser-supplied identifier.
                sql = ("SELECT TABLE_SCHEMA,TABLE_NAME FROM information_schema.TABLES "
                       "WHERE TABLE_SCHEMA IN ('acore_characters','acore_world')")
                if base_only:
                    sql += " AND TABLE_TYPE='BASE TABLE'"
                result = self.catalog_reader(sql)
                self.tables = {tuple(row) for row in result['rows']}
                self.catalog_time = time.monotonic()
                self.catalog_base_only = base_only
            return sorted(self.tables)

    def run(self, query, schema):
        policy = self.settings.get()['sql']
        tables = self.catalog(policy)
        row_limit = MAX_ROWS if policy['row_limit'] else None
        normalized = normalize_query(query, schema, set(tables), row_limit=row_limit)
        if not self.lock.acquire(blocking=False):
            raise QueryError('Another query is running; try again when it finishes.')
        try:
            started = time.monotonic()
            result = self.executor(normalized, row_limit=row_limit, execution_timeout=policy['execution_timeout'])
            result['duration_ms'] = round((time.monotonic() - started) * 1000)
            result['policy'] = policy
            return result
        finally:
            self.lock.release()
