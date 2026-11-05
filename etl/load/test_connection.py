"""
DataLab — teste de conexão Python (Windows) → PostgreSQL (Docker).

Cenário do ambiente atual:
  - Python executando no Windows, dentro do venv (.venv).
  - PostgreSQL executando num container Docker (serviço 'postgres'),
    com a porta publicada no host (POSTGRES_PORT, default 5432).
  - Por isso o host de conexão é 'localhost'.

Uso (raiz do projeto):
    .venv\\Scripts\\python etl/load/test_connection.py

Saída esperada em caso de sucesso:
    Conexão com PostgreSQL OK.
    PostgreSQL 16.x ... (versão do servidor)

As credenciais são lidas do arquivo .env da raiz do projeto.
Nenhuma senha é exibida nem registrada por este script.
"""

import os
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv

# Raiz do projeto: sobe de etl/load/ até o diretório que contém o .env
RAIZ_PROJETO = Path(__file__).resolve().parents[2]
load_dotenv(RAIZ_PROJETO / ".env")

# PostgreSQL roda no Docker: conexão local via localhost (Windows → host)
DB_HOST = "localhost"
DB_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
DB_NAME = os.getenv("POSTGRES_DB")
DB_USER = os.getenv("POSTGRES_USER")
DB_PASSWORD = os.getenv("POSTGRES_PASSWORD")


def main() -> None:
    # Valida presença das variáveis sem expor valores
    faltando = [
        nome
        for nome, valor in {
            "POSTGRES_DB": DB_NAME,
            "POSTGRES_USER": DB_USER,
            "POSTGRES_PASSWORD": DB_PASSWORD,
        }.items()
        if not valor
    ]
    if faltando:
        sys.exit(
            f"ERRO: variáveis ausentes no .env: {', '.join(faltando)}. "
            "Copie .env.example para .env e preencha."
        )

    try:
        with psycopg.connect(
            host=DB_HOST,
            port=DB_PORT,
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            connect_timeout=5,
        ) as conexao:
            with conexao.cursor() as cursor:
                cursor.execute("SELECT version();")
                versao = cursor.fetchone()[0]

        print("Conexão com PostgreSQL OK.")
        print(f"Servidor: {versao}")
        print(f"Banco: {DB_NAME} em {DB_HOST}:{DB_PORT}")
    except psycopg.OperationalError as erro:
        sys.exit(
            f"FALHA na conexão com o PostgreSQL em {DB_HOST}:{DB_PORT}.\n"
            f"Detalhe: {erro}\n"
            "Verifique se o container do PostgreSQL está rodando "
            "(docker compose up -d) e se o .env está correto."
        )


if __name__ == "__main__":
    main()
