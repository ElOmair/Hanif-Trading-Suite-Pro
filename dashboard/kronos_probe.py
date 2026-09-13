from __future__ import annotations

import ast
import json
import os
import re
from pathlib import Path

KRONOS_ROOT = Path('/home/airomair/Kronos')
FILES = {
    'trading.ensemble_forecast': KRONOS_ROOT / 'trading' / 'ensemble_forecast.py',
    'trading.decision_engine': KRONOS_ROOT / 'trading' / 'decision_engine.py',
    'trading.trade_plan': KRONOS_ROOT / 'trading' / 'trade_plan.py',
    'trading.options_selector': KRONOS_ROOT / 'trading' / 'options_selector.py',
}

INTERESTING_PATTERNS = (
    'NVDA', 'ALPACA_', 'load_dotenv', 'if __name__', 'symbol =', 'SYMBOL =',
    'forecast_paths', 'FORECAST_PATHS', 'select_option', 'select_options',
)


def _signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    try:
        args = ast.unparse(node.args)
    except Exception:
        args = '...'
    prefix = 'async ' if isinstance(node, ast.AsyncFunctionDef) else ''
    return f'{prefix}{node.name}({args})'


def _literal(value: ast.AST):
    try:
        return ast.literal_eval(value)
    except Exception:
        try:
            return ast.unparse(value)
        except Exception:
            return '<expression>'


def inspect_source(path: Path) -> dict[str, object]:
    source = path.read_text(encoding='utf-8')
    tree = ast.parse(source, filename=str(path))
    lines = source.splitlines()

    functions: list[str] = []
    classes: dict[str, list[str]] = {}
    assignments: dict[str, object] = {}
    top_level_calls: list[str] = []
    has_main_guard = False

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(_signature(node))
        elif isinstance(node, ast.ClassDef):
            methods = [
                _signature(child)
                for child in node.body
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
            classes[node.name] = methods
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = node.value
            for target in targets:
                if isinstance(target, ast.Name):
                    name = target.id
                    if any(token in name.lower() for token in ('symbol', 'path', 'feed', 'dte', 'delta')):
                        assignments[name] = _literal(value)
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            try:
                top_level_calls.append(ast.unparse(node.value.func))
            except Exception:
                top_level_calls.append('<call>')
        elif isinstance(node, ast.If):
            test_text = ast.unparse(node.test) if hasattr(ast, 'unparse') else ''
            if '__name__' in test_text and '__main__' in test_text:
                has_main_guard = True

    matches: list[dict[str, object]] = []
    for i, line in enumerate(lines, start=1):
        if any(pattern.lower() in line.lower() for pattern in INTERESTING_PATTERNS):
            safe = re.sub(r'(ALPACA_(?:API_KEY|SECRET_KEY)\s*=\s*)[^#\n]+', r'\1<redacted-expression>', line)
            matches.append({'line': i, 'text': safe.strip()[:240]})

    return {
        'path': str(path),
        'functions': functions,
        'classes': classes,
        'interesting_assignments': assignments,
        'top_level_calls': top_level_calls,
        'has_main_guard': has_main_guard,
        'interesting_lines': matches[:80],
    }


def main() -> None:
    if not KRONOS_ROOT.exists():
        raise SystemExit(f'Kronos root not found: {KRONOS_ROOT}')

    # Load no modules. The previous probe imported ensemble_forecast, which executed
    # its top-level NVDA forecast as a side effect. This version is static-only.
    os.chdir(KRONOS_ROOT)
    result: dict[str, object] = {
        'kronos_root': str(KRONOS_ROOT),
        'mode': 'static-source-only; no forecast executed',
        'modules': {},
    }
    for module_name, path in FILES.items():
        try:
            result['modules'][module_name] = inspect_source(path)
        except Exception as exc:
            result['modules'][module_name] = {'error': f'{type(exc).__name__}: {exc}'}

    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
