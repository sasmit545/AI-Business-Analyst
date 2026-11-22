"""Fail-closed AST policy for application-generated PostgreSQL only."""
import re
import sqlglot
from sqlglot import exp

from app.context.catalog import catalog

ALLOWED_NODES = frozenset('''Select Alias Column Identifier Table From Join Where And Or Not
EQ NEQ GT GTE LT LTE Is In Literal Boolean Null Star Count Sum Min Max Filter
Case If Cast DataType Paren Group Order Ordered Limit Subquery Distinct
Add Sub Mul Div Neg Coalesce Anonymous RegexpLike Placeholder AtTimeZone
DateTrunc TimeToStr Var TableAlias Interval Nullif Having DateBin Offset'''.split())
FUNCTIONS = {'pg_input_is_valid', 'date_bin'}


def validate_sql(sql: str, scenario: str):
    try:
        trees = sqlglot.parse(re.sub(r'%\((\w+)\)s', r':\1', sql), read='postgres')
    except sqlglot.errors.ParseError as exc:
        raise ValueError('SQL parsing failed') from exc
    if len(trees) != 1 or not isinstance(trees[0], exp.Select):
        raise ValueError('Only one registered SELECT is permitted')
    allowed_tables = set(catalog(scenario)['tables'])
    for node in trees[0].walk():
        if type(node).__name__ not in ALLOWED_NODES:
            raise ValueError(f'Unsupported SQL node: {type(node).__name__}')
        if isinstance(node, exp.Table):
            if node.catalog or node.db != scenario or node.name not in allowed_tables:
                raise ValueError('Relation outside selected scope')
        if isinstance(node, exp.Anonymous) and node.name.lower() not in FUNCTIONS:
            raise ValueError('Function not allowed')
    return trees[0]
