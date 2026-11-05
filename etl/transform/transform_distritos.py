"""
DataLab — Transform (v2): transformação efetiva dos distritos do IBGE.

A v1 lia e DESCREVIA os dados brutos; esta versão aplica a transformação
e grava o resultado em data/processed/distritos.csv. O arquivo bruto em
data/raw/ é aberto somente para leitura; nenhuma linha é excluída e
nenhum valor ausente é preenchido.

Etapas da transformação:
  1. Remove a coluna redundante 'municipio_microrregiao' (gerada pela
     normalização; verificada como 100% ausente, sem informação útil).
  2. Padroniza os nomes das colunas: hífens viram underscores.
  3. Converte as colunas *_id para texto (ex.: '52010' em vez de
     '52010.0'), preservando os valores ausentes.

Verificações após transformar:
  - Nenhuma linha foi perdida (contagem final igual à inicial).
  - Linhas com 'id' duplicado (0 no conjunto atual).

Estrutura real do arquivo (verificada na v1):
  - O JSON é uma LISTA de objetos (um por distrito).
  - Cada objeto tem 'id', 'nome' e blocos ANINHADOS:
      municipio -> microrregiao -> mesorregiao -> UF -> regiao
      municipio -> regiao-imediata -> regiao-intermediaria -> UF -> regiao
  - Por ser aninhado, usamos pd.json_normalize para "achatar" os
    blocos em colunas (ex.: municipio_microrregiao_mesorregiao_UF_sigla).

Execução (a partir da raiz do projeto, com o Python do venv):
    .venv\\Scripts\\python etl/transform/transform_distritos.py
"""

import json
import sys
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------
# Caminhos: sempre relativos à raiz do projeto, não ao diretório atual.
# Este arquivo está em <raiz>/etl/transform/, então a raiz é parents[2].
# ---------------------------------------------------------------------
RAIZ_PROJETO = Path(__file__).resolve().parents[2]
ARQUIVO_BRUTO = RAIZ_PROJETO / "data" / "raw" / "distritos.json"

# Saída da transformação; o diretório é criado automaticamente se faltar.
ARQUIVO_PROCESSADO = RAIZ_PROJETO / "data" / "processed" / "distritos.csv"

# Coluna redundante gerada pela normalização (100% ausente, sem valor útil).
COLUNA_REDUNDANTE = "municipio_microrregiao"

# Sufixo usado para identificar as colunas de código do IBGE.
SUFIXO_COLUNAS_ID = "_id"


class ErroDeDados(Exception):
    """Erro esperado (arquivo ausente, JSON inválido, estrutura inesperada)."""


def carregar_json(caminho: Path):
    """Lê o arquivo JSON (somente leitura) e devolve o objeto Python."""
    if not caminho.is_file():
        raise ErroDeDados(f"Arquivo não encontrado: {caminho}")

    try:
        # utf-8: o JSON do IBGE contém acentos (ex.: 'Goiás').
        with caminho.open("r", encoding="utf-8") as arquivo:
            return json.load(arquivo)
    except json.JSONDecodeError as erro:
        raise ErroDeDados(
            f"JSON inválido em {caminho.name}: {erro.msg} "
            f"(linha {erro.lineno}, coluna {erro.colno})"
        ) from erro
    except UnicodeDecodeError as erro:
        raise ErroDeDados(f"Codificação inesperada (esperado UTF-8): {erro}") from erro


def validar_estrutura(dados) -> list:
    """Confere se os dados são uma lista não vazia de objetos (dicts)."""
    if not isinstance(dados, list):
        raise ErroDeDados(
            f"Estrutura inesperada: esperava uma lista, veio {type(dados).__name__}."
        )
    if not dados:
        raise ErroDeDados("Estrutura inesperada: a lista está vazia.")

    # Localiza o primeiro item que não seja um objeto, se existir.
    for posicao, item in enumerate(dados):
        if not isinstance(item, dict):
            raise ErroDeDados(
                f"Estrutura inesperada: item {posicao} é {type(item).__name__}, "
                "esperava um objeto."
            )
    return dados


def criar_dataframe(registros: list) -> pd.DataFrame:
    """Converte a lista de registros em DataFrame, achatando os blocos aninhados."""
    try:
        # sep="_" gera nomes como 'municipio_nome' em vez de 'municipio.nome'.
        return pd.json_normalize(registros, sep="_")
    except Exception as erro:  # json_normalize pode falhar com estruturas estranhas
        raise ErroDeDados(f"Não foi possível converter para DataFrame: {erro}") from erro


def remover_coluna_redundante(df: pd.DataFrame, coluna: str) -> pd.DataFrame:
    """Remove uma coluna inteiramente nula, confirmando antes que ela
    não carrega informação útil (nenhum valor não nulo)."""
    if coluna not in df.columns:
        return df
    if not df[coluna].isna().all():
        raise ErroDeDados(
            f"A coluna '{coluna}' NÃO é totalmente nula: "
            "não será removida para não perder informação."
        )
    print(f"Coluna '{coluna}': 100% ausente — removida (redundante).")
    return df.drop(columns=[coluna])


def padronizar_nomes_colunas(df: pd.DataFrame) -> pd.DataFrame:
    """Substitui hífens por underscores nos nomes das colunas."""
    renomeacoes = {c: c.replace("-", "_") for c in df.columns if "-" in c}
    if renomeacoes:
        df = df.rename(columns=renomeacoes)
        print(f"Nomes padronizados (hífen -> '_'): {len(renomeacoes)} colunas.")
    return df


def converter_ids_para_texto(df: pd.DataFrame) -> pd.DataFrame:
    """Converte colunas terminadas em '_id' para texto.

    Evita números com '.0' (ex.: '52010' em vez de '52010.0') e preserva
    os valores ausentes — nada é preenchido nem descartado.
    """
    colunas_id = [c for c in df.columns if c.endswith(SUFIXO_COLUNAS_ID)]
    for coluna in colunas_id:
        serie = df[coluna]
        if pd.api.types.is_float_dtype(serie):
            # float64 só aparece quando há ausente; 'Int64' preserva o nulo
            # e descarta o sufixo '.0' antes da conversão para texto.
            serie = serie.astype("Int64")
        if not pd.api.types.is_string_dtype(serie):
            serie = serie.astype("string")
        df[coluna] = serie
    print(f"Colunas '*{SUFIXO_COLUNAS_ID}' convertidas para texto: {len(colunas_id)}.")
    return df


def transformar(df: pd.DataFrame) -> pd.DataFrame:
    """Aplica a transformação efetiva.

    Nenhuma LINHA é excluída e nenhum valor ausente é preenchido; só são
    feitas as limpezas solicitadas (coluna vazia, nomes e tipos de *_id).
    """
    df = remover_coluna_redundante(df, COLUNA_REDUNDANTE)
    df = padronizar_nomes_colunas(df)
    df = converter_ids_para_texto(df)
    return df


def verificar_ids_duplicados(df: pd.DataFrame) -> pd.Series:
    """Devolve a máscara (bool por linha) das ocorrências de 'id' repetido."""
    return df["id"].duplicated(keep=False)


def imprimir_titulo(texto: str) -> None:
    print(f"\n=== {texto} ===")


def exibir_resumo(df: pd.DataFrame) -> None:
    """Mostra o diagnóstico básico do DataFrame (sem alterá-lo)."""
    imprimir_titulo("Dimensões")
    print(f"Registros (linhas): {len(df)}")
    print(f"Colunas: {df.shape[1]}")

    imprimir_titulo("Nomes das colunas")
    for nome in df.columns:
        print(f"  - {nome}")

    imprimir_titulo("Tipos de dados")
    print(df.dtypes.to_string())

    imprimir_titulo("Valores ausentes por coluna")
    ausentes = df.isna().sum()
    print(ausentes.to_string())
    if (ausentes > 0).any():
        print(
            "\nObservação: colunas com ausências indicam registros cujo bloco "
            "aninhado veio nulo no JSON (ex.: 'municipio_microrregiao'). "
            "Se um bloco inteiro é nulo, suas colunas internas ficam ausentes."
        )

    imprimir_titulo("Amostra de 5 registros")
    # Transposta (.T): com muitas colunas, fica legível uma coluna por linha.
    print(df.head(5).T.to_string())


def salvar_csv(df: pd.DataFrame, caminho: Path) -> None:
    """Grava o DataFrame como CSV (utf-8), criando a pasta se necessário."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(caminho, index=False, encoding="utf-8")
    print(f"CSV gravado: {caminho}")


def exibir_relatorio_final(
    df: pd.DataFrame, caminho: Path, duplicados: pd.Series
) -> None:
    """Relatório pós-transform: dimensões, colunas, ausentes, duplicados e arquivo."""
    imprimir_titulo("Relatório final")
    print(f"Linhas: {len(df)}")
    print(f"Colunas: {df.shape[1]}")

    imprimir_titulo("Colunas finais")
    for nome in df.columns:
        print(f"  - {nome}")

    imprimir_titulo("Valores ausentes")
    ausentes = df.isna().sum()
    if (ausentes > 0).any():
        print(ausentes[ausentes > 0].to_string())
    else:
        print("Nenhum valor ausente.")

    imprimir_titulo("IDs duplicados (coluna 'id')")
    print(f"Linhas envolvidas em 'id' repetido: {int(duplicados.sum())}")
    if duplicados.any():
        ids_repetidos = df.loc[duplicados, "id"].unique()
        print("IDs repetidos:", ", ".join(map(str, ids_repetidos)))

    imprimir_titulo("Arquivo gerado")
    print(caminho)


def main() -> int:
    # Garante acentos corretos no terminal do Windows.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    print(f"Lendo: {ARQUIVO_BRUTO}")
    try:
        dados = carregar_json(ARQUIVO_BRUTO)
        registros = validar_estrutura(dados)
        df = criar_dataframe(registros)
    except ErroDeDados as erro:
        print(f"ERRO: {erro}", file=sys.stderr)
        return 1

    total_inicial = len(df)

    # Diagnóstico pré-transform (v1): descreve os dados que serão alterados.
    exibir_resumo(df)

    imprimir_titulo("Transformação")
    df = transformar(df)

    duplicados = verificar_ids_duplicados(df)

    imprimir_titulo("Verificações")
    if len(df) != total_inicial:
        # Guarda-saída: nunca deve acontecer (nenhuma linha é excluída).
        print(
            f"ERRO: contagem de registros mudou ({total_inicial} -> {len(df)}); "
            "abortando antes de gravar dados incompletos.",
            file=sys.stderr,
        )
        return 1
    print(
        f"Registros preservados: {len(df)} de {total_inicial} "
        f"({len(df) == total_inicial})."
    )
    print(f"Linhas com 'id' duplicado: {int(duplicados.sum())}.")

    salvar_csv(df, ARQUIVO_PROCESSADO)

    exibir_relatorio_final(df, ARQUIVO_PROCESSADO, duplicados)
    return 0


if __name__ == "__main__":
    sys.exit(main())
