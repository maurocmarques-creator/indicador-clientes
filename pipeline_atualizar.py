#!/usr/bin/env python3
"""
pipeline_atualizar.py — Pipeline completo do Indicador Clientes (multi-tenant):

  1. Extrai do portal Brudam o relatorio 106 (Emissoes) numa unica
     pesquisa, SEM filtro de cliente (traz todos de uma vez -- nao
     escalaria pedir uma extracao por cliente com centenas deles).
  2. Descobre, pela coluna CLIENTE de cada linha, quais nomes ainda nao
     batem com nenhum cliente cadastrado (nomes_portal) e cadastra esses
     automaticamente como pendentes (inativos) -- revisao continua manual
     em admin.html (ativar, ajustar nome, liberar paineis, vincular login).
  3. Pra cada cliente conhecido (ativo ou pendente): filtra as linhas
     dele dentro da planilha unica, converte em linhas e grava na tabela
     public.fretes do Supabase (upsert por cliente_id+minuta), e registra
     ocorrencias novas em public.ocorrencias_historico.
  4. Envia um e-mail de resumo.

Credenciais do portal vem de PORTAL_USER / PORTAL_PASS (variaveis de
ambiente) — nunca ficam no codigo. A gravacao no Supabase usa
SUPABASE_SERVICE_ROLE_KEY (ver supabase_db.py). O envio de e-mail usa
EMAIL_USER / EMAIL_PASS (conta Gmail + senha de app).

Ainda NAO inclui (continuam especificas do projeto indicador-ansell por
enquanto, ver supabase/PROJETO.md): correcoes manuais de status/data,
observacoes do Mural, motivo de ocorrencia, ID de carregamento, Status
NF (CT-e).

Uso:
  set PORTAL_USER=seu.usuario
  set PORTAL_PASS=sua.senha
  set SUPABASE_SERVICE_ROLE_KEY=sua.chave
  set EMAIL_USER=seu.email@gmail.com
  set EMAIL_PASS=sua.senha.de.app.do.gmail
  python pipeline_atualizar.py
"""

import os
import smtplib
import sys
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path

import pandas as pd
from playwright.sync_api import sync_playwright

import atualizar_dashboard as ad
import extrair_portal as ep
import supabase_db

REPO_DIR = Path(__file__).parent
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
EMAIL_DESTINO = "mauro.cesar@portoex.com.br"
PREFIXO_MINUTA_PEX = "PEX-"

LOG_FILE = REPO_DIR / "pipeline.log"
LOCK_FILE = REPO_DIR / "pipeline.lock"
LOCK_MAX_IDADE_MIN = 30  # acima disso, considera trava travada de uma execucao anterior que morreu


def log(msg):
    print(msg, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().strftime('%d/%m/%Y %H:%M:%S')} — {msg}\n")
    except Exception:
        pass  # logging nunca deve derrubar o pipeline


def extrair_tudo(usuario, senha, data_ini, data_fim, pasta_tmp: Path, base_url=ep.PORTAL_URL, nome_arquivo="todos.xlsx") -> Path:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()
        page.set_default_timeout(60000)

        try:
            ep.login(page, usuario, senha, base_url)
            destino = ep.extrair_todos(page, data_ini, data_fim, pasta_tmp, base_url, nome_arquivo)
        except Exception:
            diag_dir = pasta_tmp / "diagnostico" / nome_arquivo.replace(".xlsx", "")
            diag_dir.mkdir(parents=True, exist_ok=True)
            try:
                page.screenshot(path=str(diag_dir / "falha.png"), full_page=True)
                (diag_dir / "falha.html").write_text(page.content(), encoding="utf-8")
                log(f"Diagnostico salvo em: {diag_dir}")
            except Exception as diag_err:
                log(f"Nao foi possivel salvar diagnostico: {diag_err}")
            raise
        finally:
            browser.close()
    return destino


def _chave(nome):
    return str(nome or "").strip().lower()


def _mapear_por_nome_portal(clientes):
    """{nome_portal_normalizado: cliente}, avisando (e ignorando o
    repetido) se dois clientes declararem o mesmo nome de portal -- nao
    deveria acontecer (cadastro errado em admin.html), mas nao pode
    travar o pipeline pros demais clientes."""
    mapa = {}
    for c in clientes:
        for nome in c.get("nomes_portal") or []:
            chave = _chave(nome)
            if not chave:
                continue
            if chave in mapa:
                log(f"AVISO: nome de portal '{nome}' repetido em '{mapa[chave]['nome']}' e '{c['nome']}' -- mantendo o primeiro, confira o cadastro em admin.html.")
                continue
            mapa[chave] = c
    return mapa


def descobrir_clientes_novos(df, clientes_existentes):
    """Olha a coluna CLIENTE da extracao unica e cadastra (pendente,
    inativo) qualquer nome que nao bate com o nomes_portal de nenhum
    cliente ja conhecido (ativo ou nao). Retorna a lista de clientes
    atualizada (existentes + os novos recem-criados)."""
    mapa = _mapear_por_nome_portal(clientes_existentes)
    nomes_na_planilha = sorted(set(str(x).strip() for x in df["CLIENTE"].dropna().unique() if str(x).strip()))
    novos = [n for n in nomes_na_planilha if _chave(n) not in mapa]
    if not novos:
        return clientes_existentes
    log(f"Clientes novos descobertos na extracao (cadastrados como pendentes, inativos): {', '.join(novos)}")
    for nome in novos:
        cliente_novo = supabase_db.criar_cliente_pendente(nome)
        clientes_existentes.append(cliente_novo)
        mapa[_chave(nome)] = cliente_novo
    return clientes_existentes


def _valor_ou_none(v):
    return v if v else None


def _linha_para_frete(r, cliente_id):
    return {
        "cliente_id": cliente_id,
        "minuta": r["MINUTA"],
        "nf_doc": r["NF_DOC"],
        "mes": r["MES"],
        "mes_nome": r["MES_NOME"],
        "mes_prev": r["MES_PREV"],
        "mes_prev_nome": r["MES_PREV_NOME"],
        "status": r["STATUS"],
        "cliente_portal": r["CLIENTE"],
        "volumes": r["VOLUMES"],
        "frete_total": r["FRETE TOTAL"],
        "nf_valor": r["NF VALOR"],
        "peso": r["PESO"],
        "tx_pedagio": r["TX. PEDAGIO"],
        "valor_icms": r["VALOR ICMS"],
        "tx_gris": r["TX. GRIS"],
        "tx_frete_peso": r["TX. FRETE PESO"],
        "tx_outros": r["TX. OUTROS"],
        "tx_nota": r["TX. NOTA"],
        "tipo_emissao": r["TIPO EMISSÃO"],
        "cotacao": r["COTACAO"],
        "data_emissao": _valor_ou_none(r["DATA EMISSAO"]),
        "data_entrega": _valor_ou_none(r["DATA ENTREGA"]),
        "prev_entrega": _valor_ou_none(r["PREV. ENTREGA"]),
        "data_agendamento": _valor_ou_none(r["DATA DE AGENDAMENTO"]),
        "eff_local": r["EFF_LOCAL"],
        "redespacho": r["REDESPACHO"],
        "eff_cidade": r["EFF_CIDADE"],
        "eff_uf": r["EFF_UF"],
        "regiao": r["REGIAO"],
        "lat": r["LAT"],
        "lng": r["LNG"],
        "descricao_ultimo": r["DESCRICAO_ULTIMO"],
    }


def processar_cliente(cliente, df_tudo, pasta_consolidados, mes_abrev):
    """Filtra, dentro da planilha unica (todos os clientes), as linhas
    cujo CLIENTE bate com algum nomes_portal deste cliente; grava os
    dados de frete e as ocorrencias novas no Supabase. Retorna
    (n_linhas, n_ocorrencias_novas), ou None se nao tinha nenhuma linha
    pra esse cliente (nomes_portal desatualizado ou sem movimento no
    periodo)."""
    chaves = {_chave(n) for n in (cliente.get("nomes_portal") or [])}
    if not chaves:
        return None
    df = df_tudo[df_tudo["CLIENTE"].astype(str).str.strip().str.lower().isin(chaves)]
    if df.empty:
        return None

    pasta_consolidados.mkdir(parents=True, exist_ok=True)
    nome_arquivo = "".join(c if c.isalnum() else "_" for c in cliente["nome"])
    df.to_excel(pasta_consolidados / f"{nome_arquivo}_Jan_{mes_abrev}.xlsx", sheet_name="Brudam", index=False)

    rows = ad.build_rows(df)
    log(f"{cliente['nome']}: {len(rows)} linhas (nomes no portal: {', '.join(cliente.get('nomes_portal') or [])}).")

    supabase_db.upsert_fretes([_linha_para_frete(r, cliente["id"]) for r in rows])

    ultimas = supabase_db.ultima_ocorrencia_por_minuta(cliente["id"])
    novas = ad.novas_ocorrencias(rows, ultimas, cliente["id"])
    supabase_db.inserir_ocorrencias(novas)
    log(f"{cliente['nome']}: {len(novas)} ocorrencias novas registradas.")

    return len(rows), len(novas)


def enviar_email(assunto, corpo_html):
    remetente = os.environ.get("EMAIL_USER")
    senha = os.environ.get("EMAIL_PASS")
    if not remetente or not senha:
        log("EMAIL_USER/EMAIL_PASS nao definidos — notificacao por e-mail pulada.")
        return

    msg = EmailMessage()
    msg["Subject"] = assunto
    msg["From"] = formataddr(("Indicador Clientes PortoEx", remetente))
    msg["To"] = EMAIL_DESTINO
    msg.set_content(corpo_html, subtype="html")

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
            smtp.starttls()
            smtp.login(remetente, senha)
            smtp.send_message(msg)
        log(f"E-mail de notificacao enviado para {EMAIL_DESTINO}.")
    except Exception as e:
        log(f"Falha ao enviar e-mail de notificacao: {e}")


def main():
    usuario = os.environ.get("PORTAL_USER")
    senha = os.environ.get("PORTAL_PASS")
    if not usuario or not senha:
        log("Defina as variaveis de ambiente PORTAL_USER e PORTAL_PASS antes de rodar.")
        sys.exit(1)

    hoje = date.today()
    data_ini = date(hoje.year, 1, 1).strftime("%d/%m/%Y")
    data_fim = (hoje - timedelta(days=1)).strftime("%d/%m/%Y")
    log(f"Periodo: {data_ini} ate {data_fim}")

    pasta_tmp = REPO_DIR / "downloads_tmp"
    arquivo = extrair_tudo(usuario, senha, data_ini, data_fim, pasta_tmp)

    df_tudo = pd.read_excel(arquivo, sheet_name="Brudam")
    log(f"Base AZ: {len(df_tudo)} linhas, {df_tudo['CLIENTE'].nunique()} clientes distintos no Brudam.")

    # Segunda base (PEX Logistica), consolidada junto com a AZ. Login proprio
    # (PORTAL_PEX_USER / PORTAL_PEX_PASS): o da AZ nao vale la. Se falhar, segue
    # so com a AZ (dados da PEX ficam como estavam no Supabase) e avisa no e-mail.
    aviso_pex = None
    usuario_pex = os.environ.get("PORTAL_PEX_USER")
    senha_pex = os.environ.get("PORTAL_PEX_PASS")
    if not usuario_pex or not senha_pex:
        aviso_pex = "PORTAL_PEX_USER/PORTAL_PEX_PASS nao definidos -- base PEX Logistica NAO foi extraida."
        log("AVISO: " + aviso_pex)
    else:
        try:
            arquivo_pex = extrair_tudo(usuario_pex, senha_pex, data_ini, data_fim, pasta_tmp, ep.PORTAL_URL_PEX, "todos_pex.xlsx")
            df_pex = pd.read_excel(arquivo_pex, sheet_name="Brudam")
            log(f"Base PEX: {len(df_pex)} linhas, {df_pex['CLIENTE'].nunique()} clientes distintos no Brudam.")
            # numeracao de minuta e separada por base: o prefixo evita colisao
            # (chave unica cliente+minuta) e mostra de onde veio a emissao.
            df_pex["MINUTA"] = PREFIXO_MINUTA_PEX + df_pex["MINUTA"].astype(str)
            df_tudo = pd.concat([df_tudo, df_pex], ignore_index=True)
        except Exception as e:
            aviso_pex = f"Falha ao extrair a base PEX Logistica ({e}) -- rodou so com a AZ."
            log("AVISO: " + aviso_pex)
    log(f"Consolidado: {len(df_tudo)} linhas, {df_tudo['CLIENTE'].nunique()} clientes distintos.")

    log("Buscando clientes cadastrados no Supabase (ativos e pendentes)...")
    clientes = supabase_db.listar_clientes_todos()
    clientes = descobrir_clientes_novos(df_tudo, clientes)

    pasta_consolidados = REPO_DIR / "consolidados"
    mes_abrev = ad.MES_ABREV[hoje.month]
    resumo = []
    for cliente in clientes:
        resultado = processar_cliente(cliente, df_tudo, pasta_consolidados, mes_abrev)
        if resultado:
            resumo.append((cliente["nome"], cliente.get("ativo", False), *resultado))

    agora = datetime.now().strftime("%d/%m/%Y %H:%M")
    itens = "".join(
        f"<li>{nome}{'' if ativo else ' (pendente de revisao)'}: {n_linhas} minutas, {n_oco} ocorrencia(s) nova(s)</li>"
        for nome, ativo, n_linhas, n_oco in resumo
    )
    corpo_html = f"<p>A rotina rodou normalmente em {agora}.</p>"
    if aviso_pex:
        corpo_html += f"<p><b>Atencao:</b> {aviso_pex}</p>"
    corpo_html += f"<ul>{itens}</ul>"
    enviar_email("Indicador Clientes - Atualizado com Sucesso" + (" (sem a base PEX)" if aviso_pex else ""), corpo_html)

    log("\nPipeline concluido.")


def adquirir_lock():
    """Evita duas execucoes reais simultaneas (ex.: Task Scheduler disparando
    de novo com uma anterior ainda rodando) fazendo login duplicado no portal.
    Trava obsoleta (processo anterior que travou/morreu) e destravada sozinha
    apos LOCK_MAX_IDADE_MIN."""
    if LOCK_FILE.exists():
        idade_min = (datetime.now().timestamp() - LOCK_FILE.stat().st_mtime) / 60
        if idade_min < LOCK_MAX_IDADE_MIN:
            log(f"Ja existe uma execucao em andamento (trava com {idade_min:.1f} min) — abortando esta chamada.")
            return False
        log(f"Trava antiga encontrada ({idade_min:.1f} min) — considerando travada, removendo e seguindo.")
    LOCK_FILE.write_text(datetime.now().isoformat(), encoding="utf-8")
    return True


def liberar_lock():
    LOCK_FILE.unlink(missing_ok=True)


if __name__ == "__main__":
    log(f"\n{'='*60}\nInicio do pipeline: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    if not adquirir_lock():
        sys.exit(0)
    try:
        main()
    except Exception:
        import traceback
        log("ERRO NAO TRATADO:\n" + traceback.format_exc())
        raise
    finally:
        liberar_lock()
