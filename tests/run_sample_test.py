#!/usr/bin/env python3
"""Insert 50 classic Python bug test samples into BugVault, then test retrieval."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

# ── Point to the project root ──────────────────────────────────────
# This script is designed to run via ``uv run python tests/run_sample_test.py``.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ── Must import stdout_guard BEFORE anything else ─────────────────
from bugvault.utils.stdout_guard import _MCPStdoutProxy  # noqa: F401

import asyncio
from concurrent.futures import ThreadPoolExecutor

from bugvault.config import settings
from bugvault.database.lancedb_client import LanceDBClient
from bugvault.models.bug_record import BugRecord
from bugvault.services.archive_svc import write_markdown_archive
from bugvault.services.ingestion_svc import validate_and_prepare
from bugvault.services.embedding_svc import EmbeddingService
from bugvault.services.retrieval_svc import rerank
from bugvault.utils.logger import logger


# ===================================================================
#  50 Classic Python Bug Samples
# ===================================================================

SAMPLES: list[dict] = [
    # ── TypeError ──────────────────────────────────────────────────
    dict(
        bug_title="TypeError: unsupported operand type(s) for +: int and str",
        error_log_snippet="TypeError: unsupported operand type(s) for +: 'int' and 'str'\n  File 'app.py', line 42, in calculate_total\n    result = price + quantity\n  File 'app.py', line 40, in calculate_total\n    price = get_price()  # returns int\n    quantity = get_quantity()  # returns str",
        tried_methods="Used type() to debug variable types; tried int(quantity) conversion",
        final_solution="Ensure quantity is cast to int() before arithmetic: result = price + int(quantity). Add runtime type checking with isinstance().",
        root_cause="Function get_quantity() returns a string instead of int; no type hint or validation at the boundary.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    dict(
        bug_title="TypeError: 'NoneType' object is not subscriptable",
        error_log_snippet="TypeError: 'NoneType' object is not subscriptable\n  File 'api/handler.py', line 28, in process_response\n    data = response['data']\n  File 'api/handler.py', line 25, in process_response\n    response = fetch_from_cache(cache_key)",
        tried_methods="Added print(response) to debug; checked if response is None before access",
        final_solution="Add None check before subscript access: if response is None: return default; data = response.get('data', [])",
        root_cause="fetch_from_cache returns None on cache miss; caller assumed non-None return without defensive check.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    dict(
        bug_title="TypeError: can only concatenate str (not 'int') to str",
        error_log_snippet="TypeError: can only concatenate str (not 'int') to str\n  File 'views.py', line 15, in render_summary\n    message = 'User ' + user_id + ' has ' + score + ' points'\n  File 'views.py', line 12, in render_summary\n    score = compute_score(user_id)",
        tried_methods="Used f-string instead; tried str(score); checked compute_score return type",
        final_solution="Use formatted string: message = f'User {user_id} has {score} points'. Or explicitly cast: str(score).",
        root_cause="Assumed all variables in concatenation are strings; score is an int from compute_score.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    dict(
        bug_title="TypeError: missing 1 required positional argument",
        error_log_snippet="TypeError: __init__() missing 1 required positional argument: 'timeout'\n  File 'client.py', line 55, in make_request\n    conn = APIConnection(url, retries=3)\nAPIConnection.__init__ defined at connection.py:10 with signature (self, url, timeout, retries=3)",
        tried_methods="Checked APIConnection constructor signature; added timeout parameter",
        final_solution="Update call to include timeout: conn = APIConnection(url, timeout=10, retries=3). Review constructor required params.",
        root_cause="Constructor signature changed to require timeout parameter; calling code was not updated to match.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    dict(
        bug_title="TypeError: 'int' object is not iterable",
        error_log_snippet="TypeError: 'int' object is not iterable\n  File 'utils.py', line 33, in flatten\n    for item in data:\n  File 'main.py', line 22, in process\n    result = flatten(get_counts())",
        tried_methods="Printed data type with type(); wrapped data in [data] list",
        final_solution="Check if data is iterable before loop: if not isinstance(data, Iterable): data = [data]. Or fix return type of get_counts() to always return a list.",
        root_cause="get_counts() returns a single int when there is only one count, but flatten() expects a list.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    # ── ValueError ─────────────────────────────────────────────────
    dict(
        bug_title="ValueError: invalid literal for int() with base 10",
        error_log_snippet="ValueError: invalid literal for int() with base 10: 'abc123'\n  File 'import.py', line 12, in parse_user_id\n    user_id = int(raw_id)\n  File 'import.py', line 8, in parse_user_id\n    raw_id = row[2].strip()  # often has text like 'ABC123'",
        tried_methods="Added print(raw_id) to see the actual value; tried regex to extract digits only",
        final_solution="Use try/except with fallback: try: user_id = int(raw_id) except ValueError: user_id = 0. Or validate with str.isdigit() first.",
        root_cause="Raw input contains non-numeric characters; caller assumed data is always purely numeric.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    dict(
        bug_title="ValueError: too many values to unpack (expected 2)",
        error_log_snippet="ValueError: too many values to unpack (expected 2)\n  File 'parser.py', line 28, in parse_line\n    key, value = line.split('=')\n  File 'config.py', line 45, in load_config\n    options = [parse_line(l) for l in lines]",
        tried_methods="Printed line.split('=') to inspect; tried using line.split('=', 1)",
        final_solution="Use maxsplit parameter: key, value = line.split('=', 1). This ensures only the first '=' splits, preserving values that contain '='.",
        root_cause="Config values can contain '=' characters; split() without maxsplit produces more than 2 elements.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    dict(
        bug_title="ValueError: not enough values to unpack (expected 3, got 2)",
        error_log_snippet="ValueError: not enough values to unpack (expected 3, got 2)\n  File 'data_loader.py', line 15, in parse_csv_row\n    name, age, city = row.split(',')\n  File 'data_loader.py', line 10, in load_data\n    parsed = [parse_csv_row(r) for r in raw_data]",
        tried_methods="Added validation for row.count(','); tried padding the list",
        final_solution="Handle variable-length rows: parts = row.split(','); name = parts[0]; age = parts[1] if len(parts) > 1 else ''; city = parts[2] if len(parts) > 2 else ''",
        root_cause="CSV rows have variable column counts; unpacking assumes fixed schema with no missing fields.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    dict(
        bug_title="ValueError: need more than 1 value to unpack",
        error_log_snippet="ValueError: need more than 1 value to unpack\n  File 'geometry.py', line 8, in parse_point\n    x, y = point.split(',')\n  Input: '42' (single coordinate)",
        tried_methods="Checked point value before split; added length guard",
        final_solution="Validate before unpacking: if ',' not in point: return (point, 0); x, y = point.split(',')",
        root_cause="Some entries in input data contain single values but code always expects 2+.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    dict(
        bug_title="ValueError: I/O operation on closed file",
        error_log_snippet="ValueError: I/O operation on closed file.\n  File 'file_processor.py', line 40, in read_remaining\n    content = f.read()\n  File 'file_processor.py', line 35, in process\n    with open(path) as f:\n        header = f.readline()\n    # f is now closed outside 'with' block",
        tried_methods="Moved read_remaining() call inside the with block; checked f.closed",
        final_solution="Ensure all file operations happen inside the 'with' block: with open(path) as f: header = f.readline(); content = read_remaining(f). Do not reference f outside 'with'.",
        root_cause="File object is referenced outside its context manager ('with' block); it gets auto-closed on block exit.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    # ── AttributeError ─────────────────────────────────────────────
    dict(
        bug_title="AttributeError: 'NoneType' object has no attribute 'text'",
        error_log_snippet="AttributeError: 'NoneType' object has no attribute 'text'\n  File 'scraper.py', line 55, in extract_data\n    title = soup.find('title').text\n  File 'scraper.py', line 50, in parse_page\n    result = extract_data(html_content)",
        tried_methods="Printed soup.find('title') to debug; tried checking if result is None",
        final_solution="Check before access: title_tag = soup.find('title'); title = title_tag.text if title_tag else ''",
        root_cause="soup.find() returns None when element is not found; chaining .text on None causes AttributeError.",
        project_name="sample-python",
        tech_stack="Python, BeautifulSoup",
    ),
    dict(
        bug_title="AttributeError: module 'x' has no attribute 'y'",
        error_log_snippet="AttributeError: module 'utils' has no attribute 'parse_config'\n  File 'main.py', line 5\n    from utils import parse_config\n  File 'utils/__init__.py', line 2\n    from .parser import parse_config\n  File 'utils/parser.py', line 1\n    import utils  # circular import",
        tried_methods="Checked utils/parser.py for function definition; removed circular import",
        final_solution="Remove circular imports: use 'from utils.parser import parse_config' in __init__.py, or move imports inside functions. Never import the parent package from a submodule.",
        root_cause="Circular import caused parse_config to be undefined at import time; the module wasn't fully initialized yet.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    dict(
        bug_title="AttributeError: 'str' object has no attribute 'append'",
        error_log_snippet="AttributeError: 'str' object has no attribute 'append'\n  File 'builder.py', line 22, in build_query\n    query.append(f'AND {condition}')\n  File 'builder.py', line 18, in build_query\n    query = 'SELECT * FROM users'  # initialized as string",
        tried_methods="Printed type(query) to debug; tried using += instead of append()",
        final_solution="Initialize as list: query_parts = ['SELECT * FROM users']; query_parts.append(f'AND {condition}'); final = ' '.join(query_parts)",
        root_cause="Variable initialized as a string (immutable, no .append()) but used as if it were a list.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    dict(
        bug_title="AttributeError: 'dict' object has no attribute 'append'",
        error_log_snippet="AttributeError: 'dict' object has no attribute 'append'\n  File 'data_mapper.py', line 35\n    config.append(new_rule)\nconfig is a dict at line 30: config = load_config()  # returns dict",
        tried_methods="Printed type(config); tried config.update() instead",
        final_solution="Use dict methods: config[new_rule_key] = new_rule_value or config.update(new_rules_dict). Differentiate between lists and dicts.",
        root_cause="Confused dict and list APIs; .append() is a list method, not a dict method.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    dict(
        bug_title="AttributeError: partially initialized module has no attribute",
        error_log_snippet="AttributeError: partially initialized module 'app' has no attribute 'config' (most likely due to circular import)\n  File 'app/__init__.py', line 3\n    from .routes import init_routes\n  File 'app/routes.py', line 5\n    from app import config  # config not yet defined in __init__.py",
        tried_methods="Moved config definition before imports; used lazy import inside function",
        final_solution="Define config in a separate module (app/config.py), or use lazy import: def get_db(): from app import config; return config.DB_PATH",
        root_cause="Circular import causes partial initialization; attribute not yet assigned when the dependent module tries to import it.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    # ── IndexError ─────────────────────────────────────────────────
    dict(
        bug_title="IndexError: list index out of range",
        error_log_snippet="IndexError: list index out of range\n  File 'csv_reader.py', line 20\n    first_name = row[1]\nrow is ['Alice'] (length 1) at csv_reader.py:18",
        tried_methods="Printed len(row) to debug; tried using row[0] instead",
        final_solution="Check bounds before access: if len(row) > 1: first_name = row[1] else: first_name = ''. Use row.get() for dict-like access patterns.",
        root_cause="Assumed every row has at least 2 columns; some rows have fewer fields than expected.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    dict(
        bug_title="IndexError: pop from empty list",
        error_log_snippet="IndexError: pop from empty list\n  File 'stack.py', line 45\n    item = stack.pop()\n  File 'processor.py', line 60, in process_items\n    while pending:\n        item = stack.pop()",
        tried_methods="Printed len(stack) before pop; added if stack: guard",
        final_solution="Always check emptiness: if stack: item = stack.pop(). Or use stack.pop() with default: stack.pop() if stack else None",
        root_cause="Popped from a list without checking if it's empty; the while loop condition didn't prevent emptiness.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    dict(
        bug_title="IndexError: string index out of range",
        error_log_snippet="IndexError: string index out of range\n  File 'validator.py', line 10\n    first_char = text[0]\ntext is '' (empty string) at validator.py:8",
        tried_methods="Added if text: check; tried using text[:1] slice instead",
        final_solution="Check non-empty before indexing: if text: first_char = text[0] else: first_char = ''. Slicing (text[:1]) returns '' on empty string without error.",
        root_cause="Assumed input string is non-empty; empty strings pass validation and cause index access failure.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    dict(
        bug_title="IndexError: list assignment index out of range",
        error_log_snippet="IndexError: list assignment index out of range\n  File 'grid.py', line 25\n    grid[3][4] = 'X'\ngrid = [['']*3 for _ in range(3)]  # 3x3 grid",
        tried_methods="Printed grid dimensions; changed index to grid[2][2]",
        final_solution="Check array bounds before assignment, or pre-size correctly: grid = [['']*5 for _ in range(5)] for a 5x5 grid.",
        root_cause="Using an index beyond the array dimensions; grid is 3x3 but code accesses row 3/col 4.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    dict(
        bug_title="IndexError: too many indices for array (NumPy)",
        error_log_snippet="IndexError: too many indices for array: array is 1-dimensional, but 2 were indexed\n  File 'ml/predict.py', line 40\n    features = data[:, 1:3]\ndata.shape = (100,)  # 1D array",
        tried_methods="Checked data.shape; used data.reshape(-1, 1) for 2D",
        final_solution="Verify array dimensions: if data.ndim == 1: data = data.reshape(-1, 1). Then use correct slicing: data[:, 0:2].",
        root_cause="Data is 1D but code assumes 2D array; no dimensional validation before indexing.",
        project_name="sample-python",
        tech_stack="Python, NumPy",
    ),
    # ── KeyError ─────────────────────────────────────────────────
    dict(
        bug_title="KeyError: 'missing_key' in dict access",
        error_log_snippet="KeyError: 'config_path'\n  File 'config_loader.py', line 15\n    path = config['config_path']\nconfig = {'debug': True}  # no 'config_path' key\n   ",
        tried_methods="Printed config.keys(); tried config.get('config_path')",
        final_solution="Use .get() with default: path = config.get('config_path', './default.cfg'). Or check with 'key' in config.",
        root_cause="Accessed dict key directly without checking existence; key doesn't exist in the dict.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    dict(
        bug_title="KeyError: 0 in dict with integer-like string keys",
        error_log_snippet="KeyError: 0\n  File 'mapper.py', line 22\n    value = mapping[0]\nmapping = {'0': 'a', '1': 'b'}  # keys are strings",
        tried_methods="Checked mapping.keys(); tried str(0) conversion",
        final_solution="Use consistent key types: if mapping keys are strings, access with str(key): value = mapping[str(idx)]. Or convert keys to integers.",
        root_cause="Dict keys are strings but access uses integer; Python distinguishes 0 != '0'.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    dict(
        bug_title="KeyError raised inside nested dict access chain",
        error_log_snippet="KeyError: 'address'\n  File 'user_api.py', line 50\n    city = user['profile']['address']['city']\nuser = {'profile': {'name': 'Alice'}}  # no 'address' key",
        tried_methods="Used .get().get().get() chain; checked each nested level separately",
        final_solution="Safe nested access: city = user.get('profile', {}).get('address', {}).get('city', ''). Or use try/except with specific fallback.",
        root_cause="Deep dict access without intermediate None/key checks; middle-level key is missing.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    dict(
        bug_title="KeyError in defaultdict — used wrong factory",
        error_log_snippet='KeyError: "Key not found even though using defaultdict"\n  File "counter.py", line 18\n    count = word_counts[word] + 1\n  Actually: word_counts = defaultdict(list)  # wrong factory!',
        tried_methods="Changed defaultdict(int) to fix; printed word_counts type",
        final_solution="Use correct factory: word_counts = defaultdict(int). Then word_counts[word] += 1 works automatically. defaultdict(list) creates empty lists, not 0.",
        root_cause="Used defaultdict(list) instead of defaultdict(int); list + int raises TypeError, not KeyError.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    # ── ImportError / ModuleNotFoundError ──────────────────────────
    dict(
        bug_title="ModuleNotFoundError: No module named 'missing_module'",
        error_log_snippet="ModuleNotFoundError: No module named 'missing_module'\n  File 'app.py', line 3\n    import missing_module\n  Did you forget to install it? Or typo: pip install missing-module",
        tried_methods="Ran pip list to check; tried pip install missing_module; checked for typos in module name",
        final_solution="Install via pip: pip install missing-module. Check import spelling vs. package name. Use try/except ImportError for optional dependencies.",
        root_cause="Dependency not installed; or module name differs from pip package name (e.g. 'bs4' vs 'beautifulsoup4').",
        project_name="sample-python",
        tech_stack="Python",
    ),
    dict(
        bug_title="ImportError: cannot import name X from partially initialized module",
        error_log_snippet="ImportError: cannot import name 'db' from partially initialized module 'database' (most likely due to a circular import)\n  File 'database/__init__.py', line 2\n    from .models import User\n  File 'database/models.py', line 1\n    from database import db  # db not yet defined",
        tried_methods="Moved db initialization before imports; used lazy import",
        final_solution="Restructure: define db in a separate module (database/connection.py), import from there. Or use lazy import inside function/method.",
        root_cause="Circular import between __init__.py and models.py; db is referenced before definition in the init sequence.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    dict(
        bug_title="ImportError: attempted relative import beyond top-level package",
        error_log_snippet="ImportError: attempted relative import beyond top-level package\n  File 'scripts/run.py', line 2\n    from ..models import User\n  scripts/run.py is not in a package; executed directly via python scripts/run.py",
        tried_methods="Ran from project root; changed to absolute import; added __init__.py",
        final_solution="Use absolute imports: from myproject.models import User. Or add to PYTHONPATH and use -m flag: python -m scripts.run",
        root_cause="Executing a script inside a package directly (python scripts/run.py) breaks relative imports; the file is treated as __main__, not as part of the package.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    # ── NameError ─────────────────────────────────────────────────
    dict(
        bug_title="NameError: name 'x' is not defined (typo)",
        error_log_snippet="NameError: name 'status' is not defined\n  File 'api.py', line 55\n    return JsonResponse({'status': statu})  # typo!\nVariable is 'status' at line 50: status = 'ok'",
        tried_methods="Checked variable spelling; used IDE linter",
        final_solution="Use a linter (pylint, flake8, ruff) to catch undefined names before runtime. Be careful with typos in variable names.",
        root_cause="Simple typo: statUs vs statE; the wrong letter creates a new name that was never defined.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    dict(
        bug_title="NameError: name 'self' is not defined (forgot @classmethod)",
        error_log_snippet="NameError: name 'self' is not defined\n  File 'models.py', line 28\n    def find_by_id(cls, id):  # should be @classmethod\n        self._cache.get(id)  # should be cls._cache",
        tried_methods="Added @classmethod decorator; changed self to cls",
        final_solution="Use proper decorator and conventions: @classmethod; def find_by_id(cls, id): return cls._cache.get(id). self is for instance methods.",
        root_cause="Instance method pattern used for class-level operation; self is not available in methods without a class/static decorator.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    dict(
        bug_title="NameError: variable referenced before assignment in try/except",
        error_log_snippet="UnboundLocalError: local variable 'result' referenced before assignment\n  File 'calc.py', line 12\n    return result\nresult is assigned inside try block at line 8, but exception occurs before assignment at line 6.",
        tried_methods="Initialized result to None before try; moved return inside try",
        final_solution="Always initialize before try: result = None. Then check: if result is not None: return result; else: return default.",
        root_cause="Variable assigned inside try block; if exception occurs before assignment, the variable is never set.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    dict(
        bug_title="NameError: name 'file_path' is not defined (scope issue)",
        error_log_snippet="NameError: name 'file_path' is not defined\n  File 'processor.py', line 30\n    return {'path': file_path, 'size': file_size}\nfile_path defined inside if block at line 20: if condition: file_path = '/tmp/x.txt'",
        tried_methods="Print locals() to debug; moved variable definition outside if",
        final_solution="Declare variable in all code paths before use: file_path = '' (default) before the if/else block, then assign inside conditionals.",
        root_cause="Variable only defined inside a conditional branch; if that branch is skipped, the variable doesn't exist in the outer scope.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    # ── OSError / IOError ──────────────────────────────────────────
    dict(
        bug_title="FileNotFoundError: No such file or directory",
        error_log_snippet="FileNotFoundError: [Errno 2] No such file or directory: 'config.yaml'\n  File 'loader.py', line 10\n    with open('config.yaml') as f:\n        data = yaml.safe_load(f)\n  Working directory: /app/src (not /app)",
        tried_methods="Used os.path.abspath() to find current path; checked if file exists",
        final_solution="Use absolute paths: base_dir = Path(__file__).parent; cfg_path = base_dir / 'config.yaml'. Or use pathlib throughout.",
        root_cause="Relative path used; working directory not what the developer assumed; file exists relative to script dir, not CWD.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    dict(
        bug_title="PermissionError: [Errno 13] Permission denied",
        error_log_snippet="PermissionError: [Errno 13] Permission denied: '/var/log/app.log'\n  File 'logger.py', line 22\n    with open(log_path, 'w') as f:\n        f.write(log_entry)\n  User: www-data doesn't have write access to /var/log/",
        tried_methods="Checked file permissions with os.access(); ran as sudo",
        final_solution="Use a writable log location: log_path = Path('/tmp') / 'app.log'. Or configure log rotation to write to user-accessible path.",
        root_cause="Process runs with insufficient privileges for the target directory; not checking write permissions before open.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    dict(
        bug_title="IsADirectoryError: [Errno 21] Is a directory",
        error_log_snippet="IsADirectoryError: [Errno 21] Is a directory: '/data/output'\n  File 'writer.py', line 15\n    with open(output_path, 'w') as f:\n        f.write(result)\n  output_path is '/data/output' — it's a directory, not a file!",
        tried_methods="Checked os.path.isfile(); appended filename to path",
        final_solution="Always construct full file path including filename: output_file = Path('/data/output') / 'result.txt'. Use Path.suffix to ensure extension.",
        root_cause="Path points to a directory instead of a file; missing filename in the path construction.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    # ── RecursionError ────────────────────────────────────────────
    dict(
        bug_title="RecursionError: maximum recursion depth exceeded (no base case)",
        error_log_snippet="RecursionError: maximum recursion depth exceeded\n  File 'search.py', line 20\n    return binary_search(arr, target, low, mid-1)\nBase case missing: if low > high: return -1\nFor input: target=999, arr=[1,2,3]",
        tried_methods="Added sys.setrecursionlimit(10000); added proper base case check",
        final_solution="Ensure ALL recursive paths have a base case: if low > high: return -1. Consider iterative approach for deep recursion. Set recursion limit as safety net.",
        root_cause="Missing base case in recursive function; target not in array causes infinite recursion.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    dict(
        bug_title="RecursionError: maximum recursion depth exceeded (mutual recursion)",
        error_log_snippet="RecursionError: maximum recursion depth exceeded\n  File 'fsm.py', line 10, in state_a\n    return state_b(data)\n  File 'fsm.py', line 20, in state_b\n    return state_a(data)\n  Cycle: state_a -> state_b -> state_a -> ...",
        tried_methods="Added depth counter; added visited set; checked transition logic",
        final_solution="Add cycle detection: if state in visited: raise StateError('cycle'). Use an iterative state machine with a step counter for safety.",
        root_cause="Mutual recursion between two functions with no base case or cycle detection; state machine has a cycle.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    # ── StopIteration ──────────────────────────────────────────────
    dict(
        bug_title="RuntimeError: generator raised StopIteration",
        error_log_snippet="StopIteration in generator\n  File 'gen.py', line 15\n    def my_generator():\n        yield 1\n        raise StopIteration  # not needed, return is correct\n  Python 3.7+ raises RuntimeError when StopIteration is raised inside generator",
        tried_methods="Replaced raise StopIteration with return; simplified generator logic",
        final_solution="Never raise StopIteration inside generators. Use return to end iteration: def g(): yield 1; return. Python 3.7+ raises RuntimeError on StopIteration in generators.",
        root_cause="Manually raising StopIteration inside a generator; Python 3.7+ forbids this and converts it to RuntimeError.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    # ── AssertionError ─────────────────────────────────────────────
    dict(
        bug_title="AssertionError in production code",
        error_log_snippet="AssertionError:\n  File 'order.py', line 85\n    assert len(items) > 0, 'Items list must not be empty'\n  Items list is empty when called from process_order() at order.py:100 with no prior validation.",
        tried_methods="Used if-check before assert; moved assert to validation layer",
        final_solution="Use proper validation instead of assert: if not items: raise ValueError('Items required'). Asserts can be disabled with -O flag.",
        root_cause="assert used for input validation instead of business logic check; asserts removed in optimized mode (-O).",
        project_name="sample-python",
        tech_stack="Python",
    ),
    # ── OverflowError ──────────────────────────────────────────────
    dict(
        bug_title="OverflowError: math range error",
        error_log_snippet="OverflowError: math range error\n  File 'math_calc.py', line 22\n    result = math.exp(large_value)\n  large_value = 2000 (too large for float64; overflow to inf then error)",
        tried_methods="Used decimal.Decimal; clamped input value to reasonable range",
        final_solution="Clamp input: clamped = min(max(large_value, -700), 700); result = math.exp(clamped). Or use decimal.Decimal for arbitrary precision.",
        root_cause="math.exp() with input > ~709 causes float overflow; no validation on input magnitude.",
        project_name="sample-python",
        tech_stack="Python, math",
    ),
    # ── ZeroDivisionError ──────────────────────────────────────────
    dict(
        bug_title="ZeroDivisionError: division by zero",
        error_log_snippet="ZeroDivisionError: division by zero\n  File 'stats.py', line 45\n    avg = total / count\n  count = 0 when called from stats.py:30 with empty dataset",
        tried_methods="Added if count == 0: return 0; used try/except",
        final_solution="Always check divisor: if count == 0: return 0.0 or raise ValueError. Use statistics.mean() which handles empty sequences.",
        root_cause="Division without checking if divisor is zero; empty dataset passed to average calculation.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    # ── FloatingPointError / Decimal ──────────────────────────────
    dict(
        bug_title="decimal.InvalidOperation: NaN comparison",
        error_log_snippet="decimal.InvalidOperation: <class 'decimal.InvalidOperation'>\n  File 'finance.py', line 30\n    if balance > threshold:\n  balance is Decimal('NaN') due to computation error at line 25",
        tried_methods="Used Decimal.is_nan() to check; cleaned input data",
        final_solution="Check for NaN before comparison: if balance.is_nan(): balance = Decimal('0'). Use Decimal.is_nan() or math.isnan(float(balance)).",
        root_cause="Financial computation produced NaN (e.g., 0/0 in Decimal); NaN comparisons always return False, then later operations fail.",
        project_name="sample-python",
        tech_stack="Python, Decimal",
    ),
    # ── RuntimeError ───────────────────────────────────────────────
    dict(
        bug_title="RuntimeError: dictionary changed size during iteration",
        error_log_snippet="RuntimeError: dictionary changed size during iteration\n  File 'cache.py', line 40\n    for key in cache:\n        if is_expired(key):\n            del cache[key]  # modifying dict while iterating!",
        tried_methods="Used list(cache.keys()) to copy; used dict comprehension",
        final_solution="Iterate over a copy: for key in list(cache.keys()): if is_expired(key): del cache[key]. Or use dict comprehension: {k: v for k, v in cache.items() if not is_expired(k)}",
        root_cause="Modifying dictionary size (adding/deleting keys) while iterating over it; Python prevents this to avoid unpredictable behavior.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    dict(
        bug_title="RuntimeError: cannot reuse already awaited coroutine",
        error_log_snippet="RuntimeError: cannot reuse already awaited coroutine\n  File 'async_runner.py', line 20\n    result1 = await process(data)\n    result2 = await process(data)  # process(data) coroutine already exhausted!",
        tried_methods="Created new coroutine each time; used asyncio.create_task",
        final_solution="Create a fresh coroutine for each await: coro = process(data); result1 = await coro; coro2 = process(data); result2 = await coro2. Or use asyncio.create_task() for reuse.",
        root_cause="A coroutine object can be awaited only once; re-awaiting raises RuntimeError. Each await needs a new coroutine object.",
        project_name="sample-python",
        tech_stack="Python, asyncio",
    ),
    dict(
        bug_title="RuntimeError: Event loop is closed (asyncio)",
        error_log_snippet="RuntimeError: Event loop is closed\n  File 'async_main.py', line 15\n    await some_async_function()\n  Happens after asyncio.run() has completed and loop is closed. Common in Jupyter notebooks.",
        tried_methods="Used asyncio.get_running_loop(); used nest_asyncio.apply() in Jupyter",
        final_solution="Use asyncio.run() only once at entry point. In Jupyter: pip install nest_asyncio; nest_asyncio.apply(). For tests, use pytest-asyncio.",
        root_cause="Trying to run async code in an environment where the event loop has already closed or doesn't exist.",
        project_name="sample-python",
        tech_stack="Python, asyncio",
    ),
    # ── TypeError with async ──────────────────────────────────────
    dict(
        bug_title="TypeError: 'async_generator' object is not iterable",
        error_log_snippet="TypeError: 'async_generator' object is not iterable\n  File 'data_stream.py', line 25\n    for item in async_fetch_items():\n  async_fetch_items is defined with async def + yield, needs async for",
        tried_methods="Changed for to async for; added async for inside async function",
        final_solution="Use async for inside an async function: async for item in async_fetch_items(): process(item). Regular for loop cannot consume async generators.",
        root_cause="Using regular for loop on an async generator; async generators require async for.",
        project_name="sample-python",
        tech_stack="Python, asyncio",
    ),
    # ── TypeError: not enough arguments for format string ──────────
    dict(
        bug_title="TypeError: not enough arguments for format string",
        error_log_snippet='TypeError: not enough arguments for format string\n  File "log.py", line 12\n    msg = "User %s has %d points" % (username,)\n  One placeholder with %d for int, but only username provided.',
        tried_methods="Used f-string instead; matched format specifiers to arguments",
        final_solution='Use f-strings (Python 3.6+): msg = f"User {username} has {score} points". Or match format specs exactly: "%s has %d points" % (username, score)',
        root_cause="Number of format specifiers doesn't match number of arguments; missing the score argument.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    # ── TypeError: __init__() should return None ───────────────────
    dict(
        bug_title="TypeError: __init__() should return None, not 'int'",
        error_log_snippet="TypeError: __init__() should return None\n  File 'model.py', line 15\n    def __init__(self, name):\n        self.name = name\n        return 42",
        tried_methods="Removed return statement from __init__",
        final_solution="Never return a value from __init__. Python raises TypeError if __init__ returns anything other than None.",
        root_cause="Returning a non-None value from __init__; Python explicitly forbids this for consistency with the object creation protocol.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    # ── TypeError: object of type 'map' has no len() ───────────────
    dict(
        bug_title="TypeError: object of type 'map' has no len()",
        error_log_snippet="TypeError: object of type 'map' has no len()\n  File 'pipeline.py', line 35\n    total = len(map(process, items))\n  map() returns an iterator in Python 3, not a list.",
        tried_methods="Wrapped in list(): len(list(map(process, items))); used list comprehension",
        final_solution="Convert to list first: processed = list(map(process, items)); total = len(processed). Or use list comprehension: processed = [process(item) for item in items]. In Python 3, map() is lazy.",
        root_cause="Python 3 map() returns an iterator (no __len__). Code assumes it returns a list like Python 2.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    # ── TypeError: 'method' object is not subscriptable ────────────
    dict(
        bug_title="TypeError: 'method' object is not subscriptable",
        error_log_snippet="TypeError: 'method' object is not subscriptable\n  File 'db_handler.py', line 20\n    row = db.fetch[0]  # should be db.fetch()[0]\ndb.fetch is an unbound method (not called), not the return value.",
        tried_methods="Called method with () before indexing: result = db.fetch()[0]",
        final_solution="Call the method before indexing: row = db.fetch()[0]. Parentheses matter: db.fetch is the method object, db.fetch() is the return value.",
        root_cause="Forgot to call the method with (); tried to subscript the method object itself rather than its return value.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    # ── TypeError: 'int' object is not callable ────────────────────
    dict(
        bug_title="TypeError: 'int' object is not callable",
        error_log_snippet="TypeError: 'int' object is not callable\n  File 'math_fns.py', line 10\n    total = sum + max([1, 2, 3])  # variable named 'sum' shadows built-in sum()\n  line 5: sum = get_base_total()",
        tried_methods="Renamed variable to 'total_sum'; used builtins.sum()",
        final_solution="Never name variables after built-in functions (sum, max, min, list, dict, etc.). If shadowed, restore: del sum or import builtins; builtins.sum().",
        root_cause="Variable named sum shadows the built-in sum() function; later call to sum() tries to call the int variable.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    # ── SyntaxError ────────────────────────────────────────────────
    dict(
        bug_title="SyntaxError: f-string: expressions nested too deeply",
        error_log_snippet="SyntaxError: f-string: expressions nested too deeply\n  File 'template.py', line 10\n    msg = f'Result: {func(dict(a=[x for x in range(5)]))}'\n  Python's f-string parser has a nesting limit.",
        tried_methods="Extracted nested expression to a variable before f-string",
        final_solution="Extract complex expressions to intermediate variables: data = dict(a=[x for x in range(5)]); result = func(data); msg = f'Result: {result}'",
        root_cause="F-string expression too deeply nested; Python's parser cannot handle more than a few levels of nesting inside f-string braces.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    # ── SyntaxError: default argument is mutable ──────────────────
    dict(
        bug_title="Python mutable default argument trap",
        error_log_snippet="def add_item(item, items=[]):\n    items.append(item)\n    return items\n\nprint(add_item(1))  # [1]\nprint(add_item(2))  # [1, 2]  ← unexpected! Still the same list object",
        tried_methods="Used items=None and created list inside function",
        final_solution="Use immutable sentinel: def add_item(item, items=None): if items is None: items = []; items.append(item); return items",
        root_cause="Default arguments are evaluated once at function definition time, not at each call. Mutable defaults accumulate state across calls.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    # ── TypeError: 'range' object does not support item assignment ─
    dict(
        bug_title="TypeError: 'range' object does not support item assignment",
        error_log_snippet="TypeError: 'range' object does not support item assignment\n  File 'array_ops.py', line 15\n    indices[0] = 42\n  indices = range(10)  # range is immutable!",
        tried_methods="Converted range to list: indices = list(range(10))",
        final_solution="Convert range to list for mutable operations: indices = list(range(10)). Range objects are immutable sequences (like tuples, not lists).",
        root_cause="range() returns an immutable sequence; mutation attempted as if it were a list.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    # ── TypeError: expected str, bytes or os.PathLike ──────────────
    dict(
        bug_title="TypeError: expected str, bytes or os.PathLike, not int",
        error_log_snippet="TypeError: expected str, bytes or os.PathLike, not int\n  File 'file_manager.py', line 20\n    path = Path(123)  # Path() expects string or PathLike, not int\n  /data/{123}.txt — concatenation error: base_path + id",
        tried_methods="Converted to str before Path: Path(str(123))",
        final_solution="Always convert path components to strings: file_path = Path('/data') / str(file_id). Use f-string or str() for non-string values.",
        root_cause="Integer value passed directly to Path() constructor; pathlib expects string or os.PathLike, not int.",
        project_name="sample-python",
        tech_stack="Python, pathlib",
    ),
    # ── Pickle error ───────────────────────────────────────────────
    dict(
        bug_title="pickle.PicklingError: Can't pickle lambda function",
        error_log_snippet="pickle.PicklingError: Can't pickle <function <lambda> at 0x...>:\n  File 'parallel.py', line 30\n    results = pool.map(lambda x: x*2, data)\n  multiprocessing uses pickle to serialize; lambda can't be pickled.",
        tried_methods="Used functools.partial; defined named function instead",
        final_solution="Use named functions (def, not lambda) when passing to multiprocessing: def double(x): return x*2; pool.map(double, data). Use cloudpickle for complex cases.",
        root_cause="multiprocessing uses pickle to serialize functions; lambdas cannot be pickled. Always use named functions with multiprocessing.",
        project_name="sample-python",
        tech_stack="Python, multiprocessing",
    ),
    # ── MemoryError ────────────────────────────────────────────────
    dict(
        bug_title="MemoryError: unable to allocate large array",
        error_log_snippet="MemoryError: Unable to allocate 8.00 GiB for an array with shape (1000000, 1000) and data type float64\n  File 'ml/train.py', line 45\n    X = np.random.rand(1000000, 1000)  # too large for available memory",
        tried_methods="Used np.memmap for memory-mapped file; reduced batch size; used sparse arrays",
        final_solution="Use batch processing: for batch in batch_generator(data, batch_size=1000): process(batch). Consider generators, memory mapping (np.memmap), or incremental algorithms.",
        root_cause="Attempting to allocate more memory than available; large matrix created all at once instead of in batches.",
        project_name="sample-python",
        tech_stack="Python, NumPy",
    ),
    # ── UnicodeEncodeError ──────────────────────────────────────────
    dict(
        bug_title="UnicodeEncodeError: 'ascii' codec can't encode character",
        error_log_snippet="UnicodeEncodeError: 'ascii' codec can't encode character '\\u4e2d' in position 0: ordinal not in range(128)\n  File 'printer.py', line 10\n    print(data)  # data contains Chinese characters; console is ASCII-only",
        tried_methods="Set PYTHONIOENCODING=utf-8; encode explicitly with .encode('utf-8')",
        final_solution="Set environment: export PYTHONIOENCODING=utf-8. Or handle encoding: sys.stdout.reconfigure(encoding='utf-8'). Use .encode('utf-8') for file writes.",
        root_cause="Printing unicode characters to a terminal/pipe configured with ASCII encoding; Python raises UnicodeEncodeError instead of auto-encoding.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    # ── KeyboardInterrupt handling ─────────────────────────────────
    dict(
        bug_title="Improper KeyboardInterrupt handling blocking exit",
        error_log_snippet="File 'long_running.py', line 60\n    while True:\n        try:\n            process_data()\n        except Exception:\n            time.sleep(1)  # KeyboardInterrupt is NOT a subclass of Exception!\n  So Ctrl+C is NOT caught and exits. But if you catch BaseException, it also catches KeyboardInterrupt.",
        tried_methods="Used except BaseException: but that blocks Ctrl+C too; used signal handler",
        final_solution="Don't catch BaseException or bare except in long-running loops. Use: except (Exception, KeyboardInterrupt): to handle gracefully. Or use try/finally for cleanup.",
        root_cause="KeyboardInterrupt inherits from BaseException, not Exception. A bare 'except Exception' won't catch Ctrl+C. But 'except:' or 'except BaseException:' will catch and block it.",
        project_name="sample-python",
        tech_stack="Python",
    ),
]


# ===================================================================
#  Main: Insert 50 samples, then test retrieval
# ===================================================================

async def main():
    print("=" * 72)
    print("  BugVault — 50 Classic Python Error Samples + RAG Evaluation")
    print("=" * 72)
    print(f"\n  Config: model={settings.eval_llm_model}, RAG eval={settings.enable_rag_eval}")
    print()

    # ── Init ───────────────────────────────────────────────────────
    executor = ThreadPoolExecutor(max_workers=2)
    db = LanceDBClient()
    db.initialize()
    embedding_svc = EmbeddingService()

    # ── Insert samples ─────────────────────────────────────────────
    print(f"  Inserting {len(SAMPLES)} sample records…")
    success = 0
    for i, data in enumerate(SAMPLES):
        record = BugRecord(**data)
        missing = validate_and_prepare(record)
        if missing:
            print(f"    [{i+1}] SKIP (missing: {missing})")
            continue

        # Write archive + upsert to LanceDB
        search_text = record.to_search_text()
        embedding = embedding_svc.generate_embedding(search_text)
        db.upsert_record(search_text, embedding, record)
        write_markdown_archive(record)
        success += 1

        if (i + 1) % 10 == 0:
            print(f"    [{i+1}/{len(SAMPLES)}] {success} inserted so far…")

    print(f"\n  ✅ {success} samples inserted into LanceDB")
    print()

    # ── Test Retrieval: classic Python errors ──────────────────────
    TEST_QUERIES = [
        "KeyError when accessing dict key",
        "TypeError NoneType object has no attribute",
        "list index out of range",
        "ModuleNotFoundError cannot find module",
        "division by zero error",
    ]

    from bugvault.services.rag_evaluator_svc import RAGEvaluator
    rag_eval = RAGEvaluator()

    for q in TEST_QUERIES:
        print(f"\n  {'─' * 68}")
        print(f"  🔍 Query: \"{q}\"")
        print(f"  {'─' * 68}")

        query_emb = embedding_svc.generate_embedding(q)
        results = db.search(query_emb)

        if not results:
            print("  No results found.")
            continue

        from bugvault.services.retrieval_svc import rerank
        results = rerank(results, None)

        # Show top 2 results
        for i, row in enumerate(results[:2]):
            print(f"\n  Result #{i+1}:")
            print(f"    Title:   {row.get('bug_title', 'N/A')}")
            print(f"    Project: {row.get('project_name', 'N/A')}")
            print(f"    Root cause: {row.get('root_cause', 'N/A')[:120]}")

        # RAG evaluation
        if rag_eval.enabled:
            try:
                from bugvault.services.rag_evaluator_svc import format_context
                context = format_context(results, rag_eval.top_k)
                eval_result = await rag_eval.evaluate(q, context, "simple")
                if eval_result.rag_confidence_score is not None:
                    print(f"\n  📊 RAG Evaluation:")
                    print(f"     Confidence: {eval_result.rag_confidence_score:.1f}/10")
                    print(f"     Assessment: {eval_result.evaluation}")
            except Exception as e:
                print(f"  ⚠️  RAG eval skipped: {e}")
        else:
            print(f"\n  ⚠️  RAG evaluation is disabled (set BUGVAULT_ENABLE_RAG_EVAL=true)")

    print(f"\n  {'=' * 72}")
    print(f"  Done. Total samples: {success}, Total queries tested: {len(TEST_QUERIES)}")
    print(f"  {'=' * 72}")

    executor.shutdown(wait=False)


if __name__ == "__main__":
    asyncio.run(main())