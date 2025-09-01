import sys
import locale
locale.setlocale(locale.LC_ALL, 'en_US.UTF-8')
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')
from importlinter import cli
cli.lint_imports(['--config', 'importlinter.ini', '--verbose'])
