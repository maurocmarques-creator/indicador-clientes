#!/usr/bin/env python3
"""
atualizar_dashboard.py — Atualiza index.html do Indicador Ansell a partir de
uma planilha consolidada (Ansell + Hercules) exportada do relatorio 106
(Emissoes) do sistema Brudam.

Uso: python atualizar_dashboard.py <planilha.xlsx> [pasta_do_dashboard]
Padrao pasta_do_dashboard: diretorio deste script.
"""

import re
import sys
import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from config import CONFIG

MES_ABREV = {1: 'Jan', 2: 'Fev', 3: 'Mar', 4: 'Abr', 5: 'Mai', 6: 'Jun',
             7: 'Jul', 8: 'Ago', 9: 'Set', 10: 'Out', 11: 'Nov', 12: 'Dez'}

# Excecoes manuais de STATUS por MINUTA, para casos onde o sistema
# classifica errado (ex: TIPO EMISSAO = DEVOLUCAO mas a carga foi
# entregue normalmente). Fica em cliente_config.json para persistir a
# cada atualizacao.
STATUS_OVERRIDES = CONFIG.get("status_overrides", {})

# Correcoes manuais de datas por MINUTA, para erros de digitacao no
# portal (ex: agendamento cadastrado com o ano errado). Fica em
# cliente_config.json para persistir a cada atualizacao.
DATE_OVERRIDES = CONFIG.get("date_overrides", {})

# Mural de observacoes por MINUTA, mostrado na aba Em Transito logo
# abaixo da descricao da ultima ocorrencia -- uma "conversa" (lista de
# mensagens, mais recente por ultimo) que o time PortoEx escreve na
# ferramenta interna (Artifact com banco compartilhado) e que este
# pipeline sincroniza para dentro de cliente_config.json, para ficar
# visivel (somente leitura) para quem abrir o dashboard publico,
# inclusive o cliente. Formato por minuta:
#   [{"autor": "Nome", "texto": "...", "data": "17/09/2026 14:30"}, ...]
OBSERVACOES_TRANSITO = CONFIG.get("observacoes_transito", {})

# Motivo da ocorrencia (ex.: "Pedido Divergente", "Nota Fiscal em
# Desacordo-Preco Incorreto"), marcado manualmente pelo time PortoEx no
# Mural -- um motivo por MINUTA (nao por evento/volume), cobrindo a
# ocorrencia-problema mais recente dela. Mesmo mecanismo de sincronizacao
# que OBSERVACOES_TRANSITO (Mural -> cliente_config.json -> aqui).
# Formato por minuta: {"motivo": "Pedido Divergente", "definido_em": "..."}
MOTIVOS_OCORRENCIA = CONFIG.get("motivos_ocorrencia", {})

# ID de Carregamento, vinculado manualmente por NF (nao por minuta) no
# Mural ao importar a "Ordem de Coleta" do dia -- mesmo mecanismo de
# sincronizacao que MOTIVOS_OCORRENCIA. Chave = numero da NF (string).
ID_CARREGAMENTO_POR_NF = CONFIG.get("id_carregamento", {})


def _id_carregamento_da_linha(nf_doc):
    """Uma minuta pode ter mais de uma NF na mesma celula (separadas por
    virgula) -- usa o ID de Carregamento da primeira NF que bater no
    mapa (na pratica todas as NFs de uma minuta viajam no mesmo
    carregamento, entao nao deveria haver conflito real)."""
    for nf in str(nf_doc or '').split(','):
        nf = nf.strip()
        if nf in ID_CARREGAMENTO_POR_NF:
            return ID_CARREGAMENTO_POR_NF[nf]
    return ''

UF_REGIAO = {
    'AC': 'Norte', 'AP': 'Norte', 'AM': 'Norte', 'PA': 'Norte', 'RO': 'Norte', 'RR': 'Norte', 'TO': 'Norte',
    'AL': 'Nordeste', 'BA': 'Nordeste', 'CE': 'Nordeste', 'MA': 'Nordeste', 'PB': 'Nordeste',
    'PE': 'Nordeste', 'PI': 'Nordeste', 'RN': 'Nordeste', 'SE': 'Nordeste',
    'DF': 'Centro-Oeste', 'GO': 'Centro-Oeste', 'MT': 'Centro-Oeste', 'MS': 'Centro-Oeste',
    'ES': 'Sudeste', 'MG': 'Sudeste', 'RJ': 'Sudeste', 'SP': 'Sudeste',
    'PR': 'Sul', 'RS': 'Sul', 'SC': 'Sul',
}

# Centroides aproximados por UF (uso apenas decorativo no mapa do dashboard).
UF_CENTROID = {
    'AC': (-9.02, -70.81), 'AL': (-9.57, -36.78), 'AM': (-3.47, -65.10),
    'AP': (0.90, -52.00), 'BA': (-12.96, -41.70), 'CE': (-5.50, -39.32),
    'DF': (-15.78, -47.93), 'ES': (-19.19, -40.34), 'GO': (-15.83, -49.83),
    'MA': (-5.42, -45.44), 'MG': (-18.51, -44.55), 'MS': (-20.77, -54.79),
    'MT': (-12.64, -55.42), 'PA': (-3.42, -52.29), 'PB': (-7.06, -36.72),
    'PE': (-8.38, -37.86), 'PI': (-7.72, -42.73), 'PR': (-24.89, -51.55),
    'RJ': (-22.25, -42.66), 'RN': (-5.40, -36.95), 'RO': (-10.83, -63.34),
    'RR': (1.99, -61.33), 'RS': (-30.17, -53.50), 'SC': (-27.45, -50.95),
    'SE': (-10.57, -37.45), 'SP': (-22.25, -48.63), 'TO': (-10.25, -48.25),
}

# Coordenadas aproximadas por cidade (chave "CIDADE|UF", mesmo texto de
# EFF_CIDADE/EFF_UF), usadas no mapa em vez do centroide do estado quando
# disponivel -- sem isso, todas as cidades de um mesmo estado caiam
# exatamente no mesmo ponto (visivel principalmente com o zoom por
# estado). Uso apenas decorativo (mesma ressalva do UF_CENTROID); cidade
# que nao estiver aqui cai de volta no centroide do estado. Cobre as
# cidades que ja apareceram nos dados -- uma cidade nova, ate ser
# adicionada aqui, some pro centro do estado (nao quebra nada).
CITY_COORD = {
    'GUARULHOS|SP': (-23.4538, -46.5333), 'SERRA|ES': (-20.1289, -40.3078),
    'GARUVA|SC': (-26.0292, -48.8564), 'SAO JOSE DOS PINHAIS|PR': (-25.5347, -49.2058),
    'ITAJUBA|MG': (-22.4256, -45.4528), 'CAXIAS DO SUL|RS': (-29.1678, -51.1794),
    'ARACARIGUAMA|SP': (-23.4325, -47.0611), 'CAMPINAS|SP': (-22.9099, -47.0626),
    'GOIANIA|GO': (-16.6869, -49.2648), 'SOROCABA|SP': (-23.5015, -47.4526),
    'SAO PAULO|SP': (-23.5505, -46.6333), 'CONTAGEM|MG': (-19.9317, -44.0536),
    'CASCAVEL|PR': (-24.9555, -53.4552), 'SANTO ANDRE|SP': (-23.6639, -46.5383),
    'SAO JOSE|SC': (-27.5964, -48.6262), 'ATIBAIA|SP': (-23.1170, -46.5503),
    'INDAIAL|SC': (-26.8983, -49.2308), 'SAO BENTO DO SUL|SC': (-26.2503, -49.3789),
    'LAURO DE FREITAS|BA': (-12.8944, -38.3247), 'JOINVILLE|SC': (-26.3045, -48.8487),
    'CRICIUMA|SC': (-28.6775, -49.3697), 'PARAUAPEBAS|PA': (-6.0675, -49.9022),
    'MARINGA|PR': (-23.4205, -51.9331), 'JABOATAO DOS GUARARAPES|PE': (-8.1130, -35.0150),
    'SAO BERNARDO DO CAMPO|SP': (-23.6944, -46.5654), 'PELOTAS|RS': (-31.7654, -52.3376),
    'PATO BRANCO|PR': (-26.2288, -52.6706), 'RIO DE JANEIRO|RJ': (-22.9068, -43.1729),
    'SAO LUIZ|MA': (-2.5307, -44.3068), 'GRAVATAI|RS': (-29.9442, -50.9925),
    'BARUERI|SP': (-23.5104, -46.8761), 'PONTE NOVA|MG': (-20.4092, -42.9036),
    'GUARAMIRIM|SC': (-26.4783, -49.0294), 'SAO GABRIEL DO OESTE|MS': (-19.3953, -54.5578),
    'JUNDIAI|SP': (-23.1864, -46.8842), 'PIRACICABA|SP': (-22.7253, -47.6492),
    'CURITIBA|PR': (-25.4284, -49.2733), 'MANAUS|AM': (-3.1190, -60.0217),
    'LIMEIRA|SP': (-22.5646, -47.4017), 'DIAS D AVILA|BA': (-12.6047, -38.2986),
    'CAUCAIA|CE': (-3.7361, -38.6531), 'OLIVEIRA|MG': (-20.6975, -44.8283),
    'MACAE|RJ': (-22.3708, -41.7869), 'EMBU|SP': (-23.6489, -46.8519),
    'CHAPECO|SC': (-27.1004, -52.6152), 'CAMACARI|BA': (-12.6975, -38.3242),
    'COTIA|SP': (-23.6019, -46.9188), 'PROMISSAO|SP': (-21.5361, -49.8603),
    'BELO HORIZONTE|MG': (-19.9167, -43.9345), 'UBERLANDIA|MG': (-18.9186, -48.2772),
    'MATELANDIA|PR': (-25.1611, -53.9622), 'NANUQUE|MG': (-17.8394, -40.3536),
    'BATAGUASSU|MS': (-21.7156, -52.4239), 'NOVO HAMBURGO|RS': (-29.6783, -51.1306),
    'ANAPOLIS|GO': (-16.3267, -48.9528), 'BETIM|MG': (-19.9678, -44.1983),
    'TATUI|SP': (-23.3556, -47.8492), 'COLATINA|ES': (-19.5386, -40.6306),
    'ITAUNA|MG': (-20.0736, -44.5764), 'ANANINDEUA|PA': (-1.3656, -48.3722),
    'ERECHIM|RS': (-27.6342, -52.2739), 'ITATIBA|SP': (-23.0064, -46.8386),
    'SAO SEBASTIAO DO OESTE|MG': (-20.2764, -45.1194), 'VARZEA GRANDE|MT': (-15.6467, -56.1325),
    'LINS|SP': (-21.6789, -49.7425), 'JOAO MONLEVADE|MG': (-19.8083, -43.1731),
    'JUIZ DE FORA|MG': (-21.7642, -43.3503), 'CABO DE SANTO AGOSTINHO|PE': (-8.2892, -35.0353),
    'TAPEJARA|RS': (-28.0678, -52.0086), 'MARECHAL CANDIDO RONDON|PR': (-24.5581, -54.0567),
    'LAGOA DA PRATA|MG': (-20.0225, -45.5478), 'BELEM|PA': (-1.4558, -48.4902),
    'CASTRO|PR': (-24.7911, -50.0119), 'CAMPO MOURAO|PR': (-24.0463, -52.3776),
    'SANTA HELENA|PR': (-24.8583, -54.3339), 'ITAIPULANDIA|PR': (-25.1197, -54.3392),
    'MEDIANEIRA|PR': (-25.2975, -54.0931), 'RIO CLARO|SP': (-22.4114, -47.5614),
    'ITAPEVI|SP': (-23.5489, -46.8494), 'MARAVILHA|SC': (-26.7681, -53.1697),
    'ENCANTADO|RS': (-29.2350, -51.8692), 'SAO MIGUEL DO IGUACU|PR': (-25.3583, -54.2394),
    'FORTALEZA|CE': (-3.7319, -38.5267), 'SARANDI|RS': (-27.9436, -52.9247),
    'JOACABA|SC': (-27.1758, -51.5050), 'INDAIATUBA|SP': (-23.0917, -47.2181),
    'SAO JOSE DO RIO PRETO|SP': (-20.8113, -49.3758), 'ANAURILANDIA|MS': (-22.1839, -52.7208),
    'PAULINIA|SP': (-22.7614, -47.1544), 'ABELARDO LUZ|SC': (-26.5639, -52.3269),
    'SERTAOZINHO|SP': (-21.1378, -48.0431), 'ITAPAGIPE|MG': (-19.8964, -49.5988),
    'CANOAS|RS': (-29.9177, -51.1836), 'TRES LAGOAS|MS': (-20.7849, -51.7005),
    'EXTREMA|MG': (-22.8547, -46.3197), 'TRES CORACOES|MG': (-21.6989, -45.2536),
    'PASSO FUNDO|RS': (-28.2636, -52.4064), 'TAUBATE|SP': (-23.0264, -45.5553),
    'RESENDE|RJ': (-22.4658, -44.4467), 'TREZE TILIAS|SC': (-26.9600, -51.4106),
    'IPOJUCA|PE': (-8.4013, -35.0631), 'SANTA TEREZINHA DE ITAIPU|PR': (-25.4692, -54.4022),
    'VILA VELHA|ES': (-20.3297, -40.2925), 'PORTO ALEGRE|RS': (-30.0346, -51.2177),
    'DUQUE DE CAXIAS|RJ': (-22.7858, -43.3117), 'LINHARES|ES': (-19.3944, -40.0717),
    'CARAGUATATUBA|SP': (-23.6206, -45.4131), 'TEIXEIRA DE FREITAS|BA': (-17.5406, -39.7422),
    'MANDAGUARI|PR': (-23.5433, -51.6717), 'CATALAO|GO': (-18.1658, -47.9464),
    'VIANA|ES': (-20.3908, -40.4967), 'QUILOMBO|SC': (-26.7247, -52.7328),
    'MIRASSOL D OESTE|MT': (-15.6756, -58.0908), 'BRUSQUE|SC': (-27.0981, -48.9106),
    'MACEIO|AL': (-9.6658, -35.7353), 'OSASCO|SP': (-23.5325, -46.7917),
    'CUBATAO|SP': (-23.8950, -46.4247), 'SAO JOSE DOS CAMPOS|SP': (-23.2237, -45.9009),
    'POMERODE|SC': (-26.7378, -49.1758),
    # Adicionadas quando "Destinatario" passou a ser sempre o cliente final
    # (DESTINO), nao mais o local de entrega/redespacho -- surgiram
    # cidades novas no mapa que antes nao apareciam.
    'ALHANDRA|PB': (-7.4197, -34.9142), 'ALUMINIO|SP': (-23.5306, -47.2617),
    'ARACAJU|SE': (-10.9472, -37.0731), 'ARAUCARIA|PR': (-25.5883, -49.4106),
    'CASTANHAL|PA': (-1.2938, -47.9257), 'JACAREI|SP': (-23.3053, -45.9658),
    'JANAUBA|MG': (-15.8019, -43.3117), 'MATOZINHOS|MG': (-19.5514, -44.0294),
    'MOSSORO|RN': (-5.1875, -37.3441), 'PORTO REAL|RJ': (-22.4192, -44.2831),
    'RONDONOPOLIS|MT': (-16.4706, -54.6356), 'TANGARA DA SERRA|MT': (-14.6228, -57.4931),
}


def iso(d):
    if pd.isna(d):
        return ''
    return d.strftime('%Y-%m-%d')


def _primeiro_preenchido(*valores):
    """Primeiro valor nao vazio/nao NaN da lista (trata tanto celula vazia
    do Excel quanto string em branco, ja que o pandas pode retornar as
    duas coisas dependendo da planilha). Se nenhum estiver preenchido,
    retorna string vazia."""
    for v in valores:
        if not pd.isna(v) and str(v).strip():
            return v
    return ''


# Mesma lista/logica de normalizacao de nome usada no index.html (funcao
# JS _normalizaDest, aba Resumo Destinatario) -- mantida em espelho aqui
# porque o Python nao pode chamar o JS. Se adicionar um prefixo confirmado
# num lado, adicionar no outro tambem.
CONSOLIDACAO_PREFIXOS_CONFIRMADOS = [
    'NORTEL', 'ATIVA', 'BALASKA', 'BUNZL', 'CORSUL', 'DIMENSIONAL',
    'ELETRONOR', 'EXATA', 'FASTENAL', 'FEMABRA', 'FRISA', 'IR NEUTZLING',
    'ITURRI', 'KROMBERG', 'PETROLEO BRASILEIRO', 'RSG', 'WILSON SONS',
]


def _normaliza_nome(nome):
    """Normaliza um nome de destinatario pra comparacao: maiusculas, remove
    pontuacao e sufixo societario (LTDA, SA, EPP, ME, EIRELI, MEI) do
    final, e reduz a um prefixo confirmado manualmente quando aplicavel
    (ex.: "CORSUL COMERCIO E REPRESENTACOES DO SUL LTDA" e "CORSUL
    COMERCIO E REPRESENTACOES" viram ambos "CORSUL")."""
    n = re.sub(r'\s+', ' ', str(nome or '').upper()).strip()
    n = re.sub(r'\bS/A\b', 'SA', n)
    n = re.sub(r'\bS\.A\.?\b', 'SA', n)
    n = re.sub(r'\bS\s+A\b', 'SA', n)
    n = re.sub(r'[.\-]', ' ', n)
    n = re.sub(r'\s+', ' ', n).strip()
    sufixo_re = re.compile(r'\s(LTDA|SA|EPP|ME|EIRELI|MEI)$')
    while True:
        nova = sufixo_re.sub('', n).strip()
        if nova == n:
            break
        n = nova
    for prefixo in CONSOLIDACAO_PREFIXOS_CONFIRMADOS:
        if n == prefixo or n.startswith(prefixo + ' '):
            return prefixo
    return n


def compute_status(tipo_emissao, data_entrega, prev_entrega, data_agendamento, hoje, descricao_ultimo=''):
    if tipo_emissao == 'DEVOLUCAO':
        return 'DEVOLUCAO'
    if tipo_emissao == 'REENTREGA':
        return 'REENTREGA'
    efetivo = data_agendamento if not pd.isna(data_agendamento) else prev_entrega

    # A "DATA ENTREGA" as vezes fica em branco mesmo com a entrega ja
    # confirmada na descricao da ultima ocorrencia — nesses casos nao e
    # "Em Transito" de verdade, e sim uma entrega sem a data batida no
    # sistema. Usamos hoje como data de referencia (nao temos a data real).
    descricao_ultimo = (descricao_ultimo or '')
    entregue_sem_data = pd.isna(data_entrega) and 'ENTREGA REALIZADA NORMALMENTE' in descricao_ultimo.upper()
    data_ref = hoje if entregue_sem_data else data_entrega

    if pd.isna(data_ref):
        # Sem baixa e sem confirmacao de entrega: compara hoje contra o
        # prazo (agendamento, se tiver; senao a propria previsao de entrega).
        if not pd.isna(efetivo) and hoje > efetivo:
            return 'EM TRANSITO FORA DO PRAZO'
        return 'EM TRANSITO DENTRO DO PRAZO'
    if pd.isna(efetivo):
        return 'EM ATRASO'
    return 'NO PRAZO' if data_ref <= efetivo else 'EM ATRASO'


def find_tipo_emissao_col(df):
    # O cabeçalho "TIPO EMISSÃO" costuma vir com o "Ã" corrompido no Excel
    # exportado pelo portal (caractere de substituição real, não só exibição).
    candidates = [c for c in df.columns if c.startswith('TIPO EMISS')]
    if not candidates:
        raise ValueError('Coluna "TIPO EMISSAO" nao encontrada na planilha')
    return candidates[0]


def prazo_efetivo(prev_entrega, data_agendamento, data_emissao):
    """Data que rege as metricas de PERFORMANCE (por oposicao as de
    faturamento, que usam DATA EMISSAO): se tiver agendamento, usa o
    agendamento; senao usa a previsao de entrega; se nenhum dos dois
    existir (raro), cai de volta pra emissao para a linha nao sumir dos
    filtros de mes."""
    if not pd.isna(data_agendamento):
        return data_agendamento
    if not pd.isna(prev_entrega):
        return prev_entrega
    return data_emissao


def build_rows(df, hoje=None):
    hoje = pd.Timestamp(hoje) if hoje is not None else pd.Timestamp.now().normalize()
    tipo_col = find_tipo_emissao_col(df)
    rows = []
    for _, r in df.iterrows():
        minuta = str(r['MINUTA'])
        data_emissao = r['DATA EMISSAO']
        data_entrega = r['DATA ENTREGA']
        prev_entrega = r['PREV. ENTREGA']
        data_agendamento = r['DATA DE AGENDAMENTO']

        # Corrige erros de digitacao de data cadastrados no portal (ex:
        # ano errado), antes de qualquer calculo usar essas datas.
        date_over = DATE_OVERRIDES.get(minuta, {})
        if 'DATA DE AGENDAMENTO' in date_over:
            data_agendamento = pd.Timestamp(date_over['DATA DE AGENDAMENTO'])
        if 'PREV. ENTREGA' in date_over:
            prev_entrega = pd.Timestamp(date_over['PREV. ENTREGA'])

        tipo = r[tipo_col]
        # "Destinatario" no dashboard e sempre o cliente final (DESTINO/
        # CIDADE DESTINO/UF DESTINO -- nunca vem em branco no Brudam), nao
        # mais o local fisico de entrega (LOCAL ENTREGA), que as vezes e um
        # parceiro de redespacho/cross-dock (ex.: "EXATA CARGO" em
        # Guarulhos) diferente do cliente real, ate em outra cidade/UF.
        # Pedido do cliente: LOCAL ENTREGA vira uma coluna separada
        # "Redespacho" (so o nome), mostrada apenas quando preenchida.
        eff_local = _primeiro_preenchido(r.get('DESTINO', ''), r['LOCAL ENTREGA'])
        eff_cidade = _primeiro_preenchido(r.get('CIDADE DESTINO', ''), r['CIDADE ENTREGA'])
        eff_uf = _primeiro_preenchido(r.get('UF DESTINO', ''), r['UF ENTREGA'])
        redespacho = _primeiro_preenchido(r['LOCAL ENTREGA'], '')
        # Se o local de entrega e o destinatario sao a mesma empresa, nao
        # e redespacho de verdade -- so o mesmo nome escrito diferente
        # (sufixo societario, "DO SUL" a mais etc.). Nesse caso o valido
        # e o destinatario, entao deixa em branco. Usa a mesma
        # normalizacao (com sufixo + prefixos confirmados) da consolidacao
        # do Resumo Destinatario, senao comparacoes como "CORSUL COMERCIO
        # E REPRESENTACOES DO SUL LTDA" x "CORSUL COMERCIO E
        # REPRESENTACOES" nao batem no texto puro.
        if redespacho and _normaliza_nome(redespacho) == _normaliza_nome(eff_local):
            redespacho = ''
        coord = CITY_COORD.get(f"{eff_cidade}|{eff_uf}") or UF_CENTROID.get(eff_uf)
        descricao_ultimo = r.get('DESCRICAO ULTIMO', '')
        descricao_ultimo = '' if pd.isna(descricao_ultimo) else descricao_ultimo
        status = STATUS_OVERRIDES.get(
            minuta, compute_status(tipo, data_entrega, prev_entrega, data_agendamento, hoje, descricao_ultimo)
        )
        prazo_perf = prazo_efetivo(prev_entrega, data_agendamento, data_emissao)

        rows.append({
            'MES': data_emissao.strftime('%Y-%m'),
            'MES_NOME': f"{MES_ABREV[data_emissao.month]}/{data_emissao.year}",
            'MES_PREV': prazo_perf.strftime('%Y-%m'),
            'MES_PREV_NOME': f"{MES_ABREV[prazo_perf.month]}/{prazo_perf.year}",
            'STATUS': status,
            'CLIENTE': r['CLIENTE'],
            'MINUTA': minuta,
            'NF_DOC': str(r['NF/DOC']),
            'VOLUMES': int(r['VOLUMES']) if not pd.isna(r['VOLUMES']) else 0,
            'FRETE TOTAL': float(r['FRETE TOTAL']) if not pd.isna(r['FRETE TOTAL']) else 0.0,
            'NF VALOR': float(r['NF VALOR']) if not pd.isna(r['NF VALOR']) else 0.0,
            'PESO': float(r['PESO CALC']) if not pd.isna(r['PESO CALC']) else 0.0,
            'TX. PEDAGIO': float(r['TX. PEDAGIO']) if not pd.isna(r['TX. PEDAGIO']) else 0.0,
            'VALOR ICMS': float(r['VALOR ICMS']) if not pd.isna(r['VALOR ICMS']) else 0.0,
            'TX. GRIS': float(r['TX. GRIS']) if not pd.isna(r['TX. GRIS']) else 0.0,
            'TX. FRETE PESO': float(r['TX. FRETE PESO']) if not pd.isna(r['TX. FRETE PESO']) else 0.0,
            'TX. OUTROS': float(r['TX. OUTROS']) if not pd.isna(r['TX. OUTROS']) else 0.0,
            'TX. NOTA': float(r['TX. NOTA']) if not pd.isna(r['TX. NOTA']) else 0.0,
            'TIPO EMISSÃO': tipo,
            # COTACAO no export bruto e um numero de cotacao (quando negociado
            # fora da tabela) ou vazio — o filtro Sim/Nao do dashboard espera
            # 'S'/'N', entao convertemos presenca/ausencia de valor.
            'COTACAO': 'S' if not pd.isna(r['COTACAO']) else 'N',
            'DATA EMISSAO': iso(data_emissao),
            'DATA ENTREGA': iso(data_entrega),
            'PREV. ENTREGA': iso(prev_entrega),
            'DATA DE AGENDAMENTO': iso(data_agendamento),
            'EFF_LOCAL': eff_local,
            'REDESPACHO': redespacho,
            'EFF_CIDADE': eff_cidade,
            'DESCRICAO_ULTIMO': descricao_ultimo,
            'OBSERVACOES': OBSERVACOES_TRANSITO.get(minuta, []),
            'MOTIVO_OCORRENCIA': MOTIVOS_OCORRENCIA.get(minuta, {}).get('motivo', ''),
            'ID_CARREGAMENTO': _id_carregamento_da_linha(r['NF/DOC']),
            'EFF_UF': eff_uf,
            'REGIAO': UF_REGIAO.get(eff_uf, ''),
            'LAT': coord[0] if coord else None,
            'LNG': coord[1] if coord else None,
        })
    return rows


# Espelho do CODIGOS_OCORRENCIA_PROBLEMA em index.html (funcao JS
# isOcorrenciaProblema, aba Ocorrencias) -- mantido em sincronia manual
# porque o Python nao pode chamar o JS. Se adicionar/remover um codigo
# num lado, adicionar no outro tambem.
CODIGOS_OCORRENCIA_PROBLEMA = {'135', '713', '23', '667', '170', '10060', '26', '2'}


def _e_ocorrencia_problema(descricao):
    codigo = str(descricao or '').split(' - ')[0].strip()
    return codigo in CODIGOS_OCORRENCIA_PROBLEMA


def _ultima_ocorrencia_problema(historico_minuta):
    """Ultimo evento de ocorrencia-problema (ignora marcos de rotina) no
    historico de uma minuta, ou None se ela nunca teve nenhum."""
    for evento in reversed(historico_minuta):
        if _e_ocorrencia_problema(evento['descricao']):
            return evento
    return None


def build_ocorrencias_problema(rows, historico):
    """Lista (achatada, uma linha por minuta) das minutas que ja tiveram
    alguma ocorrencia-problema (mesmo que resolvida/substituida depois),
    para o Mural mostrar e o time marcar o motivo -- inclui minutas que
    ja sairam de 'Em Transito', ao contrario de em_transito.json."""
    resultado = []
    for r in rows:
        ultimo = _ultima_ocorrencia_problema(historico.get(r['MINUTA'], []))
        if not ultimo:
            continue
        resultado.append({
            'minuta': r['MINUTA'],
            'nf': r['NF_DOC'],
            'cliente': r['CLIENTE'],
            'destinatario': r['EFF_LOCAL'],
            'cidade': r['EFF_CIDADE'],
            'uf': r['EFF_UF'],
            'redespacho': r['REDESPACHO'],
            'descricao': ultimo['descricao'],
            'detectado_em': ultimo['detectado_em'],
        })
    return resultado


def build_ocorrencias_historico(rows, historico_anterior):
    """O Brudam so entrega a ultima ocorrencia de cada minuta
    (DESCRICAO_ULTIMO, sobrescrita a cada rodada) -- sem historico
    proprio na fonte. Essa funcao constroi o historico do lado da
    PortoEx: compara a ocorrencia atual de cada minuta com a ultima
    conhecida (guardada em historico_anterior) e so acrescenta um
    registro novo quando ela mudou (ou e a primeira vez que a minuta
    aparece com uma ocorrencia nao vazia) -- assim nao perde o registro
    quando o Brudam atualizar/substituir a ocorrencia. Formato:
    {"<MINUTA>": [{"descricao": "135 - MATERIAL RECUSADO PELO CLIENTE",
    "detectado_em": "30/09/2026 15:00"}, ...]}."""
    agora = datetime.now().strftime('%d/%m/%Y %H:%M')
    historico = {m: list(v) for m, v in historico_anterior.items()}
    for r in rows:
        desc = r['DESCRICAO_ULTIMO']
        if not desc:
            continue
        minuta = r['MINUTA']
        anteriores = historico.get(minuta, [])
        if not anteriores or anteriores[-1]['descricao'] != desc:
            historico[minuta] = anteriores + [{'descricao': desc, 'detectado_em': agora}]
    return historico


def build_raw(rows, gerado_em=None):
    meses = sorted(set(r['MES'] for r in rows))
    tipos = sorted(set(r['TIPO EMISSÃO'] for r in rows))
    ufs = sorted(set(r['EFF_UF'] for r in rows if r['EFF_UF']))
    clientes = sorted(set(r['CLIENTE'] for r in rows))
    return {
        'meta': {
            'meses': meses,
            'tipos_emissao': tipos,
            'ufs': ufs,
            'clientes': clientes,
            'gerado_em': gerado_em or datetime.now().strftime('%d/%m/%Y %H:%M'),
        },
        'rows': rows,
    }


def read_json_blob(content, marker):
    pos = content.find(marker)
    if pos == -1:
        return None
    start = pos + len(marker)
    decoder = json.JSONDecoder()
    data, _ = decoder.raw_decode(content, start)
    return data


def replace_json_blob(content, marker, new_json):
    pos = content.find(marker)
    if pos == -1:
        raise ValueError(f'Marcador nao encontrado: {marker!r}')
    start = pos + len(marker)
    decoder = json.JSONDecoder()
    _, end = decoder.raw_decode(content, start)
    return content[:start] + new_json + content[end:]


def main():
    if len(sys.argv) < 2:
        print('Uso: python atualizar_dashboard.py <planilha.xlsx> [pasta_do_dashboard]')
        sys.exit(1)

    xlsx_path = Path(sys.argv[1])
    dash_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).parent
    index_path = dash_dir / 'index.html'

    if not xlsx_path.exists():
        print(f'Planilha nao encontrada: {xlsx_path}')
        sys.exit(1)

    print(f'Lendo {xlsx_path}...')
    df = pd.read_excel(xlsx_path, sheet_name='Brudam')
    print(f'{len(df)} linhas carregadas.')

    rows = build_rows(df)
    raw = build_raw(rows)

    print(f"Periodo: {raw['meta']['meses'][0]} a {raw['meta']['meses'][-1]}")
    print(f"Clientes: {raw['meta']['clientes']}")
    print(f"Linhas RAW: {len(rows)}")

    index_content = index_path.read_text(encoding='utf-8')
    raw_json = json.dumps(raw, ensure_ascii=False)
    index_content = replace_json_blob(index_content, 'const RAW = ', raw_json)

    # Historico de ocorrencias (ver build_ocorrencias_historico) -- guardado
    # tambem solto no repo (nao so no blob do index.html) pra sobreviver
    # mesmo se o blob for reconstruido do zero num passo futuro.
    hist_path = dash_dir / 'ocorrencias_historico.json'
    historico_anterior = json.loads(hist_path.read_text(encoding='utf-8')) if hist_path.exists() else {}
    historico = build_ocorrencias_historico(rows, historico_anterior)
    hist_path.write_text(json.dumps(historico, ensure_ascii=False), encoding='utf-8')
    index_content = replace_json_blob(index_content, 'const OCORRENCIAS_HIST = ', json.dumps(historico, ensure_ascii=False))
    print(f'Atualizado: {hist_path} ({sum(len(v) for v in historico.values())} eventos em {len(historico)} minutas)')

    index_path.write_text(index_content, encoding='utf-8')
    print(f'Atualizado: {index_path}')

    # ocorrencias_problema.json -- minutas que ja tiveram ocorrencia-problema
    # (mesmo que ja resolvida), publicada solta no repo pro Mural buscar e
    # o time marcar o motivo -- mesmo padrao do em_transito.json, mas sem
    # se limitar as minutas ainda em transito.
    ocorrencias_problema = build_ocorrencias_problema(rows, historico)
    ocorrencias_problema_path = dash_dir / 'ocorrencias_problema.json'
    ocorrencias_problema_path.write_text(json.dumps(ocorrencias_problema, ensure_ascii=False), encoding='utf-8')
    print(f'Atualizado: {ocorrencias_problema_path} ({len(ocorrencias_problema)} minutas)')

    # em_transito.json -- lista das minutas ainda em transito (mesmo
    # criterio da aba "Em Transito" do dashboard), publicada solta no
    # repo pra o Mural buscar ao vivo (fetch direto do GitHub, sem
    # precisar que eu republique o Mural toda vez que uma minuta e
    # entregue e sai da lista).
    em_transito = [
        {
            'minuta': r['MINUTA'],
            'nf': r['NF_DOC'],
            'cliente': r['CLIENTE'],
            'destinatario': r['EFF_LOCAL'],
            'cidade': r['EFF_CIDADE'],
            'uf': r['EFF_UF'],
            'redespacho': r['REDESPACHO'],
            'prazo': r['DATA DE AGENDAMENTO'] or r['PREV. ENTREGA'],
            'descricao': r['DESCRICAO_ULTIMO'],
        }
        for r in rows
        if r['STATUS'] in ('EM TRANSITO DENTRO DO PRAZO', 'EM TRANSITO FORA DO PRAZO')
    ]
    em_transito_path = dash_dir / 'em_transito.json'
    em_transito_path.write_text(json.dumps(em_transito, ensure_ascii=False), encoding='utf-8')
    print(f'Atualizado: {em_transito_path} ({len(em_transito)} minutas em transito)')


if __name__ == '__main__':
    main()
