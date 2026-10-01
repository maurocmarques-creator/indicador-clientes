#!/usr/bin/env python3
"""
pipeline_atualizar.py — Pipeline completo do Indicador Ansell:

  1. Extrai do portal Brudam os relatorios de Ansell e Hercules (Playwright)
  2. Consolida os dois em uma planilha unica (salva tambem na pasta
     "Analise Ansell" do OneDrive, como no processo manual)
  3. Atualiza index.html com os dados novos
  4. Faz commit + push (so se algo realmente mudou)

Credenciais do portal vem de PORTAL_USER / PORTAL_PASS (variaveis de
ambiente) — nunca ficam no codigo. O envio de e-mail de notificacao usa
EMAIL_USER / EMAIL_PASS (conta Gmail + senha de app — o Office365 da
PortoEx bloqueia autenticacao SMTP por padrao), tambem via variavel de
ambiente. O e-mail sempre vai para EMAIL_DESTINO (PortoEx), so o
remetente e o Gmail.

Uso:
  set PORTAL_USER=seu.usuario
  set PORTAL_PASS=sua.senha
  set EMAIL_USER=seu.email@gmail.com
  set EMAIL_PASS=sua.senha.de.app.do.gmail
  python pipeline_atualizar.py
"""

import json
import os
import smtplib
import subprocess
import sys
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path

import pandas as pd
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

import atualizar_dashboard as ad
import extrair_portal as ep
from config import CONFIG

RELATORIO_NFS = "NFs_Emitida_Ansell"

REPO_DIR = Path(__file__).parent
ONEDRIVE_ANALISE_ANSELL = Path(CONFIG["onedrive_consolidado"])
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
EMAIL_DESTINO = CONFIG["email_destino"]


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


def extrair_arquivos(usuario, senha, data_ini, data_fim, pasta_tmp: Path) -> dict:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()
        page.set_default_timeout(60000)

        try:
            ep.login(page, usuario, senha)

            arquivos = {}
            for cliente in ep.CLIENTES:
                arquivos[cliente] = ep.extrair_cliente(page, cliente, data_ini, data_fim, pasta_tmp)
        except Exception:
            diag_dir = pasta_tmp / "diagnostico"
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
    return arquivos


def _marcar_status_minuta_todas(page):
    """Abre o painel 'Status Minuta', desmarca o padrao (TODAS / EMITIDAS,
    id_0) e marca so 'TODAS' (id_18, ultima caixa da lista)."""
    page.click("#minuta_status")
    page.wait_for_selector("#minuta_status_id_18", state="visible", timeout=10000)
    if page.is_checked("#minuta_status_id_0"):
        page.uncheck("#minuta_status_id_0")
    page.check("#minuta_status_id_18")
    page.click("#minuta_status")  # fecha o painel


def _marcar_status_cte_todas(page):
    """'Status CTe' e um <select> simples (nao checklist) -- escolhe TODAS
    (value=0), localizado pela posicao estrutural ao lado do botao de
    Status Minuta (o campo nao tem id/name proprios)."""
    select = page.locator("#minuta_status").locator(
        "xpath=ancestor::td[1]/following-sibling::td[1]//select"
    )
    select.select_option(value="0")


def _extrair_nfs_cliente(page, cliente, data_ini, data_fim, pasta_saida: Path) -> Path:
    log(f"\n=== Relatorio de Notas Fiscais: {cliente} ===")
    page.goto(ep.RELATORIO_URL)
    page.wait_for_load_state("networkidle")

    cliente_input = ep.get_cliente_input(page)
    cliente_input.fill(cliente)
    ep.set_date_range(page, data_ini, data_fim)

    _marcar_status_cte_todas(page)
    _marcar_status_minuta_todas(page)

    page.get_by_role("button", name="PESQUISAR").click()
    page.wait_for_selector("text=/registros|Selecione um dos relat/i", timeout=30000)

    page.get_by_text("Personalizado Excel", exact=False).click()
    page.wait_for_selector("text=Personalizar Relatório", timeout=15000)
    page.get_by_text("Meus relatórios", exact=False).click()
    page.wait_for_selector("text=Relatórios Personalizados", timeout=15000)
    page.get_by_role("radio", name=RELATORIO_NFS).check()

    pasta_saida.mkdir(parents=True, exist_ok=True)
    destino = pasta_saida / f"nfs_{cliente.lower()}.xlsx"

    with page.expect_download(timeout=180000) as download_info:
        page.get_by_role("button", name="Gerar").click()
        try:
            page.wait_for_selector("text=Escolha o tipo de exportação", timeout=5000)
            page.get_by_role("button", name="XLSX").click()
        except PlaywrightTimeoutError:
            pass
    download_info.value.save_as(destino)
    log(f"Salvo: {destino}")
    return destino


def _fmt_nf_data(v):
    """'NF DATA' normalmente vem como Timestamp do Excel, mas quando a
    celula tinha varias notas (ver _expandir_notas_multiplas) o valor ja
    chega como string 'DD/MM/AAAA' apos o split -- nesse caso o parse
    tem que ser explicitamente dia-primeiro (dayfirst), senao o pandas
    pode interpretar errado (ex.: confundir dia com mes). Normaliza pra
    ISO 'AAAA-MM-DD' (mesmo padrao de data usado no resto do dashboard),
    ou string vazia se nao tiver data."""
    if v is None or v == "" or (isinstance(v, float) and pd.isna(v)):
        return ""
    try:
        if isinstance(v, str):
            return pd.to_datetime(v, dayfirst=True).strftime("%Y-%m-%d")
        return pd.Timestamp(v).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return ""


def _expandir_notas_multiplas(df):
    """Quando NF/DOC tem mais de uma nota na mesma celula (separadas por
    virgula, com NF DATA tambem separada por virgula, uma pra cada NF
    na mesma posicao), quebra em uma linha por nota -- cada uma com seu
    proprio numero e sua propria data de emissao, em vez de uma linha
    so misturando tudo (o que fazia a Data NF nao bater com a nota
    certa e a data ficar em branco por nao dar pra parsear a string com
    virgulas). As demais colunas (minuta, CT-e, status, cliente,
    destino etc.) se repetem em todas as linhas geradas, ja que e a
    mesma minuta/CT-e -- so a NF e a data mudam."""
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


def _separar_historico_nf(df):
    """Quando uma NF tem uma linha 'Coletado' e tambem outra(s) linha(s)
    da mesma NF com status diferente (Cancelada/Pendente) em minutas
    diferentes: a cancelada/pendente e uma minuta que nao vale mais (foi
    cancelada e reemitida depois, entao nao conta) -- tira ela da lista
    principal (nao conta nos KPIs nem aparece solta na tabela) e guarda
    como "historico" dentro da linha 'Coletado' correspondente, pra
    aparecer so quando o operador clicar/expandir aquela linha. NF/DOC
    pode ter varias notas numa celula (separadas por virgula) -- usa a
    primeira como chave de agrupamento.

    Retorna (df_principal, historico_por_posicao, n_no_historico), onde
    historico_por_posicao mapeia a posicao (0-based, apos reset_index)
    da linha 'Coletado' dentro de df_principal para uma lista de Series
    (as linhas antigas/canceladas que ficaram de fora)."""
    df = df.reset_index(drop=True)

    def primeira_nota(cel):
        partes = [n.strip() for n in str(cel).split(",") if n.strip()]
        return partes[0] if partes else None

    chave = df["NF/DOC"].apply(primeira_nota)

    pos_coletado = {}
    for i, (k, coletada) in enumerate(zip(chave, df["Coletada"])):
        if coletada == "Coletado" and k is not None and k not in pos_coletado:
            pos_coletado[k] = i

    historico_por_pai = {}
    indices_historico = set()
    for i, (k, coletada) in enumerate(zip(chave, df["Coletada"])):
        if coletada != "Coletado" and k in pos_coletado:
            historico_por_pai.setdefault(pos_coletado[k], []).append(i)
            indices_historico.add(i)

    df_principal = df.drop(index=list(indices_historico)).reset_index(drop=True)

    mapa_pos_nova = {}
    pos_nova = 0
    for i in range(len(df)):
        if i in indices_historico:
            continue
        mapa_pos_nova[i] = pos_nova
        pos_nova += 1

    historico_por_posicao = {
        mapa_pos_nova[pai_idx]: [df.iloc[fi] for fi in filhos_idx]
        for pai_idx, filhos_idx in historico_por_pai.items()
    }

    return df_principal, historico_por_posicao, len(indices_historico)


def _mapear_coletada(status_cte):
    """Coluna derivada 'Coletada', a partir do STATUS CT-e:
    Autorizado/Criado -> Coletado; Cancelado -> Nao Coletado;
    em branco -> NF Recebida e Nao Coletado."""
    if pd.isna(status_cte) or not str(status_cte).strip():
        return "NF Recebida e Não Coletado"
    s = str(status_cte).strip().lower()
    if s.startswith("autorizado") or s.startswith("criado"):
        return "Coletado"
    if s.startswith("cancelado"):
        return "Não Coletado"
    return status_cte


def extrair_status_nf(usuario, senha, data_ini, data_fim, pasta_tmp: Path):
    """Extrai o relatorio 'NFs_Emitida_Ansell' (Status Minuta/CTe = TODAS)
    pra Ansell e Hercules, numa sessao de navegador propria e separada da
    extracao principal. Passo isolado: qualquer falha aqui e so logada
    (retorna None), nunca derruba o resto do pipeline -- a aba "Status NF"
    do dashboard so fica um pouco desatualizada ate a proxima rodada."""
    log("\n=== Extraindo Status NF (CT-e) ===")
    try:
        arquivos = {}
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(accept_downloads=True)
            page = context.new_page()
            page.set_default_timeout(60000)
            try:
                ep.login(page, usuario, senha)
                for cliente in ep.CLIENTES:
                    arquivos[cliente] = _extrair_nfs_cliente(page, cliente, data_ini, data_fim, pasta_tmp)
            finally:
                browser.close()

        dfs = []
        for cliente, caminho in arquivos.items():
            df = pd.read_excel(caminho)
            df.insert(0, "CLIENTE_ORIGEM", cliente)
            dfs.append(df)
        consolidado = pd.concat(dfs, ignore_index=True).fillna("")
        # Minuta sem NF nenhuma (campo NF/DOC vazio) nao e "NF recebida e
        # nao coletada" -- e so uma minuta sem nota ainda. Nao apresentar.
        antes = len(consolidado)
        consolidado = consolidado[consolidado["NF/DOC"].astype(str).str.strip() != ""]
        log(f"Minutas sem NF removidas: {antes - len(consolidado)} (de {antes}).")
        consolidado["Coletada"] = consolidado["STATUS CT-e"].apply(_mapear_coletada)
        antes_expandir = len(consolidado)
        consolidado = _expandir_notas_multiplas(consolidado)
        if len(consolidado) != antes_expandir:
            log(f"Linhas com varias NFs na mesma celula expandidas: {antes_expandir} -> {len(consolidado)} linhas.")
        consolidado, historico_por_posicao, n_historico = _separar_historico_nf(consolidado)
        log(f"Entradas movidas pro historico (NF cancelada/pendente reemitida em outra minuta, nao conta mais nos KPIs): {n_historico}.")

        # Guarda tambem os xlsx (bruto + consolidado) na pasta do cliente no
        # OneDrive, pro Mauro poder abrir/conferir manualmente quando quiser
        # -- mesmo caminho que ja usavamos quando isso era feito na mao.
        if ONEDRIVE_ANALISE_ANSELL.parent.exists():
            for cliente, caminho in arquivos.items():
                destino = ONEDRIVE_ANALISE_ANSELL / f"nfs_{cliente.lower()}.xlsx"
                pd.read_excel(caminho).to_excel(destino, index=False)
            consolidado.to_excel(ONEDRIVE_ANALISE_ANSELL / "Relatorio_Notas_Fiscais.xlsx", index=False)
            log("Relatorio_Notas_Fiscais.xlsx e arquivos brutos atualizados no OneDrive.")

        def linha_para_dict(r):
            destino = str(r.get("DESTINO", ""))
            local_entrega = str(r.get("LOCAL ENTREGA", ""))
            # Mesma regra do Em Transito/index.html: se o local de entrega e
            # o destinatario forem a mesma empresa (mesma normalizacao --
            # sufixo societario, "DO SUL" a mais etc.), nao e redespacho de
            # verdade, entao fica em branco.
            if local_entrega and ad._normaliza_nome(local_entrega) == ad._normaliza_nome(destino):
                local_entrega = ""
            return {
                "cliente_origem": str(r["CLIENTE_ORIGEM"]),
                "minuta": str(r["MINUTA"]),
                "cte": str(r["CTE"]),
                "status_cte": str(r["STATUS CT-e"]),
                "nf": str(r["NF/DOC"]),
                "nf_data": _fmt_nf_data(r["NF DATA"]),
                # 'DATA EMISSAO' aqui e a data de emissao da MINUTA no
                # Brudam -- na pratica, quando a PortoEx recebeu/registrou
                # o documento, que pode ser bem depois da propria emissao
                # da NF (nf_data) pelo cliente. Mostrado como "Data
                # Recebimento" pro cliente nao confundir com nf_data.
                "data_recebimento": _fmt_nf_data(r.get("DATA EMISSAO", "")),
                "cliente": str(r["CLIENTE"]),
                # Campos do relatorio adicionados depois (destinatario e
                # local de entrega) -- .get com default, pra nao quebrar
                # se o relatorio no portal mudar de novo e essas colunas
                # sumirem/forem renomeadas.
                "destino": destino,
                "cidade_destino": str(r.get("CIDADE DESTINO", "")),
                "uf_destino": str(r.get("UF DESTINO", "")),
                "local_entrega": local_entrega,
                "cidade_entrega": str(r.get("CIDADE ENTREGA", "")),
                "uf_entrega": str(r.get("UF ENTREGA", "")),
                "coletada": str(r["Coletada"]),
                "id_carregamento": ad.ID_CARREGAMENTO_POR_NF.get(str(r["NF/DOC"]), ""),
            }

        nf_status = []
        for pos, (_, r) in enumerate(consolidado.iterrows()):
            item = linha_para_dict(r)
            hist_rows = historico_por_posicao.get(pos)
            if hist_rows:
                item["historico"] = [linha_para_dict(h) for h in hist_rows]
            nf_status.append(item)

        log(f"Status NF extraido ({len(nf_status)} linhas principais, {n_historico} no historico).")

        # nf_pendente.json -- minutas com NF ainda nao coletada (Nao
        # Coletado ou NF Recebida e Nao Coletado), publicada solta no
        # repo pro Mural mostrar tambem (nao so as em transito -- uma
        # minuta ja entregue pode ter NF pendente/cancelada). Escrito
        # aqui direto (nao passa pelo bloco NF_STATUS do index.html),
        # a rotina agendada do Mural le esse arquivo e sincroniza pro
        # banco do Mural.
        nf_pendente = [
            {
                "minuta": item["minuta"],
                "cliente": item["cliente"],
                "cte": item["cte"],
                "nf": item["nf"],
                "status_cte": item["status_cte"],
                "coletada": item["coletada"],
                "data_recebimento": item["data_recebimento"],
            }
            for item in nf_status
            if item["coletada"] != "Coletado"
        ]
        nf_pendente_path = REPO_DIR / "nf_pendente.json"
        nf_pendente_path.write_text(json.dumps(nf_pendente, ensure_ascii=False), encoding="utf-8")
        log(f"nf_pendente.json atualizado ({len(nf_pendente)} minutas com NF nao coletada).")

        return nf_status
    except Exception:
        import traceback
        log("Falha ao extrair Status NF (nao afeta o resto do pipeline):\n" + traceback.format_exc())
        return None


def consolidar(arquivos: dict, destino: Path) -> Path:
    log("\nConsolidando planilhas...")
    dfs = [pd.read_excel(caminho, sheet_name="Brudam") for caminho in arquivos.values()]
    consolidado = pd.concat(dfs, ignore_index=True)
    destino.parent.mkdir(parents=True, exist_ok=True)
    consolidado.to_excel(destino, sheet_name="Brudam", index=False)
    log(f"Consolidado ({len(consolidado)} linhas) salvo em: {destino}")
    return destino


def _sem_timestamp(raw):
    meta = dict(raw.get("meta", {}))
    meta.pop("gerado_em", None)
    return {"meta": meta, "rows": raw.get("rows")}


def atualizar_html(xlsx_consolidado: Path, nf_status=None) -> bool:
    """Atualiza o index.html. O timestamp 'gerado_em' e sempre renovado
    (para refletir a ultima vez que a rotina rodou), mas o retorno indica
    se os dados de frete em si (fora do timestamp) realmente mudaram.
    Se nf_status vier preenchido (extracao de Status NF deu certo nesta
    rodada), tambem regrava o bloco NF_STATUS; se vier None (extracao
    falhou ou foi pulada), deixa o bloco existente como esta."""
    log("\nAtualizando index.html...")
    df = pd.read_excel(xlsx_consolidado, sheet_name="Brudam")
    rows = ad.build_rows(df)
    raw = ad.build_raw(rows)
    log(f"Periodo: {raw['meta']['meses'][0]} a {raw['meta']['meses'][-1]} | {len(rows)} linhas")

    index_path = REPO_DIR / "index.html"
    index_content = index_path.read_text(encoding="utf-8")

    raw_antigo = ad.read_json_blob(index_content, "const RAW = ")
    dados_mudaram = not (raw_antigo and _sem_timestamp(raw_antigo) == _sem_timestamp(raw))
    log("Dados de frete mudaram." if dados_mudaram else "Dados de frete iguais aos ja publicados.")

    raw_json = json.dumps(raw, ensure_ascii=False)
    index_content = ad.replace_json_blob(index_content, "const RAW = ", raw_json)

    # Historico de ocorrencias -- o Brudam so da a ultima (ver
    # atualizar_dashboard.build_ocorrencias_historico), entao acumulamos
    # aqui a cada rodada, tambem guardado solto no repo.
    hist_path = REPO_DIR / "ocorrencias_historico.json"
    historico_anterior = json.loads(hist_path.read_text(encoding="utf-8")) if hist_path.exists() else {}
    historico = ad.build_ocorrencias_historico(rows, historico_anterior)
    hist_path.write_text(json.dumps(historico, ensure_ascii=False), encoding="utf-8")
    index_content = ad.replace_json_blob(index_content, "const OCORRENCIAS_HIST = ", json.dumps(historico, ensure_ascii=False))
    log(f"ocorrencias_historico.json atualizado ({sum(len(v) for v in historico.values())} eventos em {len(historico)} minutas).")

    if nf_status is not None:
        nf_status_json = json.dumps(nf_status, ensure_ascii=False)
        index_content = ad.replace_json_blob(index_content, "const NF_STATUS = ", nf_status_json)
        log(f"Bloco NF_STATUS atualizado ({len(nf_status)} linhas).")
    else:
        log("Bloco NF_STATUS mantido como estava (sem extracao nova nesta rodada).")

    index_path.write_text(index_content, encoding="utf-8")

    log("index.html atualizado.")

    # ocorrencias_problema.json -- minutas que ja tiveram ocorrencia-problema
    # (mesmo que resolvida depois), publicada solta no repo pro Mural
    # mostrar e o time marcar o motivo -- inclui minutas fora de transito.
    ocorrencias_problema = ad.build_ocorrencias_problema(rows, historico)
    ocorrencias_problema_path = REPO_DIR / "ocorrencias_problema.json"
    ocorrencias_problema_path.write_text(json.dumps(ocorrencias_problema, ensure_ascii=False), encoding="utf-8")
    log(f"ocorrencias_problema.json atualizado ({len(ocorrencias_problema)} minutas).")

    # em_transito.json -- lista das minutas ainda em transito, publicada
    # solta no repo pra o Mural buscar ao vivo (fetch direto do GitHub a
    # cada carregamento). Assim, quando uma minuta e entregue e sai
    # dessa lista aqui, ela some do Mural sozinha na proxima vez que
    # alguem abrir, sem precisar eu republicar o Mural na mao.
    em_transito = [
        {
            "minuta": r["MINUTA"],
            "nf": r["NF_DOC"],
            "cliente": r["CLIENTE"],
            "destinatario": r["EFF_LOCAL"],
            "cidade": r["EFF_CIDADE"],
            "uf": r["EFF_UF"],
            "prazo": r["DATA DE AGENDAMENTO"] or r["PREV. ENTREGA"],
            "descricao": r["DESCRICAO_ULTIMO"],
        }
        for r in rows
        if r["STATUS"] in ("EM TRANSITO DENTRO DO PRAZO", "EM TRANSITO FORA DO PRAZO")
    ]
    em_transito_path = REPO_DIR / "em_transito.json"
    em_transito_path.write_text(json.dumps(em_transito, ensure_ascii=False), encoding="utf-8")
    log(f"em_transito.json atualizado ({len(em_transito)} minutas em transito).")

    return dados_mudaram


def limpar_desktop_ini_do_git():
    """O Google Drive (esta pasta e sincronizada) recria arquivos
    desktop.ini dentro de .git/refs/, corrompendo as referencias do
    Git e travando push/fetch silenciosamente. Remove antes de mexer
    no git."""
    git_dir = REPO_DIR / ".git"
    removidos = list(git_dir.rglob("desktop.ini"))
    for p in removidos:
        p.unlink(missing_ok=True)
    if removidos:
        log(f"Removidos {len(removidos)} desktop.ini de dentro do .git (Google Drive).")


def commit_e_push(dados_mudaram: bool):
    limpar_desktop_ini_do_git()
    log("\nVerificando alteracoes no git...")
    arquivos_rastreados = ["index.html", "em_transito.json", "nf_pendente.json", "ocorrencias_historico.json", "ocorrencias_problema.json"]
    status = subprocess.run(
        ["git", "status", "--porcelain"] + arquivos_rastreados,
        cwd=REPO_DIR, capture_output=True, text=True,
    )
    log(f"git status --porcelain {' '.join(arquivos_rastreados)} -> rc={status.returncode} stdout={status.stdout!r} stderr={status.stderr!r}")
    if status.returncode != 0:
        log("git status falhou -- abortando commit desta rodada.")
        return
    if not status.stdout.strip():
        log("Nada para commitar (arquivos rastreados identicos aos publicados).")
        return

    subprocess.run(["git", "add"] + arquivos_rastreados, cwd=REPO_DIR, check=True)
    sufixo = "com dados novos" if dados_mudaram else "sem dados novos, so verificacao"
    mensagem = f"Atualizacao automatica ({sufixo}) — {date.today().isoformat()}"
    subprocess.run(["git", "commit", "-m", mensagem], cwd=REPO_DIR, check=True)
    subprocess.run(["git", "push"], cwd=REPO_DIR, check=True)
    log("Commit e push feitos com sucesso.")


def enviar_email(assunto, corpo_html):
    remetente = os.environ.get("EMAIL_USER")
    senha = os.environ.get("EMAIL_PASS")
    if not remetente or not senha:
        log("EMAIL_USER/EMAIL_PASS nao definidos — notificacao por e-mail pulada.")
        return

    msg = EmailMessage()
    msg["Subject"] = assunto
    msg["From"] = formataddr(("Portoex x Ansell", remetente))
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
    arquivos = extrair_arquivos(usuario, senha, data_ini, data_fim, pasta_tmp)

    mes_abrev = ad.MES_ABREV[hoje.month]
    prefixo = CONFIG.get("prefixo_consolidado", "Base")
    nome_consolidado = f"{prefixo}_Jan_{mes_abrev}.xlsx"
    # No seu PC, guarda o consolidado no OneDrive (como no processo manual).
    # Na nuvem (GitHub Actions) essa pasta nao existe — usa uma pasta local.
    if ONEDRIVE_ANALISE_ANSELL.parent.exists():
        destino_consolidado = ONEDRIVE_ANALISE_ANSELL / nome_consolidado
    else:
        destino_consolidado = REPO_DIR / "downloads_tmp" / nome_consolidado
    consolidado_path = consolidar(arquivos, destino_consolidado)

    nf_status = extrair_status_nf(usuario, senha, data_ini, data_fim, pasta_tmp)

    dados_mudaram = atualizar_html(consolidado_path, nf_status)
    commit_e_push(dados_mudaram)

    link = CONFIG["link_dashboard"]
    agora = datetime.now().strftime("%d/%m/%Y %H:%M")
    situacao = "<b><u>COM ALTERAÇÃO DE DADOS</u></b>" if dados_mudaram else "<b><u>SEM ALTERAÇÃO DE DADOS</u></b>"
    corpo_html = (
        f"<p>A rotina rodou normalmente em {agora}, {situacao}.</p>"
        f"<p>Acesse: <a href='{link}'>{link}</a></p>"
    )
    enviar_email("Indicador Ansell - Atualizado com Sucesso", corpo_html)

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
