from __future__ import annotations

import importlib
import inspect
import json
import sys
from pathlib import Path

KRONOS_ROOT = Path('/home/airomair/Kronos')
MODULES = [
    'trading.ensemble_forecast',
    'trading.decision_engine',
    'trading.trade_plan',
    'trading.options_selector',
]


def public_callables(module_name: str) -> dict[str, str]:
    module = importlib.import_module(module_name)
    found: dict[str, str] = {}
    for name, obj in vars(module).items():
        if name.startswith('_') or not callable(obj):
            continue
        if inspect.isfunction(obj) and getattr(obj, '__module__', None) != module_name:
            continue
        if inspect.isclass(obj) and getattr(obj, '__module__', None) != module_name:
            continue
        try:
            found[name] = str(inspect.signature(obj))
        except (TypeError, ValueError):
            found[name] = '(signature unavailable)'
    return dict(sorted(found.items()))


def main() -> None:
    if not KRONOS_ROOT.exists():
        raise SystemExit(f'Kronos root not found: {KRONOS_ROOT}')
    sys.path.insert(0, str(KRONOS_ROOT))
    result: dict[str, object] = {'kronos_root': str(KRONOS_ROOT), 'modules': {}}
    for module_name in MODULES:
        try:
            result['modules'][module_name] = {'callables': public_callables(module_name)}
        except Exception as exc:
            result['modules'][module_name] = {'error': f'{type(exc).__name__}: {exc}'}
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
