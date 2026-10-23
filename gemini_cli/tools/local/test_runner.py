"""Unittest в существующем процессе; итог читается из отдельного отчёта, не stdout."""
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from contextlib import nullcontext

from ...client.process import ManagedProcess
from ..results import failure, success

_WORKER = r'''
import json,sys,unittest
loader=unittest.TestLoader()
try:
    modules=json.loads(sys.argv[2])
    suite=loader.loadTestsFromNames(modules) if modules else loader.discover('tests')
    result=unittest.TextTestRunner(verbosity=1).run(suite)
    data={'completed':True,'tests_run':result.testsRun,'failures':len(result.failures),
          'errors':len(result.errors),'skipped':len(result.skipped),
          'discovery_errors':len(loader.errors),
          'failed_tests':[str(t)[:300] for t,_ in (result.failures+result.errors)[:50]]}
    passed=result.wasSuccessful() and not loader.errors and result.testsRun>0
except Exception:
    data={'completed':False,'discovery_errors':1};passed=False
with open(sys.argv[1],'w',encoding='utf-8') as stream: json.dump(data,stream)
sys.exit(0 if passed else 1)
'''


def run_tests(args: dict, root: str, *, approve, cancelled=lambda: False,
              monitor=nullcontext, on_process=None) -> dict:
    modules, timeout = args.get('modules', []), args.get('timeout', 120)
    if (not isinstance(modules, list) or len(modules) > 50
            or any(not isinstance(name, str) or len(name) > 200
                   or not re.fullmatch(r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*', name) for name in modules)
            or type(timeout) is not int or not 1 <= timeout <= 300):
        return failure('invalid_arguments', 'Нужны до 50 unittest-модулей и timeout 1–300 секунд')
    python = os.environ.get('GEMINI_CLI_PYTHON') or (sys.executable if not getattr(sys, 'frozen', False) else '')
    if not python or not os.path.isabs(python):
        return failure('unavailable', 'Задайте абсолютный GEMINI_CLI_PYTHON для запуска unittest')
    if not approve('Запустить unittest (исполняет код проекта): ' + (', '.join(modules) or 'discovery tests/')):
        return failure('denied', 'Запуск тестов отклонён')
    if cancelled():
        return failure('cancelled', 'Запуск отменён')
    process = None
    try:
        with tempfile.TemporaryDirectory(prefix='gemini-unittest-') as directory:
            report = Path(directory, 'result.json')
            process = ManagedProcess([python, '-c', _WORKER, str(report), json.dumps(modules)], root,
                                     env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONIOENCODING': 'utf-8'},
                                     limit=32768)
            if on_process:
                on_process(process)
            with monitor():
                status = process.wait(timeout=timeout, cancelled=cancelled)
            code = process.poll()
            data = {}
            if status == 'completed' and report.exists() and report.stat().st_size <= 65536:
                data = json.loads(report.read_text(encoding='utf-8'))
                if not isinstance(data, dict):
                    data = {}
            passed = (status == 'completed' and code == 0 and data.get('completed') is True
                      and type(data.get('tests_run')) is int and data['tests_run'] > 0
                      and all(data.get(key) == 0 for key in ('errors', 'failures', 'discovery_errors')))
            return {'status': 'ok' if passed else 'error', 'data': {
                'process_status': status, 'exit_code': code, 'passed': passed, 'report': data,
                'artifacts': [], 'stdout': process.stdout.read(), 'stderr': process.stderr.read()},
                'truncated': process.stdout.truncated or process.stderr.truncated,
                **({} if passed else {'error': {'code': status if status != 'completed' else 'tests_failed',
                                               'message': 'Проверка не пройдена или итог не подтверждён'}})}
    except (OSError, ValueError):
        return failure('runner_error', 'Не удалось запустить unittest или прочитать отчёт')
    finally:
        if process is not None:
            process.close()
