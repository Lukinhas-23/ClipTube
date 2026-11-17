"""
twitch.py
---------
Regras específicas da Twitch (sem nada de interface):

  * reconhecer links de GRAVAÇÃO (VOD: twitch.tv/videos/123...) e de CLIP;
  * recusar links de canal (a live) e de listas de vídeos com uma explicação, para o
    app nunca tentar baixar um canal inteiro sem querer;
  * traduzir os erros típicos para português.

O download em si é feito pelo yt-dlp (veja downloader.py).
"""

import re

_DOMINIO = r"^https?://(?:[a-z0-9-]+\.)?twitch\.tv"

# Qualquer link da Twitch
_REGEX_TWITCH = re.compile(_DOMINIO + r"(?:/|$)", re.I)
# Gravação da live (VOD): twitch.tv/videos/123456  ou  twitch.tv/canal/v/123456
_REGEX_VOD = re.compile(_DOMINIO + r"/(?:[A-Za-z0-9_]+/)?(?:videos?|v)/\d+", re.I)
# Clip: clips.twitch.tv/NomeDoClip  ou  twitch.tv/canal/clip/NomeDoClip
_REGEX_CLIP = re.compile(
    r"^https?://(?:clips\.twitch\.tv/[\w-]+|(?:[a-z0-9-]+\.)?twitch\.tv/[A-Za-z0-9_]+/clip/[\w-]+)", re.I)
# Canal puro: twitch.tv/nomedocanal (é a live; não é um vídeo)
_REGEX_CANAL = re.compile(_DOMINIO + r"/[A-Za-z0-9_]+/?(?:[?#].*)?$", re.I)


def eh_twitch(url):
    """Qualquer link da Twitch (vídeo, clip, canal, lista...)."""
    return bool(_REGEX_TWITCH.match((url or "").strip()))


def eh_clip_twitch(url):
    return bool(_REGEX_CLIP.match((url or "").strip()))


def eh_vod_twitch(url):
    return bool(_REGEX_VOD.match((url or "").strip()))


def eh_video_twitch(url):
    """Link de UMA gravação ou de UM clip (o que sabemos baixar)."""
    return eh_vod_twitch(url) or eh_clip_twitch(url)


def mensagem_link_invalido_twitch(url):
    """Explica por que um link da Twitch que não é de vídeo não serve."""
    if _REGEX_CANAL.match((url or "").strip()):
        return ("Esse é o link do canal (a live). Para baixar a live inteira use a GRAVAÇÃO: "
                "abra twitch.tv/NOME_DO_CANAL/videos, clique na gravação e cole o link dela "
                "(twitch.tv/videos/...). A gravação já aparece lá enquanto a live ainda está no ar.")
    return ("Esse link é de uma lista ou página da Twitch. Cole o link de UM vídeo "
            "(twitch.tv/videos/...) ou de UM clip.")


_REGRAS_ERRO = [
    (("subscriber", "subscribers-only", "sub-only", "subscription"),
     "Essa gravação é só para assinantes do canal. O ClipTube ainda não entra com login na Twitch."),
    (("does not exist", "not found", "404", "has been deleted", "no longer available",
      "unavailable", "is not available"),
     "Não encontrei esse vídeo: o link está errado ou a gravação foi apagada "
     "(a Twitch apaga as gravações depois de alguns dias)."),
    (("mature", "18+", "age"),
     "Esse vídeo é para maiores de 18 anos e exige login na Twitch."),
]


def traduzir_erro_twitch(texto):
    """Frase simples para um erro do yt-dlp na Twitch, ou None se não reconhecer."""
    t = (texto or "").lower()
    for trechos, frase in _REGRAS_ERRO:
        if any(x in t for x in trechos):
            return frase
    return None
