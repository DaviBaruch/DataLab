"""
DataLab — Dashboard: interface visual para análise territorial.

Mapa coroplético das 27 UFs (malha oficial do IBGE), gráficos Plotly e
indicadores lidos do PostgreSQL via app/dashboard/database.py. Nenhuma
consulta SQL é duplicada aqui.

Fonte do GeoJSON (oficial — IBGE, API de Malhas):
    https://servicodados.ibge.gov.br/api/v3/malhas/paises/BR
    com formato=application/vnd.geo+json, qualidade=intermediaria e
    intrarregiao=UF — devolve as 27 UFs, identificadas por
    properties.codarea (código oficial IBGE, ex.: 53 = Distrito Federal).
    O arquivo é baixado UMA única vez para data/geo/estados_br.geojson e,
    nas execuções seguintes, lido do disco (cache), sem novo download a
    cada atualização do Streamlit.

Execução (a partir da raiz do projeto, com o Python do venv):
    .venv\\Scripts\\python -m streamlit run app/dashboard/main.py
"""

import json
import urllib.request
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import psycopg
import streamlit as st

import database

st.set_page_config(
    page_title="DataLab — Análise Territorial do Brasil",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

RAIZ_PROJETO = Path(__file__).resolve().parents[2]
CAMINHO_GEOJSON = RAIZ_PROJETO / "data" / "geo" / "estados_br.geojson"
URL_GEOJSON_IBGE = (
    "https://servicodados.ibge.gov.br/api/v3/malhas/paises/BR"
    "?formato=application/vnd.geo+json&qualidade=intermediaria&intrarregiao=UF"
)

# Códigos oficiais das UFs (IBGE), usados para casar a base com o GeoJSON
# (properties.codarea). Informação oficial e estável — nada foi inventado.
SIGLA_UF_POR_CODIGO_IBGE = {
    "11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA", "16": "AP",
    "17": "TO", "21": "MA", "22": "PI", "23": "CE", "24": "RN", "25": "PB",
    "26": "PE", "27": "AL", "28": "SE", "29": "BA", "31": "MG", "32": "ES",
    "33": "RJ", "35": "SP", "41": "PR", "42": "SC", "43": "RS", "50": "MS",
    "51": "MT", "52": "GO", "53": "DF",
}
CODIGO_UF_POR_SIGLA = {v: k for k, v in SIGLA_UF_POR_CODIGO_IBGE.items()}

MODOS_VISUALIZACAO = [
    "Visão geral",
    "Análise por estados",
    "Análise por regiões",
    "Análise por municípios",
]

# Estilos visuais: cada tema altera de verdade o fundo, as cores das barras,
# a rosca e a escala de cores do mapa.
TEMAS = {
    "Minimalista": {
        "fundo": "#ffffff",
        "texto": "#33506b",
        "grade": "#e6ebf2",
        "borda_mapa": "#ffffff",
        "escala_mapa": ["#e9f1f9", "#c6d9ec", "#8fb3d1", "#4f7fa8", "#234f78"],
        "cor_barra": "#5f8fb8",
        "cores_rosca": ["#5f8fb8", "#8fb3d1", "#b9cbe0", "#3f6f9c", "#d4e1ee"],
        "template": "plotly_white",
    },
    "Analítico": {
        "fundo": "#fbfcfd",
        "texto": "#3d3d3d",
        "grade": "#e8e8e8",
        "borda_mapa": "#fbfcfd",
        "escala_mapa": "YlOrRd",
        "cor_barra": "#c0552f",
        "cores_rosca": ["#f6d3a1", "#edab5d", "#e07b33", "#c0552f", "#8c3018"],
        "template": "plotly",
    },
    "Dark/tecnológico": {
        "fundo": "#0e1117",
        "texto": "#e8eaed",
        "grade": "#2b313b",
        "borda_mapa": "rgba(255,255,255,0.35)",
        "escala_mapa": "Viridis",
        "cor_barra": "#57d9e0",
        "cores_rosca": ["#57d9e0", "#7f7fff", "#ffd166", "#ff7eb6", "#9ef01a"],
        "template": "plotly_dark",
    },
}


# ---------------------------------------------------------------------------
# Acesso aos dados (cache do Streamlit — evita consultas repetidas)
# ---------------------------------------------------------------------------

@st.cache_data(ttl=600, show_spinner="Consultando o banco de dados...")
def carregar_indicadores() -> dict:
    return database.indicadores_gerais()


@st.cache_data(ttl=600, show_spinner=False)
def carregar_distritos_por_uf() -> pd.DataFrame:
    return database.distritos_por_uf()


@st.cache_data(ttl=600, show_spinner=False)
def carregar_distritos_por_regiao() -> pd.DataFrame:
    return database.distritos_por_regiao()


@st.cache_data(ttl=600, show_spinner=False)
def carregar_top_municipios() -> pd.DataFrame:
    return database.top_municipios_mais_distritos(10)


def _corrigir_sentido_dos_anis(geojson: dict) -> dict:
    """Inverte a ordem dos vértices dos anéis para o padrão do d3-geo.

    O GeoJSON do IBGE vem no padrão RFC 7946 (anéis externos no sentido
    anti-horário). O motor de mapas do Plotly usa d3-geo, que no modelo
    esférico espera anéis externos horários; anel anti-horário é
    interpretado como 'a esfera inteira menos o polígono' — na tela, a
    janela do mapa sai completamente preenchida pela última UF desenhada
    (tela roxa no tema escuro, quase branca nos temas claros).

    Reordenar os vértices NÃO altera a geometria: as mesmas coordenadas
    e o mesmo território são preservados — é apenas semântica de
    preenchimento para o renderizador. O arquivo em disco permanece
    intacto, como veio do IBGE; a correção é feita na cópia em memória.
    """
    for feature in geojson["features"]:
        geometria = feature["geometry"]
        if geometria["type"] == "Polygon":
            geometria["coordinates"] = [anel[::-1] for anel in geometria["coordinates"]]
        elif geometria["type"] == "MultiPolygon":
            geometria["coordinates"] = [
                [anel[::-1] for anel in poligono] for poligono in geometria["coordinates"]
            ]
    return geojson


@st.cache_data(show_spinner="Baixando os limites territoriais do IBGE...")
def carregar_geojson() -> dict:
    """Lê a malha das 27 UFs do disco ou, na primeira execução, baixa do
    IBGE e salva em data/geo/estados_br.geojson."""
    if CAMINHO_GEOJSON.is_file():
        with open(CAMINHO_GEOJSON, encoding="utf-8") as arquivo:
            dados = json.load(arquivo)
    else:
        CAMINHO_GEOJSON.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(URL_GEOJSON_IBGE, timeout=120) as resposta:
            dados = json.loads(resposta.read().decode("utf-8"))
        with open(CAMINHO_GEOJSON, "w", encoding="utf-8") as arquivo:
            json.dump(dados, arquivo, ensure_ascii=False)
    return _corrigir_sentido_dos_anis(dados)


# ---------------------------------------------------------------------------
# Construção das figuras (Plotly)
# ---------------------------------------------------------------------------

def formatar_numero(valor: int) -> str:
    """Formata inteiros no padrão brasileiro (10751 -> '10.751')."""
    return f"{valor:,}".replace(",", ".")


def _estilo_geral(figura: go.Figure, tema: dict) -> go.Figure:
    """Aplica o tema (fundo, texto, separadores de milhar) a uma figura."""
    figura.update_layout(
        template=tema["template"],
        paper_bgcolor=tema["fundo"],
        font_color=tema["texto"],
        separators=",.",
        margin=dict(l=10, r=10, t=20, b=10),
    )
    return figura


def _calcular_bounds_do_geojson(geojson: dict) -> dict:
    """Limites reais do território a partir das coordenadas do GeoJSON.

    Devolve lon_min, lon_max, lat_min e lat_max. Os limites saem das
    próprias coordenadas do arquivo do IBGE ([lon, lat]), sem nenhum valor
    inventado — é o que define o enquadramento do mapa.
    """
    lons, lats = [], []
    for feature in geojson["features"]:
        geometria = feature["geometry"]
        coordenadas = geometria["coordinates"]
        poligonos = [coordenadas] if geometria["type"] == "Polygon" else coordenadas
        for poligono in poligonos:
            for anel in poligono:
                for lon, lat in anel:
                    lons.append(lon)
                    lats.append(lat)
    return {
        "lon_min": min(lons),
        "lon_max": max(lons),
        "lat_min": min(lats),
        "lat_max": max(lats),
    }


def construir_mapa(df_uf: pd.DataFrame, geojson: dict, tema: dict) -> go.Figure:
    """Mapa coroplético: cada UF colorida pela quantidade de distritos.

    O enquadramento usa projeção Mercator explícita com os limites reais
    calculados do GeoJSON — não depende de fitbounds, que falha no
    plotly.js embarcado no Streamlit (mapa aparecia minúsculo no canto).
    """
    df = df_uf.copy()
    df["codigo_uf"] = df["uf_sigla"].map(CODIGO_UF_POR_SIGLA)

    figura = px.choropleth(
        df,
        geojson=geojson,
        featureidkey="properties.codarea",
        locations="codigo_uf",
        color="distritos",
        color_continuous_scale=tema["escala_mapa"],
        range_color=(0, int(df["distritos"].max())),
        hover_name="uf_nome",
        hover_data={"uf_sigla": True, "distritos": ":,d"},
        labels={"uf_sigla": "UF", "uf_nome": "Estado", "distritos": "Distritos"},
    )
    figura.update_traces(marker_line_color=tema["borda_mapa"], marker_line_width=0.6)

    bounds = _calcular_bounds_do_geojson(geojson)
    margem_lon = (bounds["lon_max"] - bounds["lon_min"]) * 0.05
    margem_lat = (bounds["lat_max"] - bounds["lat_min"]) * 0.05
    figura.update_geos(
        projection_type="mercator",
        center=dict(
            lat=(bounds["lat_min"] + bounds["lat_max"]) / 2,
            lon=(bounds["lon_min"] + bounds["lon_max"]) / 2,
        ),
        lonaxis_range=[bounds["lon_min"] - margem_lon, bounds["lon_max"] + margem_lon],
        lataxis_range=[bounds["lat_min"] - margem_lat, bounds["lat_max"] + margem_lat],
        bgcolor=tema["fundo"],
        visible=False,
        showframe=False,
        showcoastlines=False,
        showcountries=False,
        showland=False,
    )
    figura = _estilo_geral(figura, tema)
    figura.update_layout(
        coloraxis_colorbar=dict(title="Distritos", outlinewidth=0),
        height=560,
        margin=dict(l=0, r=0, t=5, b=0),
    )
    return figura


def construir_barras_uf(df_uf: pd.DataFrame, tema: dict, horizontal: bool) -> go.Figure:
    """Barras de distritos por UF — vertical (visão geral) ou ranking."""
    if horizontal:
        df = df_uf.sort_values("distritos", ascending=True)  # maior no topo
        figura = px.bar(
            df, x="distritos", y="uf_sigla", orientation="h",
            hover_name="uf_nome",
            labels={"distritos": "Distritos", "uf_sigla": "UF"},
            color_discrete_sequence=[tema["cor_barra"]],
        )
        altura = 560
    else:
        df = df_uf.sort_values("distritos", ascending=False)
        figura = px.bar(
            df, x="uf_sigla", y="distritos",
            hover_name="uf_nome",
            labels={"distritos": "Distritos", "uf_sigla": "UF"},
            color_discrete_sequence=[tema["cor_barra"]],
        )
        altura = 460
    figura = _estilo_geral(figura, tema)
    figura.update_layout(
        plot_bgcolor=tema["fundo"],
        yaxis=dict(gridcolor=tema["grade"]),
        xaxis=dict(gridcolor=tema["grade"]),
        height=altura,
        margin=dict(l=0, r=0, t=5, b=0),
    )
    return figura


def construir_rosca(df_regiao: pd.DataFrame, tema: dict) -> go.Figure:
    """Rosca com a participação de cada região no total de distritos."""
    figura = px.pie(
        df_regiao,
        names="regiao_nome",
        values="distritos",
        hole=0.5,
        color_discrete_sequence=tema["cores_rosca"],
    )
    figura.update_traces(
        textinfo="label+percent",
        hovertemplate="%{label}<br>%{value:,} distritos (%{percent})",
        marker=dict(line=dict(color=tema["fundo"], width=2)),
    )
    figura = _estilo_geral(figura, tema)
    figura.update_layout(height=460, margin=dict(l=0, r=0, t=5, b=0))
    return figura


def construir_top_municipios(df_top: pd.DataFrame, tema: dict) -> go.Figure:
    """Ranking horizontal dos 10 municípios com mais distritos."""
    df = df_top.sort_values("distritos", ascending=True)  # maior no topo
    figura = px.bar(
        df, x="distritos", y="municipio_nome", orientation="h",
        hover_data={"uf_sigla": True},
        labels={"distritos": "Distritos", "municipio_nome": "Município", "uf_sigla": "UF"},
        color_discrete_sequence=[tema["cor_barra"]],
    )
    figura = _estilo_geral(figura, tema)
    figura.update_layout(
        plot_bgcolor=tema["fundo"],
        yaxis=dict(gridcolor=tema["grade"]),
        xaxis=dict(gridcolor=tema["grade"]),
        height=520,
        margin=dict(l=0, r=0, t=5, b=0),
    )
    return figura


# ---------------------------------------------------------------------------
# Exibição do mapa com checagem honesta de cobertura
# ---------------------------------------------------------------------------

def exibir_mapa(df_uf: pd.DataFrame, geojson: dict, tema: dict) -> None:
    """Desenha o mapa. Nunca descarta dados em silêncio: UFs da base sem
    polígono e distritos sem UF identificada geram avisos explícitos."""
    if geojson is None:
        st.warning(
            "Mapa indisponível: não foi possível carregar a malha dos "
            "estados (IBGE). Os gráficos continuam disponíveis."
        )
        return

    siglas_geo = {
        SIGLA_UF_POR_CODIGO_IBGE.get(str(f["properties"].get("codarea")))
        for f in geojson["features"]
    }
    siglas_dados = set(df_uf["uf_sigla"].dropna())
    total_distritos = int(df_uf["distritos"].sum())

    fora_do_mapa = siglas_dados - siglas_geo
    if fora_do_mapa:
        distritos_fora = int(
            df_uf.loc[df_uf["uf_sigla"].isin(fora_do_mapa), "distritos"].sum()
        )
        st.warning(
            f"{len(fora_do_mapa)} UF(s) dos dados sem polígono no mapa: "
            f"{', '.join(sorted(map(str, fora_do_mapa)))} — "
            f"{formatar_numero(distritos_fora)} distrito(s) ficam fora do mapa."
        )

    sem_uf = df_uf["uf_sigla"].isna()
    if sem_uf.any():
        st.warning(
            f"{formatar_numero(int(df_uf.loc[sem_uf, 'distritos'].sum()))} "
            "distrito(s) sem UF identificada não entram no mapa."
        )

    df_mapa = df_uf[~sem_uf].copy()
    figura = construir_mapa(df_mapa, geojson, tema)
    st.plotly_chart(figura, width="stretch")

    cobertas = siglas_dados & siglas_geo
    st.caption(
        f"Cobertura do mapa: {len(cobertas)} de {len(siglas_dados)} UFs "
        f"com dados e {formatar_numero(total_distritos)} distritos no total."
    )


# ---------------------------------------------------------------------------
# Página
# ---------------------------------------------------------------------------

st.title("DataLab — Análise Territorial do Brasil")

st.write(
    "Bem-vindo(a)! Painel interativo dos distritos brasileiros do IBGE. "
    "Escolha o modo de visualização e o estilo do mapa na barra lateral."
)

with st.sidebar:
    st.header("Controles")
    modo = st.radio("Modo de visualização", MODOS_VISUALIZACAO, key="modo")
    estilo = st.radio("Estilo visual do mapa", list(TEMAS), key="estilo")

try:
    indicadores = carregar_indicadores()
    df_uf = carregar_distritos_por_uf()
    df_regiao = carregar_distritos_por_regiao()
    df_top10 = carregar_top_municipios()
except psycopg.Error:
    st.error(
        "Não foi possível conectar ao banco de dados. "
        "Verifique se o PostgreSQL está em execução "
        "(`docker compose up -d`) e tente novamente."
    )
    st.stop()

try:
    geojson = carregar_geojson()
except Exception as erro:
    st.error(
        "Não foi possível carregar a malha dos estados (IBGE). "
        f"Detalhe: {erro}"
    )
    geojson = None

tema = TEMAS[estilo]

if modo == "Visão geral":
    st.subheader("Indicadores gerais")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total de distritos", formatar_numero(indicadores["total_distritos"]))
    c2.metric("Total de municípios", formatar_numero(indicadores["total_municipios"]))
    c3.metric("Total de UFs", formatar_numero(indicadores["total_ufs"]))
    c4.metric("Total de regiões", formatar_numero(indicadores["total_regioes"]))

    esquerda, direita = st.columns([3, 2])
    with esquerda:
        st.subheader("Mapa — distritos por UF")
        exibir_mapa(df_uf, geojson, tema)
    with direita:
        st.subheader("Distritos por estado")
        st.plotly_chart(construir_barras_uf(df_uf, tema, horizontal=False), width="stretch")

elif modo == "Análise por estados":
    esquerda, direita = st.columns([3, 2])
    with esquerda:
        st.subheader("Mapa — distritos por UF")
        exibir_mapa(df_uf, geojson, tema)
    with direita:
        st.subheader("Ranking de estados")
        st.plotly_chart(construir_barras_uf(df_uf, tema, horizontal=True), width="stretch")

elif modo == "Análise por regiões":
    esquerda, direita = st.columns([3, 2])
    with esquerda:
        st.subheader("Mapa — distritos por UF")
        exibir_mapa(df_uf, geojson, tema)
    with direita:
        st.subheader("Distribuição regional")
        st.plotly_chart(construir_rosca(df_regiao, tema), width="stretch")

elif modo == "Análise por municípios":
    esquerda, direita = st.columns([3, 2])
    with esquerda:
        st.subheader("Mapa — distritos por UF")
        exibir_mapa(df_uf, geojson, tema)
    with direita:
        st.subheader("Top 10 municípios com mais distritos")
        st.plotly_chart(construir_top_municipios(df_top10, tema), width="stretch")

st.caption("Fonte dos dados: IBGE — cadastro de distritos e malha territorial.")
