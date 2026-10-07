#!/usr/bin/env python3
"""
sync_nf_status.py — Copia as notas fiscais (Status Nota Fiscal) do
indicador-ansell para a tabela public.nf_status do Supabase, de onde a
aba "Status Nota Fiscal" do indicador-clientes le.

O indicador-ansell NAO e alterado: o index.html dele so e LIDO (a lista
NF_STATUS embutida nele). Cada NF e ligada ao cliente do Supabase pelo
campo "cliente" (nome do portal -> clientes.nomes_portal).

Roda sozinho se o index.html do Ansell mudou desde a ultima copia (compara
a data de modificacao guardada em sync_nf_status.estado), ou sempre com
--forcar. Apos o upsert, apaga as linhas do cliente que nao vieram mais
nessa copia (NF que saiu do relatorio).

Uso:
  set SUPABASE_SERVICE_ROLE_KEY=...
  python sync_nf_status.py [--forcar]
"""

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

import supabase_db as db

ANSELL_INDEX = Path(os.environ.get(
    "ANSELL_INDEX_HTML", r"G:\Meu Drive\Claude\Mauro\indicador-ansell\index.html"))
ESTADO = Path(__file__).parent / "sync_nf_status.estado"
LOG_FILE = Path(__file__).parent / "pipeline.log"

CAMPOS = ["cte", "status_cte", "cliente", "destino", "cidade_destino", "uf_destino",
          "local_entrega", "cidade_entrega", "uf_entrega", "coletada", "id_carregamento"]


def log(msg):
    print(msg, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().strftime('%d/%m/%Y %H:%M:%S')} — [sync_nf] {msg}\n")
    except Exception:
        pass


def ler_nf_status():
    texto = ANSELL_INDEX.read_text(encoding="utf-8")
    m = re.search(r"^const NF_STATUS = (\[.*\]);\s*$", texto, re.M)
    if not m:
        raise RuntimeError("NF_STATUS nao encontrado no index.html do Ansell.")
    return json.loads(m.group(1))


def _chave(nome):
    return str(nome or "").strip().lower()


def _data(v):
    return v or None


def main():
    forcar = "--forcar" in sys.argv
    mtime = str(ANSELL_INDEX.stat().st_mtime)
    if not forcar and ESTADO.exists() and ESTADO.read_text().strip() == mtime:
        log("index.html do Ansell nao mudou desde a ultima copia -- nada a fazer.")
        return

    nfs = ler_nf_status()
    clientes = db.listar_clientes_todos()
    por_nome = {}
    for c in clientes:
        for n in c.get("nomes_portal") or []:
            por_nome.setdefault(_chave(n), c)

    inicio = datetime.now(timezone.utc).isoformat()
    linhas, sem_cliente = [], set()
    for ordem, r in enumerate(nfs):
        c = por_nome.get(_chave(r.get("cliente")))
        if not c:
            sem_cliente.add(r.get("cliente"))
            continue
        linha = {
            "cliente_id": c["id"], "minuta": str(r["minuta"]), "nf": str(r["nf"]),
            "nf_data": _data(r.get("nf_data")), "data_recebimento": _data(r.get("data_recebimento")),
            "historico": r.get("historico") or None, "ordem": ordem, "atualizado_em": inicio,
        }
        for k in CAMPOS:
            linha[k] = r.get(k) or ""
        linhas.append(linha)
    if sem_cliente:
        log(f"AVISO: NFs ignoradas, cliente nao cadastrado no Supabase: {', '.join(sorted(map(str, sem_cliente)))}")
    if not linhas:
        raise RuntimeError("Nenhuma NF para gravar -- abortando sem apagar nada.")

    headers = db._headers({"Prefer": "resolution=merge-duplicates,return=minimal"})
    for lote in db._lotes(linhas, 300):
        resp = requests.post(f"{db.REST_URL}/nf_status", headers=headers,
                             params={"on_conflict": "cliente_id,minuta,nf"}, json=lote, timeout=120)
        resp.raise_for_status()

    # NFs que sumiram do relatorio: apaga as linhas desses clientes nao tocadas nesta copia
    apagadas = 0
    for cid in {l["cliente_id"] for l in linhas}:
        resp = requests.delete(f"{db.REST_URL}/nf_status", headers=db._headers({"Prefer": "return=representation"}),
                               params={"cliente_id": f"eq.{cid}", "atualizado_em": f"lt.{inicio}"}, timeout=120)
        resp.raise_for_status()
        apagadas += len(resp.json())

    ESTADO.write_text(mtime)
    log(f"Copiadas {len(linhas)} NFs para o Supabase ({apagadas} obsoletas removidas).")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"ERRO: {e}")
        raise
