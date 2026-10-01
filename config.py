#!/usr/bin/env python3
"""
config.py — Carrega cliente_config.json (pasta deste script).

Os demais scripts (extrair_portal.py, atualizar_dashboard.py,
pipeline_atualizar.py) sao genericos e nao tem nada de "Ansell" hardcoded;
tudo que muda de cliente para cliente fica so no JSON. Para atender um
cliente novo: copie esta pasta inteira (vira um repo/dashboard proprio),
troque o cliente_config.json e crie a tarefa agendada apontando pra la.
"""

import json
from pathlib import Path

_PATH = Path(__file__).parent / "cliente_config.json"

with open(_PATH, encoding="utf-8") as _f:
    CONFIG = json.load(_f)
