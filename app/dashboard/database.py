"""
DataLab — Dashboard: consultas do dashboard ao PostgreSQL.

Camada de dados do painel: cada função devolve um pandas.DataFrame (ou um
dicionário de indicadores inteiros), formato em que o Streamlit consome
direto (st.dataframe, st.bar_chart, st.map, plotly). Nenhuma função daqui
desenha gráfico — a etapa de visualização vem depois.

Hierarquias territoriais no banco
---------------------------------
O IBGE entrega cada distrito por dois caminhos equivalentes, e o ETL
gravou os dois:

  caminho 1: municipio -> microrregiao      -> mesorregiao        -> UF -> regiao
  caminho 2: municipio -> regiao_imediata   -> regiao_intermediaria -> UF -> regiao

Verificado no banco atual (10.751 linhas): os dois caminhos discordam em
0 registros, ambos têm 27 UFs e 5 regiões. O caminho 1 tem 1 lacuna (id
510183705 — Boa Esperança do Norte, não tem microrregiao/mesorregiao/UF no
endereço 1); o caminho 2 está completo e informa UF = MT e região =
Centro-Oeste para esse registro.

Por isso as consultas usam a UF e a região "efetivas": o valor do caminho 1
quando existe, senão o do caminho 2 (COALESCE). Isso não preenche nem
inventa nada — é somente ler o dado do endereço onde o IBGE o registrou.
A coluna uf_hierarquia diz de qual caminho veio o valor, para o painel
poder reportar a lacuna sem escondê-la.

Valores NULL
------------
NULL é informação ausente: nunca é preenchido com valor inventado e nunca é
usado como motivo para excluir linha. Nenhum rótulo do tipo "Sem UF" é
colocado no lugar do NULL — a camada de visualização decide como mostrar.
  - Indicadores: COUNT(DISTINCT ...) e COUNT(*) FILTER ignoram NULL na
    contagem (comportamento padrão do SQL) e existem chaves próprias
    ('distritos_sem_uf' e 'distritos_sem_microrregiao') para quantificar as
    lacunas em vez de omiti-las.
  - Agrupamentos (por UF e por região): NULL forma uma linha própria, que é
    mantida; assim a soma de 'distritos' continua igual ao total da tabela e
    nenhuma linha desaparece do mapa ou do gráfico de barras.
  - Lista de distritos: traz o valor original, NULL permanece NULL.

Conexão e credenciais: mesmo padrão do ETL (etl/load/test_connection.py).
  - PostgreSQL roda em container Docker com a porta publicada no host, então
    o host de conexão é 'localhost'.
  - As credenciais vêm do arquivo .env na raiz do projeto.
  - Nenhuma senha é exibida nem registrada por este módulo.

Uso:
    from app.dashboard import database as db
    db.indicadores_gerais()          # dict com 7 indicadores
    db.distritos_por_uf()            # DataFrame (27 UFs)
    db.distritos_por_regiao()        # DataFrame (5 regiões)
    db.top_municipios_mais_distritos()          # DataFrame (top 10)
    db.consultar_distritos(sigla_uf='SP')       # DataFrame com filtros
    db.distritos_sem_uf_identificada()          # DataFrame de auditoria
"""

import os
from pathlib import Path
from typing import Optional

import pandas as pd
import psycopg
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Conexão e credenciais (.env)
# ---------------------------------------------------------------------------

# Raiz do projeto: sobe de app/dashboard/ até o diretório com o .env
RAIZ_PROJETO = Path(__file__).resolve().parents[2]
load_dotenv(RAIZ_PROJETO / ".env")

DB_HOST = "localhost"
DB_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
DB_NAME = os.getenv("POSTGRES_DB")
DB_USER = os.getenv("POSTGRES_USER")
DB_PASSWORD = os.getenv("POSTGRES_PASSWORD")

NOME_TABELA_DISTRITOS = "distritos"

# ---------------------------------------------------------------------------
# Nomes de colunas: centralizados aqui para evitar erro de digitação.
# O PostgreSQL grava em minúsculas os identificadores criados sem aspas,
# por isso o IBGE 'UF' aparece no banco como 'uf'.
# ---------------------------------------------------------------------------
COL_ID_DISTRITO = "id"
COL_NOME_DISTRITO = "nome"
COL_MUNICIPIO_ID = "municipio_id"
COL_MUNICIPIO_NOME = "municipio_nome"

# Caminho 1: municipio -> microrregiao -> mesorregiao -> UF -> regiao
COL_MICRORREGIAO_ID = "municipio_microrregiao_id"
COL_MICRORREGIAO_NOME = "municipio_microrregiao_nome"
COL_UF_ID_MICROR = "municipio_microrregiao_mesorregiao_uf_id"
COL_UF_SIGLA_MICROR = "municipio_microrregiao_mesorregiao_uf_sigla"
COL_UF_NOME_MICROR = "municipio_microrregiao_mesorregiao_uf_nome"
COL_REGIAO_ID_MICROR = "municipio_microrregiao_mesorregiao_uf_regiao_id"
COL_REGIAO_SIGLA_MICROR = "municipio_microrregiao_mesorregiao_uf_regiao_sigla"
COL_REGIAO_NOME_MICROR = "municipio_microrregiao_mesorregiao_uf_regiao_nome"

# Caminho 2: municipio -> regiao_imediata -> regiao_intermediaria -> UF -> regiao
COL_UF_ID_INTERM = "municipio_regiao_imediata_regiao_intermediaria_uf_id"
COL_UF_SIGLA_INTERM = "municipio_regiao_imediata_regiao_intermediaria_uf_sigla"
COL_UF_NOME_INTERM = "municipio_regiao_imediata_regiao_intermediaria_uf_nome"
COL_REGIAO_ID_INTERM = "municipio_regiao_imediata_regiao_intermediaria_uf_regiao_id"
COL_REGIAO_SIGLA_INTERM = "municipio_regiao_imediata_regiao_intermediaria_uf_regiao_sigla"
COL_REGIAO_NOME_INTERM = "municipio_regiao_imediata_regiao_intermediaria_uf_regiao_nome"

# UF e região "efetivas": valor do caminho 1 quando existente, senão do
# caminho 2. Nenhum valor é inventado — é apenas a leitura do dado em um dos
# dois endereços onde o IBGE o registra.
EXPRESSAO_UF_ID = f"COALESCE({COL_UF_ID_MICROR}, {COL_UF_ID_INTERM})"
EXPRESSAO_UF_SIGLA = f"COALESCE({COL_UF_SIGLA_MICROR}, {COL_UF_SIGLA_INTERM})"
EXPRESSAO_UF_NOME = f"COALESCE({COL_UF_NOME_MICROR}, {COL_UF_NOME_INTERM})"
EXPRESSAO_REGIAO_ID = f"COALESCE({COL_REGIAO_ID_MICROR}, {COL_REGIAO_ID_INTERM})"
EXPRESSAO_REGIAO_SIGLA = f"COALESCE({COL_REGIAO_SIGLA_MICROR}, {COL_REGIAO_SIGLA_INTERM})"
EXPRESSAO_REGIAO_NOME = f"COALESCE({COL_REGIAO_NOME_MICROR}, {COL_REGIAO_NOME_INTERM})"

# Caminho de onde a UF pode estar ausente por lacuna de cadastro do IBGE.
# Atualmente é 1 registro (id 510183705 — Boa Esperança do Norte/MT): ele não
# tem o bloco da microrregiao preenchido, mas UF e regiao continuam
# identificadas pelo caminho 2. Nada foi excluído — isto é usado como
# auditoria e para rotular a hierarquia efetiva de origem.
COLUNA_HIERARQUIA_UF = COL_MICRORREGIAO_ID


def conectar():
    """Abre e devolve a conexão com o PostgreSQL."""
    return psycopg.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        connect_timeout=5,
    )


def _executar_consulta(sql: str, params: Optional[tuple] = None) -> pd.DataFrame:
    """Roda uma query e devolve o resultado como DataFrame.

    Cada consulta usa uma conexão nova (barato em localhost e sem risco de
    estado compartilhado entre os reruns do Streamlit). Toda a SQL vem de
    constantes deste módulo, exceto os filtros, que são sempre
    parametrizados (%s) — nunca interpolados.

    Parâmetros:
        sql: a consulta.
        params: tupla com os valores de %s, se a consulta tiver filtros.

    Retorna:
        pandas.DataFrame com as colunas e os nomes definidos no SELECT.
    """
    with conectar() as conexao:
        with conexao.cursor() as cursor:
            cursor.execute(sql, params)
            colunas = [descricao.name for descricao in cursor.description]
            linhas = cursor.fetchall()
    return pd.DataFrame(linhas, columns=colunas)


# ---------------------------------------------------------------------------
# Consultas em SQL (constantes — os únicos trechos interpolados são os
# nomes de colunas deste módulo, nunca valores digitados pelo usuário).
# ---------------------------------------------------------------------------

_SQL_INDICADORES_GERAIS = f"""
SELECT
    COUNT(*)                                                AS total_distritos,
    COUNT(DISTINCT {COL_MUNICIPIO_ID})                      AS total_municipios,
    COUNT(DISTINCT {EXPRESSAO_UF_ID})                       AS total_ufs,
    COUNT(DISTINCT {EXPRESSAO_REGIAO_ID})                   AS total_regioes,
    COUNT(*) FILTER (
        WHERE {EXPRESSAO_UF_ID} IS NULL
    )                                                       AS distritos_sem_uf,
    COUNT(*) FILTER (
        WHERE {COL_MICRORREGIAO_ID} IS NULL
    )                                                       AS distritos_sem_microrregiao
FROM {NOME_TABELA_DISTRITOS};
"""

# Agrupamento pela UF efetiva. Se algum registro ficar sem UF nos dois
# caminhos, ele forma uma linha propria de uf_sigla/uf_nome NULL e nao e
# descartado: a soma de 'distritos' continua igual ao total da tabela
# (verificado em teste), entao o mapa coropletico e o grafico de barras
# mostram a lacuna em vez de perde-la.
_SQL_DISTRITOS_POR_UF = f"""
SELECT
    {EXPRESSAO_UF_SIGLA} AS uf_sigla,
    {EXPRESSAO_UF_NOME}  AS uf_nome,
    COUNT(*)             AS distritos
FROM {NOME_TABELA_DISTRITOS}
GROUP BY {EXPRESSAO_UF_SIGLA}, {EXPRESSAO_UF_NOME}
ORDER BY distritos DESC, uf_nome NULLS LAST;
"""

# Mesma regra da UF aplicada a regiao (grafico de rosca).
_SQL_DISTRITOS_POR_REGIAO = f"""
SELECT
    {EXPRESSAO_REGIAO_SIGLA} AS regiao_sigla,
    {EXPRESSAO_REGIAO_NOME}  AS regiao_nome,
    COUNT(*)                 AS distritos
FROM {NOME_TABELA_DISTRITOS}
GROUP BY {EXPRESSAO_REGIAO_SIGLA}, {EXPRESSAO_REGIAO_NOME}
ORDER BY distritos DESC, regiao_nome NULLS LAST;
"""

# Agrupa por municipio_id E municipio_nome, como pedido. Agrupar pelo codigo
# evita misturar municipios homogeneous de estados diferentes. NULL
# permanece NULL na saida: nada e preenchido.
_SQL_TOP_MUNICIPIOS = f"""
SELECT
    {COL_MUNICIPIO_ID}   AS municipio_id,
    {COL_MUNICIPIO_NOME} AS municipio_nome,
    {EXPRESSAO_UF_SIGLA} AS uf_sigla,
    COUNT(*)             AS distritos
FROM {NOME_TABELA_DISTRITOS}
GROUP BY {COL_MUNICIPIO_ID}, {COL_MUNICIPIO_NOME}, {EXPRESSAO_UF_SIGLA}
ORDER BY distritos DESC, municipio_nome NULLS LAST, municipio_id
LIMIT %s;
"""

# Colunas devolvidas nas listagens. Os apelidos sao definidos aqui via AS,
# entao nao dependem de como o PostgreSQL gravou o cabecalho do CSV.
# 'uf_hierarquia' registra de qual dos dois caminhos o IBGE veio a UF.
_COLUNAS_LISTAGEM = f"""    {COL_ID_DISTRITO}          AS id,
    {COL_NOME_DISTRITO}        AS nome,
    {COL_MUNICIPIO_ID}         AS municipio_id,
    {COL_MUNICIPIO_NOME}       AS municipio_nome,
    {EXPRESSAO_UF_ID}          AS uf_id,
    {EXPRESSAO_UF_SIGLA}       AS uf_sigla,
    {EXPRESSAO_UF_NOME}        AS uf_nome,
    CASE
        WHEN {COL_UF_ID_MICROR} IS NOT NULL THEN 'microrregiao'
        WHEN {COL_UF_ID_INTERM} IS NOT NULL THEN 'regiao_imediata'
        ELSE NULL
    END                        AS uf_hierarquia,
    {EXPRESSAO_REGIAO_SIGLA}   AS regiao_sigla,
    {EXPRESSAO_REGIAO_NOME}    AS regiao_nome,
    {COL_MICRORREGIAO_NOME}    AS microrregiao_nome"""

# Todos os filtros sao parametrizados (%s). Cada condicao so e acrescentada
# ao WHERE quando o valor e informado; fora disso nada e interpolado.
_SQL_BASE_DISTRITOS_FILTRO = (
    f"SELECT\n{_COLUNAS_LISTAGEM}\nFROM {NOME_TABELA_DISTRITOS}"
)

_SQL_ORDENACAO_DISTRITOS_FILTRO = """
ORDER BY uf_nome NULLS LAST, municipio_nome NULLS LAST, nome, id;
"""

# Auditoria da lacuna territorial: lista os registros cujo caminho 1 nao
# trouxe microrregiao/UF (hoje 1 linha). Nada e ocultado nem corrigido.
# A UF efetiva continua vindo do caminho 2, entao a listagem mostra a
# origem (uf_hierarquia = 'regiao_imediata') em vez de esconder o vazio.
_SQL_DISTRITOS_SEM_UF = (
    f"SELECT\n{_COLUNAS_LISTAGEM}\n"
    f"FROM {NOME_TABELA_DISTRITOS}\n"
    f"WHERE {COLUNA_HIERARQUIA_UF} IS NULL\n"
    f"   OR {EXPRESSAO_UF_ID} IS NULL\n"
    "ORDER BY id;"
)


# ---------------------------------------------------------------------------
# Funções de consulta publicadas para o dashboard
# ---------------------------------------------------------------------------

def indicadores_gerais() -> dict:
    """Indicadores gerais da tabela de distritos.

    Retorna:
        dict com valores inteiros:
            total_distritos             -> linhas da tabela (10.751)
            total_municipios            -> municipio_id distintos
            total_ufs                   -> UFs distintas (26 estados + DF)
            total_regioes               -> regioes distintas (5)
            distritos_sem_uf            -> sem UF nos DOIS caminhos
            distritos_sem_microrregiao  -> lacuna do caminho 1 (hoje 1)

        total_ufs e total_regioes usam a UF/regiao efetivas, entao o
        registro sem microrregiao continua contabilizado: o IBGE o
        classifica em MT/Centro-Oeste pelo caminho 2.
    """
    linha = _executar_consulta(_SQL_INDICADORES_GERAIS).iloc[0]
    return {chave: int(valor) for chave, valor in linha.items()}


def distritos_por_uf() -> pd.DataFrame:
    """Distritos por UF — base do mapa coroplético e do gráfico de barras.

    Retorna:
        DataFrame com uf_sigla, uf_nome, distritos (int64): uma linha por
        UF, hoje 27 (26 estados + Distrito Federal), ordenado do maior para
        o menor. Registro sem UF nos dois caminhos, se existir, forma uma
        linha de sigla/nome NULL em vez de ser descartado — a soma de
        'distritos' permanece igual a total_distritos (testado), então o
        mapa não perde dado silenciosamente.
    """
    df = _executar_consulta(_SQL_DISTRITOS_POR_UF)
    df["distritos"] = df["distritos"].astype("int64")
    return df


def distritos_por_regiao() -> pd.DataFrame:
    """Distritos por região — base do gráfico de rosca.

    Retorna:
        DataFrame com regiao_sigla, regiao_nome, distritos (int64),
        ordenado do maior para o menor (Norte, Nordeste, Centro-Oeste,
        Sudeste e Sul no conjunto atual). Mesma regra de NULL da UF: nada é
        removido e a soma bate com o total da tabela.
    """
    df = _executar_consulta(_SQL_DISTRITOS_POR_REGIAO)
    df["distritos"] = df["distritos"].astype("int64")
    return df


def top_municipios_mais_distritos(limite: int = 10) -> pd.DataFrame:
    """Municípios com mais distritos (agrupando por id E nome).

    Agrupar pelo codigo, e nao so pelo nome, evita misturar municipios
    homonimos de estados diferentes.

    Parâmetros:
        limite: quantidade maxima de linhas (padrao 10).

    Retorna:
        DataFrame com municipio_id, municipio_nome, uf_sigla, distritos
        (int64), ordenado do maior para o menor. NULL de municipio_nome nao
        eh preenchido: permanece NULL na saida.
    """
    limite = int(limite)
    if limite < 1:
        raise ValueError("limite precisa ser um inteiro maior que zero.")
    df = _executar_consulta(_SQL_TOP_MUNICIPIOS, (limite,))
    df["distritos"] = df["distritos"].astype("int64")
    return df


def consultar_distritos(
    sigla_uf: Optional[str] = None,
    municipio: Optional[str] = None,
) -> pd.DataFrame:
    """Distritos com filtros opcionais de UF e município.

    Os filtros informados são combinados com AND e seguem sempre como
    parâmetros (%s) do driver, nunca interpolados na string SQL.

    Parâmetros:
        sigla_uf: sigla da UF ('SP'). Comparação por igualdade, ou ILIKE
            quando o texto contiver os curingas '%' / '_'.
        municipio: nome do município; mesma regra acima, aceita por
            igualdade exata, ou padrão LIKE/ILIKE se contiver curinga.

        Os dois comparam a UF/região EFETIVAs, então o filtro 'MT' devolve
        também o distrito que não tem microrregião.

    Retorna:
        DataFrame com id, nome, municipio_id, municipio_nome, uf_id,
        uf_sigla, uf_nome, uf_hierarquia, regiao_sigla, regiao_nome e
        microrregiao_nome, ordenado por UF, município e nome. Nenhum dos
        filtros: a tabela inteira.
    """
    condicoes = []
    parametros = []

    if sigla_uf:
        operador = "ILIKE" if _contem_curinga_like(sigla_uf) else "="
        condicoes.append(f"{EXPRESSAO_UF_SIGLA} {operador} %s")
        parametros.append(sigla_uf)

    if municipio:
        operador = "ILIKE" if _contem_curinga_like(municipio) else "="
        condicoes.append(f"{COL_MUNICIPIO_NOME} {operador} %s")
        parametros.append(municipio)

    sql = _SQL_BASE_DISTRITOS_FILTRO
    if condicoes:
        sql += " WHERE " + " AND ".join(condicoes)
    sql += _SQL_ORDENACAO_DISTRITOS_FILTRO

    return _executar_consulta(sql, tuple(parametros) if parametros else None)


def distritos_sem_uf_identificada() -> pd.DataFrame:
    """Auditoria dos registros com o caminho 1 (microrregião) vazio.

    Não preenche nem descarta nada: devolve os distritos cuja microrregiao
    nao veio do IBGE (hoje 1 registro, id 510183705) ou que estariam sem UF
    nos dois caminhos. Para cada um, uf_sigla/uf_nome/regiao mostram o que
    o cadastro informa e uf_hierarquia diz de onde esse valor veio.

    Retorna:
        DataFrame com as mesmas colunas de consultar_distritos(), ordenado
        por id. Vazio se a lacuna não existir mais.
    """
    return _executar_consulta(_SQL_DISTRITOS_SEM_UF)


def _contem_curinga_like(valor: str) -> bool:
    """True se o texto usa os curingas do LIKE ('%' ou '_').

    Serve só para escolher o operador ('=' ou ILIKE). O valor em si segue
    pelo driver como parâmetro, nunca pela string SQL — o que mantém a
    consulta imune a injeção.
    """
    return "%" in valor or "_" in valor
