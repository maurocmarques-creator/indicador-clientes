#!/usr/bin/env python3
"""
nf_status.py — Status Nota Fiscal (Confirmacao de Coleta + Posicao NF) do
Indicador Clientes: transforma o relatorio de Notas Fiscais do portal
Brudam (todos os clientes, das bases AZ e PEX) em linhas da tabela
public.nf_status do Supabase.

As regras sao as mesmas do indicador-ansell (pipeline_atualizar.py de la):
  - minuta sem NF nao entra;
  - "Coletada" a partir do STATUS CT-e (Autorizado/Criado = Coletado;
    Cancelado = Nao Coletado; em branco = NF Recebida e Nao Coletado);
  - celula com varias NFs vira uma linha por NF;
  - NF cancelada/pendente reemitida depois em outra minuta sai da lista
    principal e vai pro "historico" da linha Coletado.
Diferenca: com varios clientes, a NF so e considerada "a mesma" dentro do
mesmo cliente (o numero de NF se repete entre clientes diferentes).

O ID de carregamento e um cadastro do indicador-ansell (NF -> ID); aqui ele
e lido (so leitura) do index.html de la, e so se aplica aos clientes que
aparecem la.
"""

import json
import os
import re
from pathlib import Path

import pandas as pd
import requests

import atualizar_dashboard as ad
import supabase_db as db

ANSELL_INDEX = Path(os.environ.get(
    "ANSELL_INDEX_HTML", r"G:\Meu Drive\Claude\Mauro\indicador-ansell\index.html"))
PREFIXO_MINUTA_PEX = "PEX-"


def _chave(nome):
    return str(nome or "").strip().lower()


def fmt_data(v):
    """Data do Excel (Timestamp ou 'DD/MM/AAAA') -> 'AAAA-MM-DD', ou ''."""
    if v is None or v == "" or (isinstance(v, float) and pd.isna(v)):
        return ""
    try:
        if isinstance(v, str):
            return pd.to_datetime(v, dayfirst=True).strftime("%Y-%m-%d")
        return pd.Timestamp(v).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return ""


def mapear_coletada(status_cte):
    if pd.isna(status_cte) or not str(status_cte).strip():
        return "NF Recebida e Não Coletado"
    s = str(status_cte).strip().lower()
    if s.startswith("autorizado") or s.startswith("criado"):
        return "Coletado"
    if s.startswith("cancelado"):
        return "Não Coletado"
    return status_cte


def expandir_notas_multiplas(df):
    linhas = []
    for _, r in df.iterrows():
        nfs = [n.strip() for n in str(r["NF/DOC"]).split(",") if n.strip()]
        datas = [d.strip() for d in str(r["NF DATA"]).split(",")]
        if len(nfs) <= 1 or len(nfs) != len(datas):
            linhas.append(r)
            continue
        for nf, data in zip(nfs, datas):
            nova = r.copy()
            nova["NF/DOC"] = nf
            nova["NF DATA"] = data
            linhas.append(nova)
    return pd.DataFrame(linhas).reset_index(drop=True)


def separar_historico(df):
    """Igual ao do Ansell, mas a chave de agrupamento e (cliente, 1a nota).
    Retorna (df_principal, historico_por_posicao)."""
    df = df.reset_index(drop=True)

    def primeira_nota(cel):
        partes = [n.strip() for n in str(cel).split(",") if n.strip()]
        return partes[0] if partes else None

    chave = [(c, primeira_nota(n)) for c, n in zip(df["CLIENTE"], df["NF/DOC"])]
    pos_coletado = {}
    for i, (k, coletada) in enumerate(zip(chave, df["Coletada"])):
        if coletada == "Coletado" and k[1] is not None and k not in pos_coletado:
            pos_coletado[k] = i
    historico_por_pai, indices_historico = {}, set()
    for i, (k, coletada) in enumerate(zip(chave, df["Coletada"])):
        if coletada != "Coletado" and k in pos_coletado:
            historico_por_pai.setdefault(pos_coletado[k], []).append(i)
            indices_historico.add(i)
    df_principal = df.drop(index=list(indices_historico)).reset_index(drop=True)
    mapa_pos_nova, pos_nova = {}, 0
    for i in range(len(df)):
        if i in indices_historico:
            continue
        mapa_pos_nova[i] = pos_nova
        pos_nova += 1
    historico_por_posicao = {
        mapa_pos_nova[pai]: [df.iloc[f] for f in filhos] for pai, filhos in historico_por_pai.items()
    }
    return df_principal, historico_por_posicao


def ids_carregamento_do_ansell():
    """{(cliente_minusculo, nf): id_carregamento} lido do index.html do
    Ansell (somente leitura). Vazio se o arquivo nao estiver acessivel."""
    try:
        texto = ANSELL_INDEX.read_text(encoding="utf-8")
        m = re.search(r"^const NF_STATUS = (\[.*\]);\s*$", texto, re.M)
        itens = json.loads(m.group(1)) if m else []
    except Exception:
        return {}
    return {(_chave(i["cliente"]), str(i["nf"])): i["id_carregamento"] for i in itens if i.get("id_carregamento")}


def preparar(df, prefixo_minuta="", ignoradas=None):
    """Relatorio bruto de NFs de uma base -> lista de dicts (um por NF, com
    'historico' quando houver), ainda sem cliente_id."""
    df = df.fillna("").copy()
    df["MINUTA"] = prefixo_minuta + df["MINUTA"].astype(str)
    if ignoradas:
        ign = df.apply(lambda r: (_chave(r["CLIENTE"]), str(r["MINUTA"])) in ignoradas, axis=1)
        df = df[~ign]
    df = df[df["NF/DOC"].astype(str).str.strip() != ""]
    if df.empty:
        return []
    df["Coletada"] = df["STATUS CT-e"].apply(mapear_coletada)
    df = expandir_notas_multiplas(df)
    df, hist = separar_historico(df)
    ids = ids_carregamento_do_ansell()

    def linha(r):
        destino = str(r.get("DESTINO", ""))
        local = str(r.get("LOCAL ENTREGA", ""))
        if local and ad._normaliza_nome(local) == ad._normaliza_nome(destino):
            local = ""
        return {
            "minuta": str(r["MINUTA"]), "cte": str(r["CTE"]), "status_cte": str(r["STATUS CT-e"]),
            "nf": str(r["NF/DOC"]), "nf_data": fmt_data(r["NF DATA"]),
            "data_recebimento": fmt_data(r.get("DATA EMISSAO", "")),
            "cliente": str(r["CLIENTE"]), "destino": destino,
            "cidade_destino": str(r.get("CIDADE DESTINO", "")), "uf_destino": str(r.get("UF DESTINO", "")),
            "local_entrega": local,
            "cidade_entrega": str(r.get("CIDADE ENTREGA", "")), "uf_entrega": str(r.get("UF ENTREGA", "")),
            "coletada": str(r["Coletada"]),
            "id_carregamento": ids.get((_chave(r["CLIENTE"]), str(r["NF/DOC"])), ""),
        }

    saida = []
    for pos, (_, r) in enumerate(df.iterrows()):
        item = linha(r)
        if hist.get(pos):
            item["historico"] = [linha(h) for h in hist[pos]]
        saida.append(item)
    return saida


def gravar(itens_por_base, clientes, inicio_iso, log):
    """itens_por_base: {'az': [...], 'pex': [...]} (so as bases extraidas com
    sucesso). Upsert em public.nf_status e remocao do que sumiu, base a base
    (uma base que falhou nao tem as linhas dela apagadas)."""
    mapa = {}
    for c in clientes:
        for n in c.get("nomes_portal") or []:
            mapa.setdefault(_chave(n), c)

    # clientes que so tem minuta de status nao-emitido (ficam fora do relatorio
    # de emissoes) e por isso ainda nao existem: cadastra como pendente/inativo,
    # igual a descoberta automatica do pipeline
    novos = sorted({it["cliente"] for itens in itens_por_base.values() for it in itens
                    if it["cliente"] and _chave(it["cliente"]) not in mapa})
    for nome in novos:
        c = db.criar_cliente_pendente(nome)
        clientes.append(c)
        mapa[_chave(nome)] = c
    if novos:
        log(f"Clientes novos vindos do relatorio de NFs (pendentes, inativos): {', '.join(novos)}")

    headers = db._headers({"Prefer": "resolution=merge-duplicates,return=minimal"})
    ordem, total, sem_cliente, vistos = 0, 0, set(), set()
    for base, itens in itens_por_base.items():
        linhas = []
        for it in itens:
            c = mapa.get(_chave(it["cliente"]))
            if not c:
                sem_cliente.add(it["cliente"])
                continue
            chave = (c["id"], it["minuta"], it["nf"])
            if chave in vistos:
                continue  # mesma NF repetida na mesma minuta: mantem a primeira
            vistos.add(chave)
            linhas.append({
                "cliente_id": c["id"], "minuta": it["minuta"], "nf": it["nf"], "cte": it["cte"],
                "status_cte": it["status_cte"], "nf_data": it["nf_data"] or None,
                "data_recebimento": it["data_recebimento"] or None, "cliente": it["cliente"],
                "destino": it["destino"], "cidade_destino": it["cidade_destino"], "uf_destino": it["uf_destino"],
                "local_entrega": it["local_entrega"], "cidade_entrega": it["cidade_entrega"],
                "uf_entrega": it["uf_entrega"], "coletada": it["coletada"],
                "id_carregamento": it["id_carregamento"], "historico": it.get("historico"),
                "ordem": ordem, "atualizado_em": inicio_iso,
            })
            ordem += 1
        for lote in db._lotes(linhas, 300):
            r = requests.post(f"{db.REST_URL}/nf_status", headers=headers,
                              params={"on_conflict": "cliente_id,minuta,nf"}, json=lote, timeout=180)
            r.raise_for_status()
        total += len(linhas)
        if not linhas:
            log(f"NFs ({base}): nenhuma linha gravada -- nada removido.")
            continue
        filtro_base = {"minuta": f"like.{PREFIXO_MINUTA_PEX}*"} if base == "pex" else {"minuta": f"not.like.{PREFIXO_MINUTA_PEX}*"}
        r = requests.delete(f"{db.REST_URL}/nf_status", headers=db._headers({"Prefer": "return=representation"}),
                            params={**filtro_base, "atualizado_em": f"lt.{inicio_iso}"}, timeout=180)
        r.raise_for_status()
        log(f"NFs ({base}): {len(linhas)} gravadas, {len(r.json())} obsoletas removidas.")
    if sem_cliente:
        log(f"AVISO: NFs ignoradas (cliente nao cadastrado): {', '.join(sorted(map(str, sem_cliente))[:10])}")
    return total


def apagar_minutas(minutas_por_cliente, clientes, log):
    """Apaga de fretes, ocorrencias_historico e nf_status as minutas descartadas
    pela regra 'sem_cancelados' (o pipeline ja gravou os fretes delas antes de
    descobrir que o CT-e esta cancelado). {cliente_minusculo: {minutas}}"""
    mapa = {}
    for c in clientes:
        for nome in c.get("nomes_portal") or []:
            mapa.setdefault(_chave(nome), c)
    for cli, minutas in minutas_por_cliente.items():
        c = mapa.get(cli)
        if not c or not minutas:
            continue
        lista = "(" + ",".join(sorted(minutas)) + ")"
        for tabela in ("fretes", "ocorrencias_historico", "nf_status"):
            r = requests.delete(f"{db.REST_URL}/{tabela}", headers=db._headers({"Prefer": "return=representation"}),
                                params={"cliente_id": f"eq.{c['id']}", "minuta": f"in.{lista}"}, timeout=120)
            r.raise_for_status()
            log(f"Minutas canceladas de {c['nome']}: {len(r.json())} linha(s) removida(s) de {tabela}.")
