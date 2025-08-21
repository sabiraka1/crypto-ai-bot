import sys
from scripts.arch_check import main as arch_main
def test_architecture_rules():
    rc = arch_main()
    assert rc == 0, "arch_check reported violations (see stdout for details)"
