"""
DataLab — Load: carrega data/processed/distritos.csv no PostgreSQL.

Cenário do ambiente atual (mesmo de test_connection.py):
  - Python executando no Windows, dentro do venv (.venv).
  - PostgreSQL executando num container Docker (serviço 'postgres'),
    com a porta publicada no host (POSTGRES_PORT, default 5432).
  - Por isso o host de conexão é 'localhost'.

O script:
  1. Lê o CSV produzido pela etapa Transform (10.751 distritos).
  2. Cria a tabela 'distritos' caso ainda não exista ('id' é a PRIMARY KEY).
  3. Insere os registros com INSERT ... ON CONFLICT (id) DO NOTHING:
     execuções repetidas não duplicam dados (linhas já existentes
     são ignoradas).

Uso (raiz do projeto):
    .venv\\Scripts\\python etl/load/load_distritos.py

As credenciais são lidas do arquivo .env da raiz do projeto.
Nenhuma senha é exibida nem registrada por este script.
"""

import os
import sys
from pathlib import Path

import pandas as pd
import psycopg
from dotenv import load_dotenv

# Raiz do projeto: sobe de etl/load/ até o diretório que contém o .env
RAIZ_PROJETO = Path(__file__).resolve().parents[2]
load_dotenv(RAIZ_PROJETO / ".env")

# Arquivo produzido pela etapa Transform
ARQUIVO_PROCESSADO = RAIZ_PROJETO / "data" / "processed" / "distritos.csv"

# PostgreSQL roda no Docker: conexão local via localhost (Windows → host)
DB_HOST = "localhost"
DB_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
DB_NAME = os.getenv("POSTGRES_DB")
DB_USER = os.getenv("POSTGRES_USER")
DB_PASSWORD = os.getenv("POSTGRES_PASSWORD")

NOME_TABELA = "distritos"

# Colunas esperadas no CSV (na ordem gravada pela etapa Transform).
# O id é a chave primária; as demais colunas são TEXT porque o Transform
# já normalizou os códigos do IBGE como texto (ex.: '52010', sem '.0').
COLUNAS_TABELA = [
    "id",
    "nome",
    "municipio_id",
    "municipio_nome",
    "municipio_microrregiao_id",
    "municipio_microrregiao_nome",
    "municipio_microrregiao_mesorregiao_id",
    "municipio_microrregiao_mesorregiao_nome",
    "municipio_microrregiao_mesorregiao_UF_id",
    "municipio_microrregiao_mesorregiao_UF_sigla",
    "municipio_microrregiao_mesorregiao_UF_nome",
    "municipio_microrregiao_mesorregiao_UF_regiao_id",
    "municipio_microrregiao_mesorregiao_UF_regiao_sigla",
    "municipio_microrregiao_mesorregiao_UF_regiao_nome",
    "municipio_regiao_imediata_id",
    "municipio_regiao_imediata_nome",
    "municipio_regiao_imediata_regiao_intermediaria_id",
    "municipio_regiao_imediata_regiao_intermediaria_nome",
    "municipio_regiao_imediata_regiao_intermediaria_UF_id",
    "municipio_regiao_imediata_regiao_intermediaria_UF_sigla",
    "municipio_regiao_imediata_regiao_intermediaria_UF_nome",
    "municipio_regiao_imediata_regiao_intermediaria_UF_regiao_id",
    "municipio_regiao_imediata_regiao_intermediaria_UF_regiao_sigla",
    "municipio_regiao_imediata_regiao_intermediaria_UF_regiao_nome",
]


def validar_credenciais() -> list:
    """Devolve as variáveis de ambiente ausentes (lista vazia = tudo ok)."""
    return [
        nome
        for nome, valor in {
            "POSTGRES_DB": DB_NAME,
            "POSTGRES_USER": DB_USER,
            "POSTGRES_PASSWORD": DB_PASSWORD,
        }.items()
        if not valor
    ]


def conectar():
    """Abre a conexão com o PostgreSQL (mesmo padrão de test_connection.py)."""
    try:
        return psycopg.connect(
            host=DB_HOST,
            port=DB_PORT,
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            connect_timeout=5,
        )
    except psycopg.OperationalError as erro:
        sys.exit(
            f"FALHA na conexão com o PostgreSQL em {DB_HOST}:{DB_PORT}.\n"
            f"Detalhe: {erro}\n"
            "Verifique se o container do PostgreSQL está rodando "
            "(docker compose up -d) e se o .env está correto."
        )


def ler_csv(caminho: Path) -> pd.DataFrame:
    """Lê o CSV transformado como texto, preservando valores ausentes."""
    if not caminho.is_file():
        sys.exit(f"ERRO: arquivo não encontrado. Rode antes a etapa Transform: {caminho}")

    df = pd.read_csv(caminho, dtype="string")
    if list(df.columns) != COLUNAS_TABELA:
        sys.exit(
            "ERRO: estrutura do CSV inesperada (colunas diferentes das esperadas).\n"
            f"Esperado: {COLUNAS_TABELA}\n"
            f"Recebido: {list(df.columns)}"
        )
    print(f"CSV lido: {caminho}")
    print(f"Registros no arquivo: {len(df)}")
    print(f"Colunas: {df.shape[1]}")
    return df


def criar_tabela(cursor) -> None:
    """Cria a tabela 'distritos' se ainda não existir (id é a PRIMARY KEY)."""
    colunas_sql = ",\n    ".join(f"{coluna} TEXT" for coluna in COLUNAS_TABELA)
    colunas_sql = colunas_sql.replace("id TEXT", "id TEXT PRIMARY KEY", 1)
    sql = (
        f"CREATE TABLE IF NOT EXISTS {NOME_TABELA} (\n"
        f"    {colunas_sql}\n"
        f");"
    )
    cursor.execute(sql)
    print(f"Tabela '{NOME_TABELA}' pronta (criada caso não existisse).")


def linhas_para_sql(df: pd.DataFrame):
    """Converte cada linha do DataFrame em tupla aceita pelo psycopg.

    Valores ausentes do pandas (NA) viram None (NULL no banco);
    nada é preenchido nem descartado.
    """
    for linha in df.itertuples(index=False, name=None):
        yield tuple(None if pd.isna(valor) else valor for valor in linha)


def inserir_registros(conexao, df: pd.DataFrame) -> tuple:
    """Insere os registros ignorando 'id' já existente (ON CONFLICT).

    Devolve (ja_existiam, inseridos) contando via COUNT antes/depois,
    para o resumo ser confiável mesmo em execuções repetidas.
    """
    colunas_placeholders = ", ".join(["%s"] * len(COLUNAS_TABELA))
    lista_colunas = ", ".join(COLUNAS_TABELA)
    sql = (
        f"INSERT INTO {NOME_TABELA} ({lista_colunas}) "
        f"VALUES ({colunas_placeholders}) "
        f"ON CONFLICT (id) DO NOTHING;"
    )

    with conexao.cursor() as cursor:
        cursor.execute(f"SELECT COUNT(*) FROM {NOME_TABELA};")
        existiam = cursor.fetchone()[0]

        cursor.executemany(sql, linhas_para_sql(df))

        cursor.execute(f"SELECT COUNT(*) FROM {NOME_TABELA};")
        total_final = cursor.fetchone()[0]

    inseridos = total_final - existiam
    ja_existiam = len(df) - inseridos
    return ja_existiam, inseridos, total_final


def main() -> int:
    # Garante acentos corretos no terminal do Windows.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    faltando = validar_credenciais()
    if faltando:
        sys.exit(
            f"ERRO: variáveis ausentes no .env: {', '.join(faltando)}. "
            "Copie .env.example para .env e preencha."
        )

    df = ler_csv(ARQUIVO_PROCESSADO)

    print(f"\nConectando em {DB_HOST}:{DB_PORT} (banco {DB_NAME})...")
    with conectar() as conexao:
        with conexao.cursor() as cursor:
            criar_tabela(cursor)
        ja_existiam, inseridos, total_final = inserir_registros(conexao, df)

    print("\n=== Resumo da operação ===")
    print(f"Tabela: {NOME_TABELA}")
    print(f"Registros lidos do CSV: {len(df)}")
    print(f"Já existiam no banco (ignorados): {ja_existiam}")
    print(f"Inseridos agora: {inseridos}")
    print(f"Total na tabela após o load: {total_final}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
