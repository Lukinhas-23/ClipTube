"""
instagram.py
------------
Regras específicas do Instagram (sem nada de interface):

  * reconhecer links de post, reel, igtv e story;
  * escolher o "login" (o Instagram quase sempre exige conta logada): usamos os
    cookies de um navegador onde você já está logado, ou um arquivo cookies.txt.
    O ClipTube NUNCA vê nem guarda a senha: só entrega os cookies ao yt-dlp /
    gallery-dl, na hora de baixar;
  * traduzir os erros típicos para português;
  * ler a resposta do gallery-dl (usado para FOTOS e posts com várias mídias).

Vídeos e reels: baixados pelo yt-dlp. Fotos e carrosséis: gallery-dl.
"""

import json
import os
import re

# Post (/p/), reel (/reel/ ou /reels/), IGTV (/tv/) e story (/stories/).
# Aceita também o formato com nome de usuário: instagram.com/fulano/p/XXXX/
_REGEX_INSTAGRAM = re.compile(
    r"^https?://(?:[a-z0-9-]+\.)?(?:instagram\.com|instagr\.am)/", re.I)
_REGEX_POST = re.compile(
    r"^https?://(?:[a-z0-9-]+\.)?(?:instagram\.com|instagr\.am)/"
    r"(?:[A-Za-z0-9_.]+/)?(?:p|reel|reels|tv|stories)/", re.I)

# Opções do menu "Login": texto na tela -> modo guardado na configuração
OPCOES_LOGIN = [
    ("Chrome (onde estou logado)", "chrome"),
    ("Edge (onde estou logado)", "edge"),
    ("Firefox (onde estou logado)", "firefox"),
    ("Arquivo cookies.txt...", "arquivo"),
    ("Sem login", "nenhum"),
]
NOMES_NAVEGADOR = {"chrome": "Chrome", "edge": "Edge", "firefox": "Firefox"}
# Começa SEM login: o app só lê os cookies de um navegador depois que você escolher.
LOGIN_PADRAO = {"modo": "nenhum", "arquivo": ""}


def eh_instagram(url):
    """Qualquer link do Instagram (mesmo que não seja de um post)."""
    return bool(_REGEX_INSTAGRAM.match((url or "").strip()))


def eh_post_instagram(url):
    """Link de post, reel, IGTV ou story (o que sabemos baixar)."""
    return bool(_REGEX_POST.match((url or "").strip()))


def texto_do_login(login):
    """Texto do menu para o login atual."""
    modo = (login or {}).get("modo", "nenhum")
    if modo == "arquivo":
        nome = os.path.basename((login or {}).get("arquivo") or "") or "cookies.txt"
        return f"Arquivo: {nome}"
    for texto, valor in OPCOES_LOGIN:
        if valor == modo:
            return texto
    return OPCOES_LOGIN[-1][0]


def argumentos_login(login):
    """Argumentos de cookies para o yt-dlp e o gallery-dl (os dois usam os mesmos)."""
    modo = (login or {}).get("modo", "nenhum")
    if modo in NOMES_NAVEGADOR:
        return ["--cookies-from-browser", modo]
    if modo == "arquivo":
        arquivo = (login or {}).get("arquivo") or ""
        if os.path.isfile(arquivo):
            return ["--cookies", arquivo]
    return []


def _nome_login(login):
    modo = (login or {}).get("modo", "nenhum")
    return NOMES_NAVEGADOR.get(modo, "o arquivo de cookies")


# ---------------------------------------------------------------------------
# Tradução de erros
# ---------------------------------------------------------------------------
_TRECHOS_LOGIN = ("empty media response", "login required", "log in", "login page",
                  "redirect to login", "rate-limit reached", "checkpoint_required",
                  "requires login", "not logged in", "401", "this content is not available")
_TRECHOS_COOKIES = ("cookie database", "cookies database", "dpapi", "failed to decrypt",
                    "cannot decrypt", "failed to load cookies", "failed to read cookies",
                    "could not find chrome", "could not find edge", "could not find firefox")
_TRECHOS_SEM_VIDEO = ("there is no video in this post", "no video formats found",
                      "no video in this post", "unsupported url")
_TRECHOS_PRIVADO = ("private", "not authorized", "you must be following", "follow this account")
_TRECHOS_NAO_EXISTE = ("404", "not found", "does not exist", "page isn't available", "no longer available")


def precisa_gallerydl(texto):
    """O erro do yt-dlp indica um post sem vídeo (fotos)? Então o gallery-dl resolve."""
    t = (texto or "").lower()
    return any(x in t for x in _TRECHOS_SEM_VIDEO)


def erro_de_cookies(texto):
    t = (texto or "").lower()
    return any(x in t for x in _TRECHOS_COOKIES)


def erro_de_login(texto):
    t = (texto or "").lower()
    return any(x in t for x in _TRECHOS_LOGIN)


def traduzir_erro_instagram(texto, login=None):
    """Devolve uma frase simples para um erro do yt-dlp/gallery-dl no Instagram,
    ou None se não reconhecer (aí vale a tradução geral)."""
    t = (texto or "").lower()
    modo = (login or {}).get("modo", "nenhum")
    if erro_de_cookies(t):
        nome = _nome_login(login)
        return (f"Não consegui ler o login do {nome}. Feche o navegador e tente de novo. "
                "Se continuar, use o Firefox ou escolha 'Arquivo cookies.txt...' no menu Login.")
    if any(x in t for x in _TRECHOS_PRIVADO):
        return ("Esse post é de uma conta privada. Só dá para baixar se a conta que está logada "
                "no navegador seguir esse perfil.")
    if erro_de_login(t):
        if modo == "nenhum":
            return ("O Instagram exige login para esse post. Escolha no menu Login o navegador "
                    "onde você está logado no Instagram (ou um arquivo cookies.txt).")
        if modo == "arquivo":
            return ("O Instagram recusou o login do arquivo cookies.txt. Confira se ele foi "
                    "exportado de uma conta logada no Instagram e se não está vencido (exporte de novo).")
        return (f"O Instagram recusou mesmo com o login. Confira se você está logado no Instagram "
                f"no {_nome_login(login)}, abra o post lá para ver se ele abre e tente de novo.")
    if any(x in t for x in _TRECHOS_NAO_EXISTE):
        return "Post não encontrado: o link está errado ou o post foi apagado."
    return None


# ---------------------------------------------------------------------------
# Resposta do gallery-dl (-j): lista de [tipo, ...]
#   tipo 2 = pasta/metadados do post   tipo 3 = arquivo (url, metadados)   tipo -1 = erro
# ---------------------------------------------------------------------------
def ler_json_gallerydl(texto):
    """Lê a saída `gallery-dl -j`. Retorna (info, erro).

    info = {"titulo","canal","fotos","videos","miniatura"} ou None; erro = texto ou None.
    """
    try:
        dados = json.loads(texto)
    except (ValueError, TypeError):
        return None, "resposta inválida do gallery-dl"
    meta_post, arquivos, erro = {}, [], None
    for item in dados if isinstance(dados, list) else []:
        if not item:
            continue
        tipo = item[0]
        if tipo == 2 and len(item) > 1 and isinstance(item[1], dict):
            meta_post = {**meta_post, **item[1]}
        elif tipo == 3 and len(item) > 2:
            arquivos.append((item[1], item[2] if isinstance(item[2], dict) else {}))
        elif tipo == -1:
            detalhe = item[1] if len(item) > 1 and isinstance(item[1], dict) else {}
            erro = f"{detalhe.get('error', '')} {detalhe.get('message', '')}".strip() or "erro"
    if not arquivos:
        return None, erro or "nenhuma foto ou vídeo encontrado"

    def eh_video(meta):
        return str(meta.get("extension", "")).lower() in ("mp4", "mov", "webm", "m4v")

    videos = sum(1 for _, m in arquivos if eh_video(m))
    fotos = len(arquivos) - videos
    primeiro_url, primeiro_meta = arquivos[0]
    miniatura = None
    if not eh_video(primeiro_meta):
        miniatura = primeiro_url
    else:
        miniatura = primeiro_meta.get("display_url") or primeiro_meta.get("thumbnail")
    usuario = meta_post.get("username") or (meta_post.get("owner") or {}).get("username") \
        or primeiro_meta.get("username") or ""
    legenda = (meta_post.get("description") or primeiro_meta.get("description") or "").strip()
    primeira_linha = legenda.splitlines()[0].strip() if legenda else ""
    titulo = primeira_linha[:90] or (f"Post de @{usuario}" if usuario else "Post do Instagram")
    return {"titulo": titulo, "canal": f"@{usuario}" if usuario else "", "fotos": fotos,
            "videos": videos, "miniatura": miniatura}, None


def descricao_midia(fotos, videos):
    """"3 fotos", "1 vídeo", "2 fotos e 1 vídeo"."""
    partes = []
    if fotos:
        partes.append(f"{fotos} foto" + ("s" if fotos != 1 else ""))
    if videos:
        partes.append(f"{videos} vídeo" + ("s" if videos != 1 else ""))
    return " e ".join(partes) or "mídia"
