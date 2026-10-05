"""Fixed local tool schemas, strict arguments and non-executable arithmetic."""
import ast
import copy
from datetime import datetime
import math
import operator
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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


def definitions():
    return copy.deepcopy(TOOLS)


def validate(name, arguments):
    if name not in {"calculate", "get_current_time"}:
        raise ValueError("Unknown or forbidden tool")
    if not isinstance(arguments, dict):
        raise ValueError("Tool arguments must be an object")
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
    if name == "calculate":
        return calculate(arguments["expression"])
    zone = arguments.get("timezone", "Europe/London")
    return {"timezone": zone, "datetime": datetime.now(ZoneInfo(zone)).isoformat()}
