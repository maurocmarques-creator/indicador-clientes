#!/usr/bin/env python3
"""
supabase_db.py -- Acesso ao Supabase (projeto indicador-clientes) pelo
lado do pipeline (servidor), via REST (PostgREST), usando a service
role key -- que ignora RLS, ao contrario da publishable key usada no
navegador. NUNCA commitar essa chave: ela vem da variavel de ambiente
SUPABASE_SERVICE_ROLE_KEY (defina antes de rodar o pipeline).
"""

import os

import requests

SUPABASE_URL = "https://fydoatntynvcwudxkhqv.supabase.co"
REST_URL = f"{SUPABASE_URL}/rest/v1"

_LOTE = 500  # linhas por requisicao, pra nao estourar o limite do PostgREST


def _service_key():
    chave = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not chave:
        raise RuntimeError("Defina a variavel de ambiente SUPABASE_SERVICE_ROLE_KEY antes de rodar o pipeline.")
    return chave


def _headers(extra=None):
    chave = _service_key()
    headers = {
        "apikey": chave,
        "Authorization": f"Bearer {chave}",
        "Content-Type": "application/json",
    }
    if extra:
        headers.update(extra)
    return headers


def _lotes(lista, tamanho=_LOTE):
    for i in range(0, len(lista), tamanho):
        yield lista[i:i + tamanho]


def listar_clientes_ativos():
    """Todos os clientes ativos cadastrados (admin.html), com id, nome e
    nomes_portal -- usado pelo pipeline pra saber quem extrair do Brudam
    e pra que cliente_id gravar cada linha."""
    resp = requests.get(
        f"{REST_URL}/clientes",
        headers=_headers(),
        params={"select": "id,nome,nomes_portal", "ativo": "eq.true"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def upsert_fretes(linhas):
    """Insere/atualiza linhas de public.fretes (upsert por cliente_id+minuta).
    'linhas' e uma lista de dicts com exatamente as colunas da tabela."""
    if not linhas:
        return
    headers = _headers({"Prefer": "resolution=merge-duplicates,return=minimal"})
    for lote in _lotes(linhas):
        resp = requests.post(
            f"{REST_URL}/fretes",
            headers=headers,
            params={"on_conflict": "cliente_id,minuta"},
            json=lote,
            timeout=60,
        )
        resp.raise_for_status()


def ultima_ocorrencia_por_minuta(cliente_id):
    """{minuta: descricao} com a ultima ocorrencia ja registrada no
    historico pra cada minuta deste cliente -- usado pra decidir se uma
    ocorrencia nova precisa ser inserida (so insere quando a descricao
    mudou em relacao a ultima conhecida)."""
    resp = requests.get(
        f"{REST_URL}/ocorrencias_historico",
        headers=_headers(),
        params={
            "select": "minuta,descricao,detectado_em",
            "cliente_id": f"eq.{cliente_id}",
            "order": "minuta.asc,detectado_em.asc",
        },
        timeout=60,
    )
    resp.raise_for_status()
    ultimas = {}
    for linha in resp.json():
        ultimas[linha["minuta"]] = linha["descricao"]  # ordenado por data, a ultima sobrescreve
    return ultimas


def inserir_ocorrencias(linhas):
    """Insere novos eventos em public.ocorrencias_historico (sempre
    insert, nunca upsert -- e um historico append-only)."""
    if not linhas:
        return
    headers = _headers({"Prefer": "return=minimal"})
    for lote in _lotes(linhas):
        resp = requests.post(
            f"{REST_URL}/ocorrencias_historico",
            headers=headers,
            json=lote,
            timeout=60,
        )
        resp.raise_for_status()
