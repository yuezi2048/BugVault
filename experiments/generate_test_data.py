"""生成合成 Bug 记录 + 100 条带标注的测试查询（含 ground truth）。

适用于离线检索 Benchmark，无需外部依赖。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


# ===================================================================
#  80 条合成 Bug 记录（覆盖 Python / JavaScript / Go / Java）
# ===================================================================

# 每条记录包含：bug_title, error_log_snippet, tried_methods, final_solution,
# root_cause, project_name(optional), tech_stack(optional)

BUG_RECORDS: list[dict] = [
    # ────────────────────────────────────────────────────────────────
    # Python 异常 (40 条)
    # ────────────────────────────────────────────────────────────────
    dict(
        bug_title="KeyError when accessing missing dict key",
        error_log_snippet="KeyError: 'username'\n  File 'app.py', line 22, in get_profile\n    return user_data['username']\nuser_data = {'id': 1, 'email': 'a@b.com'}  # missing 'username'",
        tried_methods="Checked dict keys with .keys(); used .get('username', default)",
        final_solution="Use dict.get(key, default) for safe access: user_data.get('username', 'unknown'). Or check with 'key in dict' first.",
        root_cause="Assuming all required keys exist without defensive checking; dict may have been populated from partial data.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    dict(
        bug_title="TypeError: unsupported operand type(s) for +: int and str",
        error_log_snippet="TypeError: unsupported operand type(s) for +: 'int' and 'str'\n  File 'cart.py', line 15, in calculate_total\n    total = price + quantity\nprice=<int>100, quantity=<str>'2'",
        tried_methods="Used type() to check variables; tried int() conversion",
        final_solution="Cast quantity to int before arithmetic: total = price + int(quantity). Add type hints to prevent the mismatch.",
        root_cause="Function get_quantity() returns a string instead of int due to not parsing the input; no type validation at the boundary.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    dict(
        bug_title="TypeError: 'NoneType' object is not subscriptable",
        error_log_snippet="TypeError: 'NoneType' object is not subscriptable\n  File 'api/handler.py', line 28, in process_response\n    data = response['data']\nresponse is None (fetch_from_cache returned None)",
        tried_methods="Added print(response) to debug; checked if response is None before access",
        final_solution="Add None check: if response is None: return {}; data = response.get('data', [])",
        root_cause="fetch_from_cache returns None on cache miss; caller assumed non-None return without defensive check.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    dict(
        bug_title="ValueError: invalid literal for int() with base 10",
        error_log_snippet="ValueError: invalid literal for int() with base 10: 'abc123'\n  File 'import.py', line 12, in parse_user_id\n    user_id = int(raw_id)\nraw_id='ABC123'",
        tried_methods="Printed raw_id to see actual value; tried regex to extract digits",
        final_solution="Use try/except: try: user_id = int(raw_id) except ValueError: user_id = 0. Or validate with str.isdigit() first.",
        root_cause="Input contains non-numeric characters; caller assumed data is always purely numeric.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    dict(
        bug_title="IndexError: list index out of range",
        error_log_snippet="IndexError: list index out of range\n  File 'csv_reader.py', line 20\n    first_name = row[1]\nrow is ['Alice'] (length 1)",
        tried_methods="Printed len(row) to debug; tried using row[0] instead",
        final_solution="Check bounds: if len(row) > 1: first_name = row[1] else: first_name = ''",
        root_cause="Assumed every row has at least 2 columns; some rows have fewer fields than expected.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    dict(
        bug_title="ModuleNotFoundError: No module named 'requests'",
        error_log_snippet="ModuleNotFoundError: No module named 'requests'\n  File 'main.py', line 3\n    import requests\nPython environment missing the 'requests' package",
        tried_methods="Ran pip install requests; checked requirements.txt",
        final_solution="Ensure requests is in requirements.txt and installed: pip install requests. Use venv to isolate dependencies.",
        root_cause="External dependency not installed; requirements.txt not updated or virtual environment not activated.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    dict(
        bug_title="ImportError: cannot import name 'flatten' from 'itertools'",
        error_log_snippet="ImportError: cannot import name 'flatten' from 'itertools'\n  File 'utils.py', line 2\n    from itertools import flatten\nitertools.flatten was removed in Python 3.10+",
        tried_methods="Checked Python version; looked up itertools docs; used itertools.chain instead",
        final_solution="Replace with itertools.chain.from_iterable(): list(chain.from_iterable(nested_list)). flatten was deprecated and removed.",
        root_cause="Using a function removed in Python 3.10; code was written for older Python or based on outdated documentation.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    dict(
        bug_title="AttributeError: 'str' object has no attribute 'append'",
        error_log_snippet="AttributeError: 'str' object has no attribute 'append'\n  File 'builder.py', line 22, in build_query\n    query.append(f'AND {condition}')\nquery = 'SELECT * FROM users'  # initialized as string, not list",
        tried_methods="Printed type(query); tried += instead of append",
        final_solution="Initialize as list: query_parts = ['SELECT * FROM users']; query_parts.append(f'AND {condition}'); final = ' '.join(query_parts)",
        root_cause="Variable initialized as string (immutable, no .append()) but used as if it were a list.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    dict(
        bug_title="ZeroDivisionError: division by zero",
        error_log_snippet="ZeroDivisionError: division by zero\n  File 'stats.py', line 30\n    average = total / count\ncount = 0 (empty dataset)",
        tried_methods="Checked count before division; used if count == 0: return 0",
        final_solution="Guard against zero: if count == 0: return 0.0; average = total / count",
        root_cause="No validation for empty dataset; computed average without checking for zero denominator.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    dict(
        bug_title="FileNotFoundError: No such file or directory",
        error_log_snippet="FileNotFoundError: [Errno 2] No such file or directory: 'config.yaml'\n  File 'loader.py', line 8\n    with open('config.yaml') as f:\nWorking directory is /app/data/, not /app/",
        tried_methods="Checked working directory with os.getcwd(); used absolute path",
        final_solution="Use absolute paths or Path(__file__).parent / 'config.yaml'. Never rely on relative paths from an unknown CWD.",
        root_cause="Relative path resolved from the wrong working directory; the file exists but not relative to CWD.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    dict(
        bug_title="UnboundLocalError: local variable referenced before assignment",
        error_log_snippet="UnboundLocalError: local variable 'result' referenced before assignment\n  File 'process.py', line 15\n    return result\nresult only assigned inside the if block",
        tried_methods="Initialized result = None before the if block",
        final_solution="Always initialize variables before conditional paths: result = None; if condition: result = compute(); return result",
        root_cause="Variable assigned inside conditional branch; if condition is False, the variable never gets assigned.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    dict(
        bug_title="RecursionError: maximum recursion depth exceeded",
        error_log_snippet="RecursionError: maximum recursion depth exceeded\n  File 'tree.py', line 12, in traverse\n    return traverse(node)  # forgot to pass node.children\n  Called without progressing to child nodes",
        tried_methods="Checked recursion depth; sys.setrecursionlimit(10000); converted to iterative",
        final_solution="Fix recursion base case: ensure each call progresses toward termination. For deep trees, use iterative stack: stack = [root]; while stack: node = stack.pop()",
        root_cause="Missing base case or not reducing the problem; infinite recursion because the same node was passed repeatedly.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    dict(
        bug_title="Python mutable default argument accumulation",
        error_log_snippet="def add_item(item, items=[]):\n    items.append(item)\n    return items\n\nprint(add_item(1))  # [1]\nprint(add_item(2))  # [1, 2]  ← shared mutable default!",
        tried_methods="Used items=None and created new list each time",
        final_solution="Use immutable sentinel: def add_item(item, items=None): if items is None: items = []; items.append(item); return items",
        root_cause="Default arguments evaluated once at function definition time; mutable defaults accumulate state across calls.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    dict(
        bug_title="pickle.PicklingError: Can't pickle lambda function",
        error_log_snippet="pickle.PicklingError: Can't pickle <function <lambda> at 0x...>\n  File 'parallel.py', line 30\n    results = pool.map(lambda x: x*2, data)\nmultiprocessing uses pickle to serialize; lambdas can't be pickled.",
        tried_methods="Used functools.partial; defined named function instead",
        final_solution="Use named functions with multiprocessing: def double(x): return x*2; pool.map(double, data)",
        root_cause="multiprocessing uses pickle to serialize; lambdas cannot be pickled. Always use named functions.",
        project_name="sample-python",
        tech_stack="Python, multiprocessing",
    ),
    dict(
        bug_title="StopIteration from manual next() call without default",
        error_log_snippet="StopIteration\n  File 'iterator.py', line 10\n    item = next(iterator)  # iterator exhausted\niterator = iter([1, 2, 3]); already consumed 3 items; no more elements.",
        tried_methods="Wrapped in try/except StopIteration; used for loop instead",
        final_solution="Use next() with default: next(iterator, None). Or use a for loop which handles StopIteration internally.",
        root_cause="Manual iteration with next() without a default value; iterator runs out of elements after the last item.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    dict(
        bug_title="TypeError: 'int' object is not iterable",
        error_log_snippet="TypeError: 'int' object is not iterable\n  File 'utils.py', line 33, in flatten\n    for item in data:\ndata = get_counts() returned a single int 42, not a list.",
        tried_methods="Printed data type with type(); wrapped data in [data] list",
        final_solution="Check if iterable: if not isinstance(data, Iterable): data = [data]. Or fix return type to always return list.",
        root_cause="Function returns a single value when only one result, but caller expects list for iteration.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    dict(
        bug_title="SyntaxError: f-string: expressions nested too deeply",
        error_log_snippet="SyntaxError: f-string: expressions nested too deeply\n  File 'template.py', line 10\n    msg = f'Result: {func(dict(a=[x for x in range(5)]))}'\nPython's f-string parser has a nesting limit.",
        tried_methods="Extracted nested expression to a variable before f-string",
        final_solution="Extract complex expressions to intermediate variables: data = dict(a=[x for x in range(5)]); result = func(data); msg = f'Result: {result}'",
        root_cause="F-string expression too deeply nested; Python parser cannot handle several levels of nesting inside f-string braces.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    dict(
        bug_title="TypeError: object of type 'map' has no len()",
        error_log_snippet="TypeError: object of type 'map' has no len()\n  File 'pipeline.py', line 35\n    total = len(map(process, items))\nmap() returns an iterator in Python 3, not a list.",
        tried_methods="Wrapped in list(): len(list(map(process, items))); used list comprehension",
        final_solution="Convert to list first: processed = list(map(process, items)); total = len(processed). In Python 3, map() is lazy.",
        root_cause="Python 3 map() returns an iterator (no __len__). Code assumes it returns a list like Python 2.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    dict(
        bug_title="AttributeError: partially initialized module has no attribute",
        error_log_snippet="AttributeError: partially initialized module 'app' has no attribute 'config'\n  File 'app/routes.py', line 5\n    from app import config  # config not yet defined in __init__.py\nCircular import at app/__init__.py",
        tried_methods="Moved config definition before imports; used lazy import inside function",
        final_solution="Define config in a separate module (app/config.py), or use lazy import inside functions.",
        root_cause="Circular import causes partial initialization; attribute not yet assigned when the dependent module tries to import it.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    dict(
        bug_title="UnicodeEncodeError: 'ascii' codec can't encode character",
        error_log_snippet="UnicodeEncodeError: 'ascii' codec can't encode character '\\u4e2d' in position 0\n  File 'printer.py', line 10\n    print(data)  # data contains Chinese characters",
        tried_methods="Set PYTHONIOENCODING=utf-8; encoded with .encode('utf-8')",
        final_solution="Set export PYTHONIOENCODING=utf-8. Or: sys.stdout.reconfigure(encoding='utf-8')",
        root_cause="Printing unicode to terminal configured with ASCII encoding.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    dict(
        bug_title="MemoryError: unable to allocate large array",
        error_log_snippet="MemoryError: Unable to allocate 8.00 GiB for array shape (1000000, 1000) float64\n  File 'ml/train.py', line 45\n    X = np.random.rand(1000000, 1000)",
        tried_methods="Used np.memmap; reduced batch size; used sparse arrays",
        final_solution="Use batch processing: for batch in batch_generator(data, batch_size=1000): process(batch)",
        root_cause="Attempting to allocate more memory than available; large matrix created all at once.",
        project_name="sample-python",
        tech_stack="Python, NumPy",
    ),
    dict(
        bug_title="KeyError: 'id' in JSON response parsing",
        error_log_snippet='KeyError: \'id\'\n  File "parser.py", line 18, in parse_user\n    user_id = data["id"]\ndata = {"name": "Alice", "email": "a@b.com"}  # missing "id"',
        tried_methods="Used data.keys() to check; added data.get('id', 0)",
        final_solution="Use .get() with default: data.get('id', 0). Validate JSON schema before access.",
        root_cause="JSON response schema varies; some records omit optional fields, but code assumes all fields exist.",
        project_name="sample-python",
        tech_stack="Python, JSON",
    ),
    dict(
        bug_title="asyncio: RuntimeError: asyncio.run() cannot be called from a running event loop",
        error_log_snippet="RuntimeError: asyncio.run() cannot be called from a running event loop\n  File 'async_main.py', line 12\n    asyncio.run(main())\nAlready inside a running event loop (Jupyter/IPython/another asyncio context)",
        tried_methods="Used await instead; checked loop with asyncio.get_running_loop()",
        final_solution="Use await main() if already in an event loop. For notebooks: await or nest_asyncio.apply(). For scripts: asyncio.run(main()) is correct.",
        root_cause="asyncio.run() called when an event loop is already active; it's designed for the 'main entry point' only.",
        project_name="sample-python",
        tech_stack="Python, asyncio",
    ),
    dict(
        bug_title="TypeError: missing 1 required positional argument: 'self'",
        error_log_snippet="TypeError: __init__() missing 1 required positional argument: 'self'\n  File 'main.py', line 10\n    obj = MyClass.__init__(name='test')\nCalled unbound __init__ instead of constructor MyClass(name='test')",
        tried_methods="Used MyClass(name='test') directly; read class instantiation docs",
        final_solution="Always use class constructor: obj = MyClass(name='test'). Never call __init__ directly.",
        root_cause="__init__ called directly on the class rather than using the constructor syntax.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    dict(
        bug_title="ValueError: too many values to unpack (expected 2)",
        error_log_snippet="ValueError: too many values to unpack (expected 2)\n  File 'parser.py', line 28\n    key, value = line.split('=')\nline = 'key=value=extra' (contains multiple '=')",
        tried_methods="Printed line.split('='); tried using split('=', 1)",
        final_solution="Use maxsplit: key, value = line.split('=', 1). This preserves values that contain '='.",
        root_cause="Config values can contain '=' characters; split() without maxsplit produces more than 2 elements.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    dict(
        bug_title="AttributeError: module 'x' has no attribute 'y' due to circular import",
        error_log_snippet="AttributeError: module 'utils' has no attribute 'parse_config'\n  File 'main.py', line 5\n    from utils import parse_config\nutils/__init__.py imports parser which imports utils (circular)",
        tried_methods="Checked utils/parser.py for function; removed circular import",
        final_solution="Restructure imports: use 'from utils.parser import parse_config' in __init__.py, or move imports inside functions.",
        root_cause="Circular import causes parse_config to be undefined at import time.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    dict(
        bug_title="TypeError: 'int' object is not callable (shadows built-in)",
        error_log_snippet="TypeError: 'int' object is not callable\n  File 'math_fns.py', line 10\n    total = sum + max([1, 2, 3])\nVariable named 'sum' shadows built-in sum() function.",
        tried_methods="Renamed variable to total_sum; used builtins.sum()",
        final_solution="Never name variables after built-ins (sum, max, min, list, dict, etc.). If shadowed, restore with import builtins; builtins.sum().",
        root_cause="Variable named sum shadows the built-in; later call to sum() tries to call the int variable.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    dict(
        bug_title="TypeError: expected str, bytes or os.PathLike, not int",
        error_log_snippet="TypeError: expected str, bytes or os.PathLike, not int\n  File 'file_manager.py', line 20\n    path = Path(123)  # Path() expects string, not int",
        tried_methods="Converted to str before Path: Path(str(123))",
        final_solution="Always convert path components to strings: file_path = Path('/data') / str(file_id)",
        root_cause="Integer value passed directly to Path(); pathlib expects str or os.PathLike.",
        project_name="sample-python",
        tech_stack="Python, pathlib",
    ),
    dict(
        bug_title="AttributeError: 'dict' object has no attribute 'append'",
        error_log_snippet="AttributeError: 'dict' object has no attribute 'append'\n  File 'data_mapper.py', line 35\n    config.append(new_rule)\nconfig is a dict, not a list.",
        tried_methods="Printed type(config); tried config.update()",
        final_solution="Use dict methods: config[new_rule_key] = new_rule_value or config.update(new_rules_dict)",
        root_cause="Confused dict and list APIs; .append() is a list method, not dict.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    dict(
        bug_title="ValueError: I/O operation on closed file",
        error_log_snippet="ValueError: I/O operation on closed file.\n  File 'file_processor.py', line 40\n    content = f.read()\n  f was closed by 'with' block at line 35; read() called after block exit.",
        tried_methods="Moved read_remaining() inside the with block; checked f.closed",
        final_solution="Keep all file ops inside the 'with' block. Do not reference f outside the context manager.",
        root_cause="File object referenced outside its context manager; Python auto-closes on 'with' block exit.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    dict(
        bug_title="KeyError: 42 when using list index as dict key",
        error_log_snippet="KeyError: 42\n  File 'mapper.py', line 25\n    value = mapping[item.id]\nmapping = {0: 'a', 1: 'b'}, item.id = 42\n  Using sequential indices instead of valid keys.",
        tried_methods="Checked mapping keys; tested with item.id in mapping",
        final_solution="Check membership: if item.id in mapping: value = mapping[item.id]. Or use mapping.get(item.id, default).",
        root_cause="Assumed all possible IDs exist as dict keys; dict only contains a subset of expected keys.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    dict(
        bug_title="Type conversion error: string to float with locale format",
        error_log_snippet="ValueError: could not convert string to float: '3,14'\n  File 'parser.py', line 12\n    value = float('3,14')\nInput uses European decimal format (comma) but float() expects dot.",
        tried_methods="Used replace(',', '.'); used locale.atof()",
        final_solution="Normalize: value = float(input_string.replace(',', '.')) or use locale.atof() with proper locale setting.",
        root_cause="Input data uses European number format (comma as decimal separator); float() only accepts dot notation.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    dict(
        bug_title="Shallow copy vs deep copy list mutation bug",
        error_log_snippet="# No explicit error — logic bug\n  File 'matrix.py', line 12\n    backup = original[:]  # shallow copy\n    backup[0][0] = 99\n    # original[0][0] also changed to 99!",
        tried_methods="Used copy.copy(); used copy.deepcopy()",
        final_solution="For nested structures, always use copy.deepcopy(): import copy; backup = copy.deepcopy(original)",
        root_cause="Shallow copy only duplicates the outer list; inner lists are shared references.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    dict(
        bug_title="NameError: name 'logger' is not defined",
        error_log_snippet="NameError: name 'logger' is not defined\n  File 'service.py', line 20\n    logger.info('Processing started')\nlogger not imported or initialized in this module.",
        tried_methods="Added from loguru import logger; checked module imports",
        final_solution="Add proper import at module level: import logging; logger = logging.getLogger(__name__)",
        root_cause="Module uses logger without importing or defining it; copy-paste error from another file.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    dict(
        bug_title="RuntimeError: dictionary changed size during iteration",
        error_log_snippet="RuntimeError: dictionary changed size during iteration\n  File 'cache.py', line 15\n    for key in cache:\n        if expired(key):\n            del cache[key]\nAdding or deleting keys while iterating over the dict.",
        tried_methods="Copied keys before iteration: for key in list(cache.keys())",
        final_solution="Iterate over a snapshot: for key in list(cache): ... del cache[key]. Or use a dict comprehension.",
        root_cause="Modifying dict while iterating over it; Python raises RuntimeError to protect against undefined behavior.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    dict(
        bug_title="TypeError: 'range' object does not support item assignment",
        error_log_snippet="TypeError: 'range' object does not support item assignment\n  File 'array_ops.py', line 15\n    indices[0] = 42\nindices = range(10)  # range is immutable!",
        tried_methods="Converted range to list: indices = list(range(10))",
        final_solution="Convert range to list for mutable ops: indices = list(range(10)). Range objects are immutable.",
        root_cause="range() returns immutable sequence; mutation attempted as if it were a list.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    dict(
        bug_title="Floating point precision issue in financial calculation",
        error_log_snippet="# No explicit error — wrong result\n  File 'finance.py', line 22\n    total = 0.1 + 0.2  #  0.30000000000000004, not 0.3\n  Comparing: if total == 0.3 → False",
        tried_methods="Used round(); used Decimal module",
        final_solution="Use Decimal for money: from decimal import Decimal; total = Decimal('0.1') + Decimal('0.2')",
        root_cause="IEEE 754 floating point cannot represent 0.1 or 0.2 exactly; accumulated rounding errors.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    dict(
        bug_title="TypeError: __init__() should return None",
        error_log_snippet="TypeError: __init__() should return None\n  File 'model.py', line 10, in __init__\n    return 42  # __init__ must return None",
        tried_methods="Removed return from __init__",
        final_solution="Never return a value from __init__. Python raises TypeError if __init__ returns anything other than None.",
        root_cause="Returning non-None from __init__; Python explicitly forbids this.",
        project_name="sample-python",
        tech_stack="Python",
    ),
    # ────────────────────────────────────────────────────────────────
    # JavaScript / TypeScript 异常 (20 条)
    # ────────────────────────────────────────────────────────────────
    dict(
        bug_title="TypeError: Cannot read properties of undefined (reading 'data')",
        error_log_snippet="TypeError: Cannot read properties of undefined (reading 'data')\n  File 'api.js', line 25\n    const result = response.data;\n  response is undefined (API call failed without error handling)",
        tried_methods="Added console.log(response); checked API return value",
        final_solution="Use optional chaining: const result = response?.data || default. Always handle API errors with try/catch.",
        project_name="sample-js",
        tech_stack="JavaScript",
    ),
    dict(
        bug_title="TypeError: Cannot read property 'map' of undefined",
        error_log_snippet="TypeError: Cannot read property 'map' of undefined\n  File 'component.jsx', line 42\n    items.map(item => <li>{item}</li>)\nitems is undefined, received from parent as null.",
        tried_methods="Checked props; added default value in destructuring",
        final_solution="Default value: const { items = [] } = props; or items?.map(...). Always provide fallbacks for optional props.",
        project_name="sample-js",
        tech_stack="React, JavaScript",
    ),
    dict(
        bug_title="ReferenceError: x is not defined (Temporal Dead Zone)",
        error_log_snippet="ReferenceError: Cannot access 'x' before initialization\n  File 'script.js', line 3\n    console.log(x);\n  let x = 5;  // TDZ: accessing let/const before declaration",
        tried_methods="Moved console.log after declaration; changed let to var",
        final_solution="Always declare variables (let/const) before using them. Unlike var, let/const have Temporal Dead Zone.",
        project_name="sample-js",
        tech_stack="JavaScript",
    ),
    dict(
        bug_title="TypeError: 'undefined' is not a function",
        error_log_snippet="TypeError: 'undefined' is not a function\n  File 'event.js', line 15\n    callback(data);\ncallback is undefined — optional parameter not provided by caller.",
        tried_methods="Checked typeof callback; added callback && callback(data)",
        final_solution="Guard optional callbacks: if (typeof callback === 'function') callback(data). Or use default: callback = noop.",
        project_name="sample-js",
        tech_stack="JavaScript",
    ),
    dict(
        bug_title="Uncaught (in promise): TypeError: NetworkError when fetching",
        error_log_snippet="TypeError: NetworkError when fetching.\n  File 'service.js', line 20\n    const res = await fetch('/api/data');\n  Network is offline or server is unreachable. No catch handler.",
        tried_methods="Added .catch(); used try/catch around fetch",
        final_solution="Always handle fetch errors: try { const res = await fetch(url); } catch (err) { showError(err.message); }",
        project_name="sample-js",
        tech_stack="JavaScript, fetch API",
    ),
    dict(
        bug_title="React: Cannot update during an existing state transition",
        error_log_snippet="Warning: Cannot update during an existing state transition\n  File 'component.jsx', line 30\n    setState({ loading: true });\n    setState({ data: result });  // Called inside render or wrong lifecycle",
        tried_methods="Moved setState to useEffect; used functional setState",
        final_solution="Batch state updates: use useEffect for side effects. Never call setState() inside render or component body directly.",
        project_name="sample-js",
        tech_stack="React",
    ),
    dict(
        bug_title="TypeError: Assignment to constant variable",
        error_log_snippet="TypeError: Assignment to constant variable.\n  File 'config.js', line 8\n    MAX_RETRIES = 5;  // MAX_RETRIES declared with const earlier",
        tried_methods="Changed const to let; found the original declaration",
        final_solution="Use let for variables that need reassignment. const is for constants. Check variable declarations before reassigning.",
        project_name="sample-js",
        tech_stack="JavaScript",
    ),
    dict(
        bug_title="JavaScript: this is undefined in class method",
        error_log_snippet="TypeError: Cannot read properties of undefined (reading 'value')\n  File 'handler.js', line 20\n    console.log(this.value);\n  this is undefined when method is passed as callback: onClick={this.handleClick}",
        tried_methods="Used .bind(this); used arrow function for class property",
        final_solution="Use arrow function: handleClick = () => { ... } or bind: onClick={this.handleClick.bind(this)}",
        project_name="sample-js",
        tech_stack="JavaScript, React",
    ),
    dict(
        bug_title="Node.js: ERR_REQUIRE_ESM — require() of ES Module",
        error_log_snippet="Error [ERR_REQUIRE_ESM]: require() of ES Module /app/pkg/index.mjs not supported.\n  File 'server.js', line 1\n    const pkg = require('esm-only-package');\nPackage is ES module only; use import instead.",
        tried_methods="Changed require to import; added 'type':'module' to package.json",
        final_solution="Use dynamic import: const pkg = await import('esm-only-package'); or switch project to ESM with 'type': 'module'.",
        project_name="sample-js",
        tech_stack="Node.js",
    ),
    dict(
        bug_title="TypeError: cyclic object value (JSON.stringify)",
        error_log_snippet="TypeError: Converting circular structure to JSON\n  File 'utils.js', line 15\n    const json = JSON.stringify(obj);\n  obj has circular reference: obj.self = obj",
        tried_methods="Used JSON.stringify(obj, replacer); removed circular ref before stringify",
        final_solution="Remove or replace circular references before JSON.stringify. Use a replacer function: JSON.stringify(obj, (k,v) => k === 'parent' ? undefined : v)",
        project_name="sample-js",
        tech_stack="JavaScript",
    ),
    dict(
        bug_title="TypeError: Invalid array length (negative or too large)",
        error_log_snippet="TypeError: Invalid array length\n  File 'grid.js', line 10\n    const arr = new Array(size);\nsize is -1 or > 2^32-1 from user input validation failure.",
        tried_methods="Clamped size to valid range; validated input before use",
        final_solution="Validate and clamp array size: const safeSize = Math.max(0, Math.min(size, MAX_ARRAY_LENGTH)). Never trust user input for array sizes.",
        project_name="sample-js",
        tech_stack="JavaScript",
    ),
    dict(
        bug_title="npm: ERESOLVE unable to resolve dependency tree",
        error_log_snippet="npm ERR! ERESOLVE unable to resolve dependency tree\n  While resolving: my-app@1.0.0\n  Conflicting peer dependency: react@18.0.0 vs react@17.0.0",
        tried_methods="Used --legacy-peer-deps; updated package.json versions",
        final_solution="Update conflicting packages to compatible versions, or use --legacy-peer-deps temporarily. Consider using --force as last resort.",
        project_name="sample-js",
        tech_stack="Node.js, npm",
    ),
    dict(
        bug_title="TypeError: Cannot use 'in' operator to search for 'length' in undefined",
        error_log_snippet="TypeError: Cannot use 'in' operator to search for 'length' in undefined\n  File 'utils.js', line 25\n    if ('length' in data) { ... }  // data is undefined",
        tried_methods="Checked typeof data; added data && before in operator",
        final_solution="Guard before 'in' operator: if (data && 'length' in data). Or use Array.isArray(data) when checking for arrays.",
        project_name="sample-js",
        tech_stack="JavaScript",
    ),
    dict(
        bug_title="Promise: Unhandled promise rejection (no .catch)",
        error_log_snippet="UnhandledPromiseRejectionWarning: Error: API request failed\n  File 'service.js', line 30\n    const data = await fetchData();  // No try/catch wrapping\n  Promise rejected but no rejection handler attached.",
        tried_methods="Added .catch(); wrapped in try/catch",
        final_solution="Always handle promise rejections: use try/catch with async/await, or .catch() on promises. Add process.on('unhandledRejection') as global fallback.",
        project_name="sample-js",
        tech_stack="Node.js",
    ),
    dict(
        bug_title="TypeError: Class constructor cannot be invoked without 'new'",
        error_log_snippet="TypeError: Class constructor MyService cannot be invoked without 'new'\n  File 'app.js', line 15\n    const svc = MyService();  // missing 'new' keyword",
        tried_methods="Added new keyword: const svc = new MyService()",
        final_solution="Always use 'new' when calling a constructor: const svc = new MyService(). Consider ES6 class syntax which enforces 'new'.",
        project_name="sample-js",
        tech_stack="JavaScript",
    ),
    dict(
        bug_title="Vue: Cannot access 'x' before initialization (composition API)",
        error_log_snippet="ReferenceError: Cannot access 'x' before initialization\n  File 'setup.js', line 15\n    const doubled = computed(() => x.value * 2);\n  const x = ref(0);  // line 20 — used before declaration in setup()",
        tried_methods="Reordered variable declarations; used let with hoisting",
        final_solution="Declare refs before computed/watch that depend on them: const x = ref(0); const doubled = computed(() => x.value * 2)",
        project_name="sample-js",
        tech_stack="Vue, JavaScript",
    ),
    # ────────────────────────────────────────────────────────────────
    # Go 异常 (10 条)
    # ────────────────────────────────────────────────────────────────
    dict(
        bug_title="Go: nil pointer dereference",
        error_log_snippet="panic: runtime error: invalid memory address or nil pointer dereference\n  File 'server.go', line 45\n    fmt.Println(config.Port)\nconfig is nil — LoadConfig() returned nil on file not found.",
        tried_methods="Added nil check for config; used defer recover",
        final_solution="Always check returned pointers: config, err := LoadConfig(); if err != nil { return err }; fmt.Println(config.Port)",
        project_name="sample-go",
        tech_stack="Go",
    ),
    dict(
        bug_title="Go: index out of range [0] with length 0 slice",
        error_log_snippet="panic: runtime error: index out of range [0] with length 0\n  File 'processor.go', line 20\n    first := items[0]\nitems is empty slice (len=0) from parsing.",
        tried_methods="Checked len(items) > 0 before access; used for range",
        final_solution="Guard with length check: if len(items) > 0 { first := items[0] }. Use 'for range' for safe iteration.",
        project_name="sample-go",
        tech_stack="Go",
    ),
    dict(
        bug_title="Go: concurrent map read and map write (race condition)",
        error_log_snippet="fatal error: concurrent map read and map write\n  File 'cache.go', line 30 (read) and line 35 (write — goroutine)\n  Shared map accessed concurrently without synchronization.",
        tried_methods="Added sync.RWMutex; used sync.Map",
        final_solution="Use sync.RWMutex: mu.RLock() for reads, mu.Lock() for writes. Or use sync.Map for concurrent-friendly key-value access.",
        project_name="sample-go",
        tech_stack="Go",
    ),
    dict(
        bug_title="Go: closing channel of closed channel (panic)",
        error_log_snippet="panic: close of closed channel\n  File 'worker.go', line 25\n    close(ch)\n  channel already closed by another goroutine. No way to check if channel is closed.",
        tried_methods="Used sync.Once for close; added closed flag with mutex",
        final_solution="Wrap close in sync.Once: var closeOnce sync.Once; closeOnce.Do(func() { close(ch) }). Never close a channel from multiple goroutines.",
        project_name="sample-go",
        tech_stack="Go",
    ),
    dict(
        bug_title="Go: cannot use (variable of type X) as type Y in assignment",
        error_log_snippet="cannot use value (variable of type string) as type int in assignment\n  File 'mapper.go', line 18\n    id := value.(int) // type assertion failed\nvalue is string, cannot assert to int.",
        tried_methods="Used strconv.Atoi(); used a type switch",
        final_solution="Use safe type assertion with ok check: id, ok := value.(int); if !ok { str, _ := value.(string); id, _ = strconv.Atoi(str) }",
        project_name="sample-go",
        tech_stack="Go",
    ),
    dict(
        bug_title="Go: sql: no rows in result set (sql.ErrNoRows)",
        error_log_snippet="sql: no rows in result set\n  File 'repo.go', line 35\n    row.Scan(&name, &age)\n  Query returned 0 rows — no matching record found.",
        tried_methods="Used QueryRow with Err(); checked for sql.ErrNoRows",
        final_solution="Always check for sql.ErrNoRows: err := row.Scan(...); if errors.Is(err, sql.ErrNoRows) { return NotFound, nil }",
        project_name="sample-go",
        tech_stack="Go, database/sql",
    ),
    dict(
        bug_title="Go: unreachable code (defer inside infinite loop never executes)",
        error_log_snippet="# Logic bug: resource leak\n  File 'server.go', line 12\n    for {\n        conn, _ := listener.Accept()\n        defer conn.Close()  // never closes until server stops\n    }\ndefers inside a loop accumulate until the function returns.",
        tried_methods="Removed defer; manually called conn.Close() after processing",
        final_solution="Don't use defer inside loops: for { conn, _ := listener.Accept(); process(conn); conn.Close() }",
        project_name="sample-go",
        tech_stack="Go",
    ),
    dict(
        bug_title="Go: send on closed channel (panic in goroutine)",
        error_log_snippet="panic: send on closed channel\n  File 'pipeline.go', line 28\n    ch <- result  // sending on channel that was already closed by another goroutine",
        tried_methods="Used select with closed detection; used additional done channel",
        final_solution="Use a 'done' channel pattern: select { case <-done: return; case ch <- result: } Only the sender should close the channel.",
        project_name="sample-go",
        tech_stack="Go",
    ),
    dict(
        bug_title="Go: JSON unmarshal type mismatch (string vs number)",
        error_log_snippet='json: cannot unmarshal number into Go struct field User.ID of type string\n  File "handler.go", line 20\n    json.Unmarshal(data, &user)\nJSON has "id": 123, but Go struct has ID string.',
        tried_methods="Changed struct field type; used json.Number; used custom unmarshaler",
        final_solution='Match struct types with JSON types: use json:",string" tag or int type for numeric JSON fields: ID int64 `json:\\"id\\"`',
        project_name="sample-go",
        tech_stack="Go, JSON",
    ),
    # ────────────────────────────────────────────────────────────────
    # Java 异常 (10 条)
    # ────────────────────────────────────────────────────────────────
    dict(
        bug_title="Java: NullPointerException on uninitialized object",
        error_log_snippet="Exception in thread 'main' java.lang.NullPointerException\n  File 'OrderService.java', line 28\n    order.getTotal()  // order is null; findOrder() returned null",
        tried_methods="Added if (order != null) check; used Optional.ofNullable()",
        final_solution="Use Optional: return Optional.ofNullable(order).map(Order::getTotal).orElse(0.0). Always handle null returns from repository.",
        project_name="sample-java",
        tech_stack="Java",
    ),
    dict(
        bug_title="Java: ConcurrentModificationException while iterating list",
        error_log_snippet="Exception in thread 'main' java.util.ConcurrentModificationException\n  File 'Cache.java', line 30\n    for (String key : map.keySet()) {\n        if (expired(key)) map.remove(key);\n    }\nModifying map while iterating over it.",
        tried_methods="Used Iterator.remove(); copied keys before iteration",
        final_solution="Use iterator: Iterator<String> it = map.keySet().iterator(); while (it.hasNext()) { it.next(); if (expired(key)) it.remove(); }",
        project_name="sample-java",
        tech_stack="Java",
    ),
    dict(
        bug_title="Java: ArrayIndexOutOfBoundsException",
        error_log_snippet="Exception in thread 'main' java.lang.ArrayIndexOutOfBoundsException: Index 5 out of bounds for length 5\n  File 'Matrix.java', line 22\n    int val = arr[i];  // i=5, arr.length=5 (valid indices: 0-4)",
        tried_methods="Checked boundaries with if (i < arr.length); used for-each loop",
        final_solution="Validate index: if (i >= 0 && i < arr.length) { val = arr[i]; }. Prefer enhanced for-loop for safe iteration.",
        project_name="sample-java",
        tech_stack="Java",
    ),
    dict(
        bug_title="Java: ClassNotFoundException for JDBC driver",
        error_log_snippet="java.lang.ClassNotFoundException: com.mysql.cj.jdbc.Driver\n  File 'Database.java', line 10\n    Class.forName('com.mysql.cj.jdbc.Driver')\nJDBC driver not in classpath.",
        tried_methods="Added mysql-connector-java to pom.xml; checked dependency scope",
        final_solution="Ensure JDBC driver dependency is in runtime scope. For modern apps, let the connection pool manage drivers automatically.",
        project_name="sample-java",
        tech_stack="Java, JDBC",
    ),
    dict(
        bug_title="Java: StringIndexOutOfBoundsException with substring",
        error_log_snippet="Exception in thread 'main' java.lang.StringIndexOutOfBoundsException: begin 5, end 10, length 7\n  File 'Parser.java', line 15\n    String part = text.substring(5, 10);\ntext has only 7 characters.",
        tried_methods="Checked text.length() before substring; used Math.min()",
        final_solution="Clamp bounds: int end = Math.min(start + length, text.length()); if (start < end) { part = text.substring(start, end); }",
        project_name="sample-java",
        tech_stack="Java",
    ),
    dict(
        bug_title="Java: NumberFormatException parsing user input",
        error_log_snippet="Exception in thread 'main' java.lang.NumberFormatException: For input string: '12a'\n  File 'Input.java', line 20\n    int age = Integer.parseInt(input);\nUser entered '12a' instead of a valid number.",
        tried_methods="Used try/catch NumberFormatException; validated with regex",
        final_solution="Use try/catch: try { int age = Integer.parseInt(input); } catch (NumberFormatException e) { showError('Invalid number'); }",
        project_name="sample-java",
        tech_stack="Java",
    ),
    dict(
        bug_title="Java: StackOverflowError from recursive method without base case",
        error_log_snippet="Exception in thread 'main' java.lang.StackOverflowError\n  File 'Factorial.java', line 10\n    return n * factorial(n - 1);  // no base case for n <= 1",
        tried_methods="Added base case; converted to iterative",
        final_solution="Always include base case: if (n <= 1) return 1; return n * factorial(n - 1). For deep recursion, use iteration.",
        project_name="sample-java",
        tech_stack="Java",
    ),
    dict(
        bug_title="Java: FileNotFoundException for resource file",
        error_log_snippet="java.io.FileNotFoundException: class path resource [config.properties] cannot be opened\n  File 'AppConfig.java', line 12\n    new ClassPathResource('config.properties').getInputStream()\nResource not in classpath.",
        tried_methods="Checked file location in resources/; used getResourceAsStream()",
        final_solution="Use getClass().getResourceAsStream('/config.properties'). Ensure resource files are in src/main/resources/.",
        project_name="sample-java",
        tech_stack="Java, Spring",
    ),
    dict(
        bug_title="Java: UnsupportedOperationException from Arrays.asList()",
        error_log_snippet="java.lang.UnsupportedOperationException\n  File 'ListOps.java', line 18\n    list.add('new item');  // list = Arrays.asList(...) returns fixed-size list\nArrays.asList() returns a fixed-size list backed by the array.",
        tried_methods="Used new ArrayList<>(Arrays.asList(...)); used List.of()",
        final_solution="Wrap with mutable list: List<String> list = new ArrayList<>(Arrays.asList(items)). Arrays.asList() returns fixed-size, not resizable.",
        project_name="sample-java",
        tech_stack="Java",
    ),
    # ────────────────────────────────────────────────────────────────
    # TypeScript / 通用 (10 条)
    # ────────────────────────────────────────────────────────────────
    dict(
        bug_title="TypeScript: Type 'undefined' is not assignable to type 'string'",
        error_log_snippet="Type 'undefined' is not assignable to type 'string'.\n  File 'config.ts', line 22\n    const name: string = process.env.NAME;\nprocess.env.NAME can be undefined, but type says string.",
        tried_methods="Used string | undefined; added ?? default value",
        final_solution="const name: string = process.env.NAME ?? 'default'. Always handle potentially undefined values from external sources.",
        project_name="sample-ts",
        tech_stack="TypeScript",
    ),
    dict(
        bug_title="TypeScript: Object is possibly 'null'",
        error_log_snippet="Object is possibly 'null'.\n  File 'component.tsx', line 30\n    element.textContent = value;\nelement can be null (document.getElementById returns HTMLElement | null).",
        tried_methods="Added ! non-null assertion; added null check",
        final_solution="Use optional chaining or null check: if (element) { element.textContent = value; } or element!.textContent as last resort.",
        project_name="sample-ts",
        tech_stack="TypeScript",
    ),
    dict(
        bug_title="TypeScript: Cannot find module or its corresponding type declarations",
        error_log_snippet="Cannot find module 'some-lib' or its corresponding type declarations.\n  File 'app.ts', line 1\n    import { parse } from 'some-lib';\n  Type definitions for the package are missing.",
        tried_methods="Installed @types/some-lib; created custom .d.ts",
        final_solution="Install types: npm install --save-dev @types/some-lib. Or create a declaration file: declare module 'some-lib'.",
        project_name="sample-ts",
        tech_stack="TypeScript",
    ),
    dict(
        bug_title="Docker: Container exits immediately with code 1",
        error_log_snippet="docker run my-app  →  exit code 1 (immediately)\n  File 'Dockerfile'\n  ENTRYPOINT ['python', 'app.py']\n  app.py has a syntax error; container exits before producing output.",
        tried_methods="Checked docker logs; ran locally with same command",
        final_solution="Always test the entrypoint command locally first. Use CMD instead of ENTRYPOINT for debuggability. Add healthcheck.",
        project_name="sample-docker",
        tech_stack="Docker, Python",
    ),
    dict(
        bug_title="Git: merge conflict resolution leaving conflict markers",
        error_log_snippet="<<<<<<< HEAD\n  const port = 3000;\n=======\n  const port = 8080;\n>>>>>>> feature-branch\nConflict markers left in committed file (runtime error).",
        tried_methods="Searched for <<<<< in codebase; used git mergetool",
        final_solution="Search for conflict markers before committing: git diff --check. Always resolve all conflicts before commit.",
        project_name="sample-git",
        tech_stack="Git",
    ),
    dict(
        bug_title="SQL: column 'id' specified twice (duplicate column)",
        error_log_snippet="ERROR: column 'id' specified more than once\n  File 'query.sql', line 5\n    SELECT u.id, u.name, u.id FROM users u  // id selected twice",
        tried_methods="Removed duplicate column; used u.* and specified unique columns",
        final_solution="Ensure unique column names in SELECT: SELECT u.id AS user_id, u.name, ... Avoid SELECT * in production queries.",
        project_name="sample-sql",
        tech_stack="SQL, PostgreSQL",
    ),
    dict(
        bug_title="SQL: deadlock detected in concurrent transactions",
        error_log_snippet="ERROR: deadlock detected\n  DETAIL: Process 123 waits for ShareLock on transaction 456; blocked by process 789.\nTwo transactions acquiring locks in different order.",
        tried_methods="Set statement_timeout; used advisory locks",
        final_solution="Always acquire locks in the same order across all transactions. Use NOWAIT or SKIP LOCKED for contention tolerance.",
        project_name="sample-sql",
        tech_stack="SQL, PostgreSQL",
    ),
    dict(
        bug_title="YAML: mapping values are not allowed here (indentation error)",
        error_log_snippet="yaml.scanner.ScannerError: mapping values are not allowed here\n  File 'config.yaml', line 8\n    key: value\n      nested: wrong  # extra spaces before 'nested'",
        tried_methods="Used a YAML linter; checked indentation (2 spaces, consistent)",
        final_solution="Use consistent 2-space indentation. All nested keys must be indented exactly 2 spaces more than their parent. Use a YAML linter.",
        project_name="sample-yaml",
        tech_stack="YAML",
    ),
    dict(
        bug_title="PostgreSQL: column reference 'id' is ambiguous",
        error_log_snippet="ERROR: column reference 'id' is ambiguous\n  File 'query.sql', line 20\n    SELECT id FROM users JOIN orders ON users.id = orders.user_id\nBoth users and orders have 'id' column.",
        tried_methods="Used table alias: SELECT u.id FROM users u JOIN ...",
        final_solution="Always qualify column names with table aliases: SELECT u.id, o.id AS order_id FROM users u JOIN orders o ON ...",
        project_name="sample-sql",
        tech_stack="SQL, PostgreSQL",
    ),
]

# ===================================================================
#  100 条带标注的测试查询
# ===================================================================

Scenario = Literal["fact", "cross_doc", "no_answer"]


@dataclass
class TestCase:
    """一条测试查询，包含 ground truth 标注。"""

    query: str
    scenario: Scenario  # 场景分类
    relevant_indices: list[int] = field(default_factory=list)
    # ^ BUG_RECORDS 列表中的索引（从 0 开始）
    # fact: 1-3 条相关记录
    # cross_doc: 3 条以上相关记录
    # no_answer: 空列表


# ── 40 条 Fact Retrieval（直接匹配特定 bug）─────────────────────
TEST_CASES_FACT: list[TestCase] = [
    TestCase(
        query="KeyError when accessing missing dict key 'username'",
        scenario="fact",
        relevant_indices=[0, 20],
    ),
    TestCase(
        query="TypeError: unsupported operand type(s) for +: int and str",
        scenario="fact",
        relevant_indices=[1],
    ),
    TestCase(
        query="'NoneType' object is not subscriptable when accessing response data",
        scenario="fact",
        relevant_indices=[2],
    ),
    TestCase(
        query="ValueError: invalid literal for int() with base 10: 'abc123'",
        scenario="fact",
        relevant_indices=[3],
    ),
    TestCase(
        query="list index out of range in CSV reader",
        scenario="fact",
        relevant_indices=[4],
    ),
    TestCase(
        query="ModuleNotFoundError: No module named 'requests'",
        scenario="fact",
        relevant_indices=[5],
    ),
    TestCase(
        query="ImportError: cannot import name 'flatten' from 'itertools' in Python 3.10",
        scenario="fact",
        relevant_indices=[6],
    ),
    TestCase(
        query="AttributeError: 'str' object has no attribute 'append'",
        scenario="fact",
        relevant_indices=[7],
    ),
    TestCase(
        query="ZeroDivisionError: division by zero when computing average",
        scenario="fact",
        relevant_indices=[8],
    ),
    TestCase(
        query="FileNotFoundError when opening config.yaml",
        scenario="fact",
        relevant_indices=[9, 28],
    ),
    TestCase(
        query="UnboundLocalError: local variable referenced before assignment",
        scenario="fact",
        relevant_indices=[10],
    ),
    TestCase(
        query="RecursionError: maximum recursion depth exceeded in tree traversal",
        scenario="fact",
        relevant_indices=[11],
    ),
    TestCase(
        query="Python mutable default argument in function definition",
        scenario="fact",
        relevant_indices=[12],
    ),
    TestCase(
        query="PicklingError: Can't pickle lambda function in multiprocessing",
        scenario="fact",
        relevant_indices=[13],
    ),
    TestCase(
        query="StopIteration when calling next() on exhausted iterator",
        scenario="fact",
        relevant_indices=[14],
    ),
    TestCase(
        query="TypeError: 'int' object is not iterable — function returned single int instead of list",
        scenario="fact",
        relevant_indices=[15, 46],
    ),
    TestCase(
        query="async RuntimeError: asyncio.run() called from running event loop",
        scenario="fact",
        relevant_indices=[22],
    ),
    TestCase(
        query="UnicodeEncodeError: 'ascii' codec can't encode Chinese characters",
        scenario="fact",
        relevant_indices=[19],
    ),
    TestCase(
        query="MemoryError: unable to allocate large NumPy array",
        scenario="fact",
        relevant_indices=[20],
    ),
    TestCase(
        query="JavaScript: Cannot read properties of undefined (reading 'data')",
        scenario="fact",
        relevant_indices=[40],
    ),
    TestCase(
        query="React Cannot read property 'map' of undefined for prop items",
        scenario="fact",
        relevant_indices=[41, 43],
    ),
    TestCase(
        query="ReferenceError: Cannot access 'x' before initialization in TDZ",
        scenario="fact",
        relevant_indices=[42],
    ),
    TestCase(
        query="TypeError: Assignment to constant variable with const MAX_RETRIES",
        scenario="fact",
        relevant_indices=[47],
    ),
    TestCase(
        query="JavaScript: this is undefined in class method callback",
        scenario="fact",
        relevant_indices=[48],
    ),
    TestCase(
        query="Node.js ERR_REQUIRE_ESM: require() of ES Module not supported",
        scenario="fact",
        relevant_indices=[49],
    ),
    TestCase(
        query="TypeError: cyclic object value when using JSON.stringify",
        scenario="fact",
        relevant_indices=[50],
    ),
    TestCase(
        query="npm ERESOLVE unable to resolve peer dependency tree",
        scenario="fact",
        relevant_indices=[52],
    ),
    TestCase(
        query="Promise: Unhandled promise rejection — no catch handler",
        scenario="fact",
        relevant_indices=[44, 54],
    ),
    TestCase(
        query="Go: nil pointer dereference on config after LoadConfig()",
        scenario="fact",
        relevant_indices=[56],
    ),
    TestCase(
        query="Go: index out of range on empty slice",
        scenario="fact",
        relevant_indices=[57, 4],
    ),
    TestCase(
        query="Go: concurrent map read and map write (race condition)",
        scenario="fact",
        relevant_indices=[58],
    ),
    TestCase(
        query="Go: close of closed channel panic",
        scenario="fact",
        relevant_indices=[59, 61],
    ),
    TestCase(
        query="Go: sql: no rows in result set (sql.ErrNoRows)",
        scenario="fact",
        relevant_indices=[61],
    ),
    TestCase(
        query="Java: NullPointerException on uninitialized order object",
        scenario="fact",
        relevant_indices=[64],
    ),
    TestCase(
        query="Java: ConcurrentModificationException when removing from map during iteration",
        scenario="fact",
        relevant_indices=[65],
    ),
    TestCase(
        query="Java: ArrayIndexOutOfBoundsException — index 5 in array length 5",
        scenario="fact",
        relevant_indices=[66, 57],
    ),
    TestCase(
        query="Java: NumberFormatException parsing user input '12a'",
        scenario="fact",
        relevant_indices=[69],
    ),
    TestCase(
        query="TypeScript: Type 'undefined' is not assignable to type 'string' for env var",
        scenario="fact",
        relevant_indices=[74],
    ),
    TestCase(
        query="TypeScript: Object is possibly 'null' getElementById",
        scenario="fact",
        relevant_indices=[75],
    ),
    TestCase(
        query="TypeScript: Cannot find module or its corresponding type declarations",
        scenario="fact",
        relevant_indices=[76],
    ),
]

# ── 30 条 Cross-Document Synthesis（需要跨记录综合）───────────────
TEST_CASES_CROSS_DOC: list[TestCase] = [
    TestCase(
        query="Why do I keep getting NoneType errors in my Python code?",
        scenario="cross_doc",
        relevant_indices=[2, 33, 64],
    ),
    TestCase(
        query="How to safely handle dictionary key access in Python?",
        scenario="cross_doc",
        relevant_indices=[0, 21, 29],
    ),
    TestCase(
        query="Common causes of TypeError in Python type operations",
        scenario="cross_doc",
        relevant_indices=[1, 15, 22, 25, 37],
    ),
    TestCase(
        query="How to fix circular import issues in Python?",
        scenario="cross_doc",
        relevant_indices=[18, 25],
    ),
    TestCase(
        query="Why does my Python code fail with ValueError and how to fix it?",
        scenario="cross_doc",
        relevant_indices=[3, 24, 30, 69],
    ),
    TestCase(
        query="How to fix list/array index out of bounds errors across languages?",
        scenario="cross_doc",
        relevant_indices=[4, 57, 66],
    ),
    TestCase(
        query="Best practices for error handling when using JSON APIs",
        scenario="cross_doc",
        relevant_indices=[21, 40, 44, 62],
    ),
    TestCase(
        query="How to properly handle file operations in Python?",
        scenario="cross_doc",
        relevant_indices=[9, 27, 28],
    ),
    TestCase(
        query="Common mistakes with Python imports and modules",
        scenario="cross_doc",
        relevant_indices=[5, 6, 18, 25],
    ),
    TestCase(
        query="Why does my code say 'object has no attribute' and how to debug?",
        scenario="cross_doc",
        relevant_indices=[7, 18, 26],
    ),
    TestCase(
        query="How to avoid recursion and stack overflow errors?",
        scenario="cross_doc",
        relevant_indices=[11, 70],
    ),
    TestCase(
        query="Concurrency and threading issues in Python and Go",
        scenario="cross_doc",
        relevant_indices=[32, 58, 59, 61, 65],
    ),
    TestCase(
        query="How to handle null/undefined values safely in JavaScript?",
        scenario="cross_doc",
        relevant_indices=[40, 41, 43, 48],
    ),
    TestCase(
        query="Common JavaScript async/await and Promise mistakes",
        scenario="cross_doc",
        relevant_indices=[44, 54],
    ),
    TestCase(
        query="Why does this == undefined in my JavaScript callback?",
        scenario="cross_doc",
        relevant_indices=[48, 43],
    ),
    TestCase(
        query="How to properly use channels in Go to avoid panics?",
        scenario="cross_doc",
        relevant_indices=[59, 61],
    ),
    TestCase(
        query="Type errors when converting between string and number (cross-language)",
        scenario="cross_doc",
        relevant_indices=[1, 3, 30, 62, 69],
    ),
    TestCase(
        query="Java: Common exceptions when working with collections",
        scenario="cross_doc",
        relevant_indices=[65, 66, 73],
    ),
    TestCase(
        query="Database error patterns across Go and Java",
        scenario="cross_doc",
        relevant_indices=[61, 71],
    ),
    TestCase(
        query="How to fix dependency and module resolution issues?",
        scenario="cross_doc",
        relevant_indices=[5, 6, 49, 52, 71, 76],
    ),
    TestCase(
        query="Why does my Python function behave differently on second call?",
        scenario="cross_doc",
        relevant_indices=[12, 31],
    ),
    TestCase(
        query="Parsing and string manipulation errors across languages",
        scenario="cross_doc",
        relevant_indices=[3, 24, 30, 69],
    ),
    TestCase(
        query="JSON serialization and deserialization pitfalls",
        scenario="cross_doc",
        relevant_indices=[50, 62],
    ),
    TestCase(
        query="How to handle large datasets without memory errors?",
        scenario="cross_doc",
        relevant_indices=[20, 32],
    ),
    TestCase(
        query="Iteration errors: why can't I modify this while looping?",
        scenario="cross_doc",
        relevant_indices=[14, 32, 36, 65],
    ),
    TestCase(
        query="Type casting and type assertion patterns (Python/Go/Java)",
        scenario="cross_doc",
        relevant_indices=[1, 37, 60, 69],
    ),
    TestCase(
        query="Configuration file loading errors across tech stacks",
        scenario="cross_doc",
        relevant_indices=[9, 56, 71, 78],
    ),
    TestCase(
        query="SQL query errors: ambiguous columns and deadlocks",
        scenario="cross_doc",
        relevant_indices=[78, 79],
    ),
    TestCase(
        query="React and Vue lifecycle and state management pitfalls",
        scenario="cross_doc",
        relevant_indices=[41, 46, 48, 55],
    ),
    TestCase(
        query="What causes KeyError and how to prevent it in Python dict operations",
        scenario="cross_doc",
        relevant_indices=[0, 21, 29],
    ),
]

# ── 30 条 No-Answer（知识库中不存在的场景）───────────────────────
TEST_CASES_NO_ANSWER: list[TestCase] = [
    TestCase(query="Kubernetes pod CrashLoopBackOff: how to debug?", scenario="no_answer"),
    TestCase(query="React useEffect dependency array causing infinite re-renders", scenario="no_answer"),
    TestCase(query="How to optimize PostgreSQL query performance with indexes?", scenario="no_answer"),
    TestCase(query="Docker Compose network configuration for multi-service apps", scenario="no_answer"),
    TestCase(query="AWS S3 bucket policy for static website hosting", scenario="no_answer"),
    TestCase(query="CSS Grid vs Flexbox for responsive layout design", scenario="no_answer"),
    TestCase(query="How to implement OAuth2 authentication in Django REST Framework?", scenario="no_answer"),
    TestCase(query="Terraform best practices for managing AWS infrastructure", scenario="no_answer"),
    TestCase(query="Redis cache invalidation strategies for web applications", scenario="no_answer"),
    TestCase(query="How to set up CI/CD pipeline with GitHub Actions?", scenario="no_answer"),
    TestCase(query="Microservice communication patterns: gRPC vs message queue", scenario="no_answer"),
    TestCase(query="How to implement rate limiting in a Node.js API?", scenario="no_answer"),
    TestCase(query="Kafka consumer group rebalancing issues and solutions", scenario="no_answer"),
    TestCase(query="Python multiprocessing Pool vs Process for CPU-bound tasks", scenario="no_answer"),
    TestCase(query="How to configure nginx as a reverse proxy for multiple services?", scenario="no_answer"),
    TestCase(query="Linux kernel panic after system update — how to recover?", scenario="no_answer"),
    TestCase(query="How to implement WebSocket reconnection logic with exponential backoff?", scenario="no_answer"),
    TestCase(query="MongoDB aggregation pipeline optimization techniques", scenario="no_answer"),
    TestCase(query="How to handle CORS errors in a React + Express application?", scenario="no_answer"),
    TestCase(query="SwiftUI @State vs @Binding vs @ObservedObject differences", scenario="no_answer"),
    TestCase(query="How to use MLflow for experiment tracking in machine learning projects?", scenario="no_answer"),
    TestCase(query="Prometheus+Grafana monitoring setup for production services", scenario="no_answer"),
    TestCase(query="How to implement feature flags using LaunchDarkly or Unleash?", scenario="no_answer"),
    TestCase(query="Elasticsearch query DSL for full-text search across multiple fields", scenario="no_answer"),
    TestCase(query="How to implement server-sent events (SSE) in a FastAPI application?", scenario="no_answer"),
    TestCase(query="Android Kotlin coroutine scope management in ViewModel", scenario="no_answer"),
    TestCase(query="How to set up a monorepo with Turborepo for frontend and backend?", scenario="no_answer"),
    TestCase(query="Webpack vs Vite for modern frontend build tooling", scenario="no_answer"),
    TestCase(query="How to implement data pagination in GraphQL with cursor-based approach?", scenario="no_answer"),
    TestCase(query="RabbitMQ message TTL and dead letter exchange configuration", scenario="no_answer"),
]

# ── 汇总 ────────────────────────────────────────────────────────────

def get_test_cases() -> list[TestCase]:
    """返回全部 100 条测试用例（fact + cross_doc + no_answer）。"""
    return TEST_CASES_FACT + TEST_CASES_CROSS_DOC + TEST_CASES_NO_ANSWER


def get_test_case_summary() -> dict:
    """返回测试集统计摘要。"""
    cases = get_test_cases()
    fact = [c for c in cases if c.scenario == "fact"]
    cross = [c for c in cases if c.scenario == "cross_doc"]
    no_ans = [c for c in cases if c.scenario == "no_answer"]
    return {
        "total": len(cases),
        "fact": len(fact),
        "cross_doc": len(cross),
        "no_answer": len(no_ans),
        "total_bug_records": len(BUG_RECORDS),
    }
