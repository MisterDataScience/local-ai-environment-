"""Fixed local tool schemas, strict arguments and non-executable arithmetic."""
import ast
import copy
from datetime import datetime
import math
import operator
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from urllib.parse import urlsplit

WEB_NAMES = {"search_web", "read_page"}

TOOLS = [
    {"type": "function", "function": {"name": "get_current_time",
     "description": "Get the current date and time in an IANA timezone, e.g. Europe/London.",
     "parameters": {"type": "object", "properties": {"timezone": {"type": "string"}},
                    "required": [], "additionalProperties": False}}},
    {"type": "function", "function": {"name": "calculate",
     "description": "Calculate arithmetic with numbers, parentheses, +, -, *, /, //, %, **. No code or functions.",
     "parameters": {"type": "object", "properties": {"expression": {"type": "string"}},
                    "required": ["expression"], "additionalProperties": False}}},
]


WEB_TOOLS = [
    {"type": "function", "function": {"name": "search_web",
     "description": "Search the web through the isolated VPN service. Returns numbered sources and bounded evidence.",
     "parameters": {"type": "object", "properties": {"query": {"type": "string"}},
                    "required": ["query"], "additionalProperties": False}}},
    {"type": "function", "function": {"name": "read_page",
     "description": "Read one public HTML/plain-text URL through the VPN. No login, PDF or JavaScript support.",
     "parameters": {"type": "object", "properties": {"url": {"type": "string"}},
                    "required": ["url"], "additionalProperties": False}}},
]


def definitions(web_enabled=False):
    return copy.deepcopy(TOOLS + (WEB_TOOLS if web_enabled else []))


def validate(name, arguments):
    if name not in {"calculate", "get_current_time"} | WEB_NAMES:
        raise ValueError("Unknown or forbidden tool")
    if not isinstance(arguments, dict):
        raise ValueError("Tool arguments must be an object")
    if name in WEB_NAMES:
        field = "query" if name == "search_web" else "url"
        value = arguments.get(field)
        limit = 500 if field == "query" else 4096
        if set(arguments) != {field} or not isinstance(value, str) or not value.strip() or len(value) > limit:
            raise ValueError("Invalid web tool arguments")
        if field == "url":
            parsed = urlsplit(value)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or any(ord(c) < 33 for c in value):
                raise ValueError("Only HTTP/HTTPS URLs without credentials are allowed")
        return copy.deepcopy(arguments)
    allowed = {"expression"} if name == "calculate" else {"timezone"}
    if set(arguments) - allowed:
        raise ValueError("Unexpected tool arguments")
    if name == "calculate":
        expression = arguments.get("expression")
        if not isinstance(expression, str) or not 0 < len(expression) <= 256:
            raise ValueError("Expression must contain 1–256 characters")
    else:
        zone = arguments.get("timezone", "Europe/London")
        if not isinstance(zone, str) or not 0 < len(zone) <= 64:
            raise ValueError("Invalid timezone")
        try:
            ZoneInfo(zone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Unknown IANA timezone") from None
    return copy.deepcopy(arguments)


def calculate(expression):
    tree = ast.parse(expression, mode="eval")
    if sum(1 for _ in ast.walk(tree)) > 64:
        raise ValueError("Expression is too complex")
    operations = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
                  ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,
                  ast.Pow: operator.pow}

    def bounded(value):
        if type(value) not in {int, float} or not math.isfinite(value) or abs(value) > 1e100:
            raise ValueError("Result exceeds numeric limits")
        return value

    def visit(node):
        if isinstance(node, ast.Constant) and type(node.value) in {int, float}:
            return bounded(node.value)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            return bounded(visit(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1))
        if isinstance(node, ast.BinOp) and type(node.op) in operations:
            left, right = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 100:
                raise ValueError("Exponent exceeds limit")
            return bounded(operations[type(node.op)](left, right))
        raise ValueError("Only numeric arithmetic is permitted")

    return {"value": visit(tree.body)}


def invoke(name, arguments):
    arguments = validate(name, arguments)
    if name in WEB_NAMES:
        raise ValueError("Web tools require the authorised VPN executor")
    if name == "calculate":
        return calculate(arguments["expression"])
    zone = arguments.get("timezone", "Europe/London")
    return {"timezone": zone, "datetime": datetime.now(ZoneInfo(zone)).isoformat()}
