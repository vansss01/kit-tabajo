#!/usr/bin/env python3
"""Entrada portátil; ejecutar con el Python del entorno local."""
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from kitlib.runtime import configure

configure()
from kitlib.cli import main

raise SystemExit(main())
