#!/usr/bin/env python3
"""
extrair_portal.py — Automatiza a extracao do relatorio 106 (Emissoes) do
portal Brudam (azportoex.brudam.com.br). Extrai TODOS os clientes numa
unica pesquisa (campo "Cliente" em branco) -- cada linha ja vem com a
coluna CLIENTE preenchida, entao o pipeline (pipeline_atualizar.py)
separa por cliente depois, em vez de pedir uma extracao por nome de
portal (isso nao escalaria com centenas de clientes).

Repete, via navegador headless, exatamente o fluxo manual:
  login -> Operacional > Relatorios > 106 Emissoes
  -> Data Emissao (01/01/<ano atual> ate ontem), Cliente em branco -> Pesquisar
  -> Personalizado Excel -> Meus relatorios -> "AUDITORIA TELA 106_ANSELL"
  -> Gerar (isso ja baixa o Excel correto)

Credenciais NUNCA ficam no codigo: vem das variaveis de ambiente
PORTAL_USER e PORTAL_PASS (defina antes de rodar, ou configure como
Secrets do GitHub quando isso for automatizado na nuvem).

Uso (extracao manual de teste):
  set PORTAL_USER=seu.usuario
  set PORTAL_PASS=sua.senha
  python extrair_portal.py <pasta_de_saida>
"""

import os
import sys
from datetime import date, timedelta
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# Duas bases Brudam da PortoEx: a AZ (principal) e a PEX Logistica. O
# pipeline extrai das duas e consolida (ver pipeline_atualizar.py).
PORTAL_URL = "https://azportoex.brudam.com.br/"
PORTAL_URL_PEX = "https://pexlogistica.brudam.com.br/"
CAMINHO_RELATORIO = "opr/relatorio/emissoes"
RELATORIO_URL = PORTAL_URL + CAMINHO_RELATORIO
# Nome do relatorio personalizado salvo em "Meus relatorios" no Brudam --
# define so o layout/colunas do Excel exportado (generico, nao filtrado
# por cliente -- o filtro de cliente e o campo de busca da pagina), entao
# o mesmo template serve pra extrair qualquer cliente.
RELATORIO_PERSONALIZADO = "AUDITORIA TELA 106_ANSELL"


def log(msg):
    print(msg, flush=True)


def login(page, usuario, senha, base_url=PORTAL_URL):
    log(f"Acessando {base_url} ...")
    page.goto(base_url)
    page.get_by_placeholder("Usuário").fill(usuario)
    page.get_by_placeholder("Senha").fill(senha)
    page.get_by_text("Acessar Sistema").click()
    page.wait_for_load_state("networkidle")
    if "inicio.php" not in page.url and "opr" not in page.url:
        # confere que nao ficou na tela de login (credenciais invalidas etc.)
        page.wait_for_timeout(1500)
    # login recusado: o portal devolve a tela de login (index.php?acao=expirada
    # ou a propria raiz com o campo Usuario ainda na tela)
    if page.get_by_placeholder("Usuário").count() > 0:
        raise RuntimeError(f"Login recusado em {base_url} -- confira usuario/senha dessa base.")
    log(f"Login OK, URL atual: {page.url}")


def set_date_range(page, data_ini, data_fim):
    campos = page.locator("input.brd-periodo")
    campos.nth(0).fill(data_ini)
    campos.nth(1).fill(data_fim)
    # fecha qualquer calendario popup que tenha aberto ao focar o campo
    page.keyboard.press("Escape")


def extrair_todos(page, data_ini, data_fim, pasta_saida: Path, base_url=PORTAL_URL, nome_arquivo="todos.xlsx") -> Path:
    """Extrai o relatorio inteiro, sem preencher o filtro 'Cliente' --
    traz todos os clientes do Brudam de uma vez (cada linha com a
    coluna CLIENTE preenchida), em vez de uma extracao por nome de
    portal."""
    log("\n=== Extraindo TODOS os clientes ===")
    page.goto(base_url + CAMINHO_RELATORIO)
    page.wait_for_load_state("networkidle")

    set_date_range(page, data_ini, data_fim)

    log("Clicando em PESQUISAR...")
    page.get_by_role("button", name="PESQUISAR").click()
    page.wait_for_selector("text=/registros|Selecione um dos relat/i", timeout=30000)

    log("Abrindo Personalizado Excel...")
    page.get_by_text("Personalizado Excel", exact=False).click()
    page.wait_for_selector("text=Personalizar Relatório", timeout=15000)

    log("Abrindo Meus relatórios...")
    page.get_by_text("Meus relatórios", exact=False).click()
    page.wait_for_selector("text=Relatórios Personalizados", timeout=15000)

    log(f"Selecionando relatório '{RELATORIO_PERSONALIZADO}'...")
    page.get_by_role("radio", name=RELATORIO_PERSONALIZADO).check()

    pasta_saida.mkdir(parents=True, exist_ok=True)
    destino = pasta_saida / nome_arquivo

    log("Clicando em Gerar (isso já gera o Excel correto)...")
    with page.expect_download(timeout=180000) as download_info:
        page.get_by_role("button", name="Gerar").click()
        # Em alguns casos aparece uma caixa extra perguntando CSV/XLSX —
        # se aparecer, confirma XLSX; se o download ja comecou sozinho,
        # esse bloco so encerra no timeout curto sem atrapalhar.
        try:
            page.wait_for_selector("text=Escolha o tipo de exportação", timeout=5000)
            page.get_by_role("button", name="XLSX").click()
        except PlaywrightTimeoutError:
            pass
    download = download_info.value
    download.save_as(destino)
    log(f"Salvo: {destino}")
    return destino


# Relatorio personalizado (Meus relatorios) com as colunas de NF/CT-e usadas
# pelas abas Status Nota Fiscal -- mesmo nome nas duas bases.
RELATORIO_NFS = "NFs_Emitida_Ansell"


def _marcar_status_minuta_todas(page):
    """Abre o painel 'Status Minuta', desmarca o padrao (TODAS / EMITIDAS,
    id_0) e marca so 'TODAS'. O id da caixa 'TODAS' muda de uma base pra
    outra (id_18 na AZ, id_16 na PEX), entao acha pelo texto do rotulo."""
    page.click("#minuta_status")
    page.wait_for_selector("#minuta_status_id_1", state="visible", timeout=10000)
    id_todas = page.evaluate("""() => {
        const i = [...document.querySelectorAll('input[id^=minuta_status_id_]')]
          .find(x => (x.closest('label') || x.parentElement).innerText.trim().toUpperCase() === 'TODAS');
        return i ? i.id : null;
    }""")
    if not id_todas:
        raise RuntimeError("Caixa 'TODAS' do Status Minuta nao encontrada.")
    if page.is_checked("#minuta_status_id_0"):
        page.uncheck("#minuta_status_id_0")
    page.check("#" + id_todas)
    page.click("#minuta_status")  # fecha o painel


def _marcar_status_cte_todas(page):
    """'Status CTe' e um <select> simples -- escolhe TODAS (value=0),
    localizado pela posicao ao lado do botao de Status Minuta."""
    select = page.locator("#minuta_status").locator(
        "xpath=ancestor::td[1]/following-sibling::td[1]//select"
    )
    select.select_option(value="0")


def extrair_nfs_todos(page, data_ini, data_fim, pasta_saida: Path, base_url=PORTAL_URL, nome_arquivo="nfs_todos.xlsx") -> Path:
    """Relatorio de Notas Fiscais de TODOS os clientes (campo Cliente em
    branco), Status Minuta/CT-e = TODAS -- mesmo fluxo do indicador-ansell,
    mas sem filtrar por cliente."""
    log("=== Extraindo Notas Fiscais de TODOS os clientes ===")
    page.goto(base_url + CAMINHO_RELATORIO)
    page.wait_for_load_state("networkidle")

    set_date_range(page, data_ini, data_fim)
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
    destino = pasta_saida / nome_arquivo
    with page.expect_download(timeout=300000) as download_info:
        page.get_by_role("button", name="Gerar").click()
        try:
            page.wait_for_selector("text=Escolha o tipo de exportação", timeout=5000)
            page.get_by_role("button", name="XLSX").click()
        except PlaywrightTimeoutError:
            pass
    download_info.value.save_as(destino)
    log(f"Salvo: {destino}")
    return destino


def main():
    usuario = os.environ.get("PORTAL_USER")
    senha = os.environ.get("PORTAL_PASS")
    if not usuario or not senha:
        log("Defina as variaveis de ambiente PORTAL_USER e PORTAL_PASS antes de rodar.")
        sys.exit(1)

    pasta_saida = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "downloads_tmp"

    hoje = date.today()
    data_ini = date(hoje.year, 1, 1).strftime("%d/%m/%Y")
    data_fim = (hoje - timedelta(days=1)).strftime("%d/%m/%Y")
    log(f"Periodo: {data_ini} ate {data_fim}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()
        page.set_default_timeout(60000)

        login(page, usuario, senha)
        destino = extrair_todos(page, data_ini, data_fim, pasta_saida)

        browser.close()

    log(f"\nExtração concluída: {destino}")


if __name__ == "__main__":
    main()
