"""
downloader.py
-------------
Toda a parte de "conversar" com o yt-dlp fica aqui, separada da interface.

Usamos o executável do yt-dlp já instalado pelo winget (o mesmo que você usa
no terminal). O app salva SEMPRE em MP4 com vídeo H.264 + áudio AAC, o
formato que abre em qualquer lugar (veja FORMATO logo abaixo).

E, quando você atualizar o yt-dlp com `winget upgrade yt-dlp`, o app também
passa a usar a versão nova automaticamente (sem precisar recompilar o .exe).
O FFmpeg instalado é encontrado pelo próprio yt-dlp para juntar vídeo + áudio.
"""

import functools
import json
import re
import os
import platform
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from io import BytesIO

import instagram
import twitch
from preparo import (comando_gallerydl, comando_ytdlp, localizar_ferramenta, localizar_winget)
from previas import extrair_dados_previa

# Formato: melhor vídeo + melhor áudio, juntados em MP4.
FORMATO = "bv*+ba/b"


def ordenacao(limite_res=None):
    """Monta a ordem de preferência (-S) do yt-dlp.

    limite_res = None  -> maior resolução que o vídeo tiver (4K, 8K...)
    limite_res = 1080  -> maior resolução até 1080p

    Depois da resolução, prefere: mais quadros por segundo, SDR (cores normais),
    vídeo H.264 e áudio AAC (assim, quando existe versão H.264 na resolução
    escolhida, nem precisa converter) e, por fim, maior taxa de bits.

    O resultado final é SEMPRE MP4 H.264 + AAC, que abre em qualquer lugar:
    se a resolução escolhida só existir em VP9/AV1 (comum em 1440p e 4K), o app
    converte depois (método garantir_compativel).
    """
    res = f"res:{limite_res}" if limite_res else "res"
    return f"{res},fps,hdr:sdr,vcodec:h264,acodec:aac,br"


# Nome amigável de cada resolução (pelo lado menor do vídeo, então vale também
# para vídeos em pé, como Shorts).
NOMES_RESOLUCAO = {4320: "8K", 2160: "4K", 1440: "2K", 1080: "Full HD", 720: "HD"}


def nome_resolucao(res):
    apelido = NOMES_RESOLUCAO.get(res)
    return f"{res}p ({apelido})" if apelido else f"{res}p"

# Impede que uma janela preta de terminal apareça ao chamar o yt-dlp.
SEM_JANELA = 0x08000000 if os.name == "nt" else 0

# Marcador que colocamos nas linhas de progresso para reconhecê-las facilmente.
MARCA_PROGRESSO = "##PROG##"


class ErroDownload(Exception):
    """Erro já traduzido para uma mensagem simples em português.

    `original` guarda o texto cru da ferramenta (yt-dlp/gallery-dl), para o app
    decidir o que fazer (ex.: tentar o gallery-dl quando o post só tem fotos).
    """

    def __init__(self, mensagem="", original=""):
        super().__init__(mensagem)
        self.original = original or mensagem


class Cancelado(Exception):
    """O usuário clicou em Cancelar."""


# ---------------------------------------------------------------------------
# Localização do yt-dlp
# ---------------------------------------------------------------------------
def localizar_ytdlp():
    """Comando para executar o yt-dlp: lista (versão em Python ou .exe) ou None."""
    return comando_ytdlp()


def _erro_sem_ytdlp():
    """Erro para quando não dá para executar o yt-dlp (não instalado, ou bloqueado)."""
    exe = localizar_ferramenta("yt-dlp")
    if exe:   # o .exe existe mas não executa: quase sempre é o Windows bloqueando
        return ErroDownload(MSG_BLOQUEIO_WINDOWS,
                            original=f"yt-dlp.exe existe em {exe}, mas não executa (WinError 4551?) "
                                     "e a versão em Python não está instalada.")
    return ErroDownload("yt-dlp não encontrado. Dê dois cliques em ClipTube.bat para instalar.")


@functools.lru_cache(maxsize=1)
def _ytdlp_aceita_js_runtimes(ytdlp):
    """O yt-dlp novo tem a opção --js-runtimes (versões antigas dão erro se ela existir).
    `ytdlp` é a tupla do comando (precisa ser hashable por causa do cache)."""
    try:
        r = subprocess.run([*ytdlp, "--help"], capture_output=True, timeout=30,
                           creationflags=SEM_JANELA)
        return b"--js-runtimes" in r.stdout
    except Exception:
        return False


def argumentos_js(ytdlp):
    """Diz ao yt-dlp onde está o Deno (interpretador de JavaScript que o YouTube exige),
    mesmo quando ele não está no PATH (acontece logo depois de instalar pelo winget)."""
    deno = localizar_ferramenta("deno")
    if deno and _ytdlp_aceita_js_runtimes(tuple(ytdlp)):
        return ["--js-runtimes", f"deno:{deno}"]
    return []


def info_ambiente():
    """Texto com versões e locais das ferramentas, para diagnosticar erros em outro PC."""
    def primeira_linha(comando):
        try:
            r = subprocess.run(comando, capture_output=True, timeout=20,
                               creationflags=SEM_JANELA, env=_ambiente_utf8())
            linhas = (r.stdout or r.stderr).decode("utf-8", errors="replace").strip().splitlines()
            return linhas[0][:110] if linhas else "(sem resposta)"
        except Exception as e:
            return f"ERRO ao executar: {e}"

    linhas = [f"Windows: {platform.platform()}",
              f"Python: {sys.version.split()[0]}  [{sys.executable}]"]
    # yt-dlp e gallery-dl: mostra o comando que o app realmente usa (versão em Python ou .exe)
    for nome, comando, exe in (("yt-dlp", comando_ytdlp(), localizar_ferramenta("yt-dlp")),
                               ("gallery-dl", comando_gallerydl(), localizar_ferramenta("gallery-dl"))):
        if comando:
            via = "versão em Python" if len(comando) > 1 else "programa .exe"
            linhas.append(f"{nome}: {primeira_linha([*comando, '--version'])}  [{via}]")
        elif exe:
            linhas.append(f"{nome}: NAO EXECUTA - [WinError 4551] bloqueado pelo Windows?  [{exe}]")
        else:
            linhas.append(f"{nome}: NAO ENCONTRADO")
    for nome, argumento in (("ffmpeg", "-version"), ("ffprobe", "-version"), ("deno", "--version")):
        caminho = localizar_ferramenta(nome)
        if caminho:
            linhas.append(f"{nome}: {primeira_linha([caminho, argumento])}  [{caminho}]")
        else:
            linhas.append(f"{nome}: NAO ENCONTRADO")
    winget = localizar_winget()
    linhas.append(f"winget: {primeira_linha([winget, '--version']) if winget else 'NAO ENCONTRADO'}")
    return "\n".join(linhas)


def _ambiente_utf8():
    """Faz o yt-dlp escrever a saída em UTF-8 (títulos com acento/emoji)."""
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


# ---------------------------------------------------------------------------
# Windows bloqueando um programa (Smart App Control / Controle de Aplicativo)
# ---------------------------------------------------------------------------
MSG_BLOQUEIO_WINDOWS = ("O Windows bloqueou um dos programas do ClipTube (erro 4551, política de "
                        "Controle de Aplicativo). Clique aqui para ver qual e como liberar.")

COMO_RESOLVER_BLOQUEIO = (
    "COMO RESOLVER: o Windows está bloqueando um programa.\n"
    "- Na seção \"Ambiente\" abaixo, o programa com [WinError 4551] é o que está bloqueado\n"
    "  (yt-dlp, ffmpeg, ffprobe, deno ou gallery-dl).\n"
    "- Se o computador é seu: abra Segurança do Windows > Controle de aplicativos e navegador >\n"
    "  Configurações do Controle inteligente de aplicativo e escolha \"Desativado\".\n"
    "  Atenção: depois de desativado, só dá para ligar de novo reinstalando o Windows.\n"
    "- Se o computador é da empresa ou da escola: a regra é do administrador (TI). Peça para\n"
    "  liberar esses programas.\n\n")


def eh_bloqueio_windows(erro):
    """O erro (exceção ou texto) é o Windows bloqueando um programa?"""
    if getattr(erro, "winerror", None) == 4551:
        return True
    texto = str(erro).lower()
    return any(x in texto for x in ("winerror 4551", "controle de aplicativo", "application control",
                                    "app control", "smart app control"))


# ---------------------------------------------------------------------------
# Tradução de erros
# ---------------------------------------------------------------------------
# Cada regra: (trechos que podem aparecer no erro do yt-dlp, mensagem amigável).
# A ordem importa: as mais específicas vêm primeiro.
_REGRAS_ERRO = [
    (("winerror 4551", "controle de aplicativo", "application control", "app control",
      "smart app control"), MSG_BLOQUEIO_WINDOWS),
    (("private video", "video is private"),
     "Este vídeo é privado. Só o dono do canal consegue assistir."),
    (("sign in to confirm your age", "age-restricted", "inappropriate for some users"),
     "Este vídeo tem restrição de idade e exige login no YouTube."),
    (("not a bot",),
     "O YouTube pediu uma verificação anti-robô. Espere um pouco e tente de novo, "
     "ou atualize o yt-dlp (winget upgrade yt-dlp)."),
    (("members-only", "join this channel"),
     "Este vídeo é exclusivo para membros do canal."),
    (("not available in your country", "geo restrict", "geo-restrict"),
     "Este vídeo está bloqueado no seu país."),
    (("live event will begin", "premieres in", "this live event"),
     "Esta transmissão ao vivo/estreia ainda não começou."),
    (("video unavailable", "video is unavailable", "has been removed", "this video is not available",
      "account associated with this video has been terminated", "copyright claim"),
     "Vídeo indisponível: ele foi removido ou não existe mais."),
    (("is not a valid url", "unsupported url", "incomplete youtube id",
      "invalid url", "no video formats found"),
     "Link inválido. Confira se você copiou o endereço completo do vídeo."),
    (("http error 403", "403: forbidden"),
     "O YouTube recusou o download (erro 403). Tente de novo em instantes "
     "ou atualize o yt-dlp (winget upgrade yt-dlp)."),
    (("requested format is not available",),
     "Não existe versão MP4 deste vídeo para baixar."),
    (("getaddrinfo", "failed to resolve", "name resolution", "nodename nor servname",
      "network is unreachable", "timed out", "connection refused",
      "connection reset", "urlopen error", "unable to download webpage",
      "no route to host", "temporary failure"),
     "Sem conexão com a internet (ou o YouTube não respondeu). "
     "Verifique sua rede e tente de novo."),
    (("ffmpeg not found", "ffprobe not found", "ffmpeg is not installed",
      "you have requested merging"),
     "FFmpeg não encontrado. Ele é necessário para juntar vídeo e áudio."),
    (("no space left", "errno 28"),
     "Sem espaço livre no disco da pasta de destino."),
    (("permission denied", "errno 13", "access is denied"),
     "Sem permissão para salvar na pasta escolhida. Tente outra pasta."),
]


def traduzir_erro(texto):
    """Recebe o texto de erro do yt-dlp e devolve uma frase simples."""
    minusculo = (texto or "").lower()
    for trechos, mensagem in _REGRAS_ERRO:
        if any(t in minusculo for t in trechos):
            return mensagem
    # Erro desconhecido: mostramos a última linha "ERROR:" de forma resumida.
    linhas = [l.strip() for l in (texto or "").splitlines() if l.strip()]
    erros = [l for l in linhas if l.startswith("ERROR:")]
    ultima = (erros or linhas or ["erro desconhecido"])[-1]
    ultima = ultima.replace("ERROR:", "").strip()
    if len(ultima) > 160:
        ultima = ultima[:157] + "..."
    return f"Não foi possível baixar: {ultima}"


def traduzir_erro_plataforma(texto, url, login=None):
    """Como traduzir_erro, mas com as mensagens específicas do Instagram quando for o caso."""
    if instagram.eh_instagram(url):
        frase = instagram.traduzir_erro_instagram(texto, login)
        if frase:
            return frase
    if twitch.eh_twitch(url):
        frase = twitch.traduzir_erro_twitch(texto)
        if frase:
            return frase
    return traduzir_erro(texto)


# ---------------------------------------------------------------------------
# Informações do vídeo (título, canal, duração, miniatura)
# ---------------------------------------------------------------------------
def obter_info(url, timeout=90, login=None):
    """Pergunta ao yt-dlp os dados do vídeo, sem baixar nada.

    Retorna um dicionário com: titulo, canal, duracao (segundos), miniatura (URL).
    `login` só vale para links do Instagram (veja instagram.py).
    """
    if instagram.eh_instagram(url):
        return obter_info_instagram(url, login, timeout)
    if twitch.eh_twitch(url) and not twitch.eh_video_twitch(url):
        raise ErroDownload(twitch.mensagem_link_invalido_twitch(url))
    ytdlp = localizar_ytdlp()
    if not ytdlp:
        raise _erro_sem_ytdlp()

    try:
        proc = subprocess.run(
            [*ytdlp, "-J", "--no-playlist", "--no-warnings", *argumentos_js(ytdlp), url],
            capture_output=True, timeout=timeout,
            creationflags=SEM_JANELA, env=_ambiente_utf8(),
        )
    except subprocess.TimeoutExpired:
        raise ErroDownload("O YouTube demorou demais para responder. Tente de novo.")

    saida = proc.stdout.decode("utf-8", errors="replace")
    erro = proc.stderr.decode("utf-8", errors="replace")
    if proc.returncode != 0 or not saida.strip():
        raise ErroDownload(traduzir_erro_plataforma(erro, url), original=erro)

    dados = json.loads(saida)
    info = {
        "titulo": dados.get("title") or "(sem título)",
        "canal": dados.get("uploader") or dados.get("channel") or "",
        "duracao": dados.get("duration"),
        "miniatura": dados.get("thumbnail"),
        "qualidades": listar_qualidades(dados),
        "previa": extrair_dados_previa(dados),     # miniaturas e links para o recorte de clip
    }
    if twitch.eh_twitch(url):
        info["plataforma"] = "twitch"
        info["tipo"] = "clip" if twitch.eh_clip_twitch(url) else "vod"
    return info


def obter_info_instagram(url, login=None, timeout=90):
    """Dados de um post/reel/story do Instagram.

    Primeiro tenta o yt-dlp (vídeos). Se o post não tiver vídeo (só fotos), usa o
    gallery-dl. Retorna o mesmo formato do obter_info, mais: plataforma="instagram",
    fotos e videos (quantidades).
    """
    if not instagram.eh_post_instagram(url):
        raise ErroDownload("Use o link de um post, reel ou story do Instagram "
                           "(perfis inteiros não são suportados).")
    ytdlp = localizar_ytdlp()
    if not ytdlp:
        raise _erro_sem_ytdlp()
    login_args = instagram.argumentos_login(login)

    try:
        proc = subprocess.run([*ytdlp, "-J", "--no-warnings", *argumentos_js(ytdlp), *login_args, url],
                              capture_output=True, timeout=timeout,
                              creationflags=SEM_JANELA, env=_ambiente_utf8())
    except subprocess.TimeoutExpired:
        raise ErroDownload("O Instagram demorou demais para responder. Tente de novo.")
    saida = proc.stdout.decode("utf-8", errors="replace")
    erro = proc.stderr.decode("utf-8", errors="replace")

    if proc.returncode == 0 and saida.strip():
        dados = json.loads(saida)
        entradas = [e for e in (dados.get("entries") or []) if e]
        primeiro = entradas[0] if entradas else dados
        legenda = (dados.get("description") or primeiro.get("description") or "").strip()
        usuario = primeiro.get("uploader_id") or primeiro.get("uploader") or ""
        titulo = (legenda.splitlines()[0].strip()[:90] if legenda else "") \
            or dados.get("title") or "Vídeo do Instagram"
        return {
            "titulo": titulo,
            "canal": f"@{usuario}" if usuario else "",
            "duracao": None if entradas else dados.get("duration"),
            "miniatura": primeiro.get("thumbnail") or dados.get("thumbnail"),
            "qualidades": [],
            "previa": {"storyboards": [], "stream": None},
            "plataforma": "instagram",
            "fotos": 0,
            "videos": len(entradas) or 1,
        }

    # O yt-dlp não conseguiu. Cookies com problema ou internet fora: o gallery-dl não ajuda.
    if instagram.erro_de_cookies(erro) or traduzir_erro(erro).startswith("Sem conexão"):
        raise ErroDownload(traduzir_erro_plataforma(erro, url, login), original=erro)

    gallerydl = comando_gallerydl()
    if not gallerydl:
        if instagram.precisa_gallerydl(erro):
            raise ErroDownload("Esse post parece ter só fotos e isso precisa do gallery-dl. "
                               "Instale com: python -m pip install gallery-dl", original=erro)
        raise ErroDownload(traduzir_erro_plataforma(erro, url, login), original=erro)

    try:
        proc2 = subprocess.run([*gallerydl, "-j", "--no-colors", *login_args, url],
                               capture_output=True, timeout=timeout,
                               creationflags=SEM_JANELA, env=_ambiente_utf8())
    except subprocess.TimeoutExpired:
        raise ErroDownload("O Instagram demorou demais para responder. Tente de novo.")
    info, erro_gd = instagram.ler_json_gallerydl(proc2.stdout.decode("utf-8", errors="replace"))
    if info is None:
        completo = f"{erro} {erro_gd or ''} {proc2.stderr.decode('utf-8', errors='replace')}"
        raise ErroDownload(traduzir_erro_plataforma(completo, url, login), original=completo)
    return {
        "titulo": info["titulo"],
        "canal": info["canal"],
        "duracao": None,
        "miniatura": info["miniatura"],
        "qualidades": [],
        "previa": {"storyboards": [], "stream": None},
        "plataforma": "instagram",
        "fotos": info["fotos"],
        "videos": info["videos"],
    }


def _fps_comum(fps):
    """Arredonda para o fps "de nome": 59.494 -> 60, 29.97 -> 30, 23.976 -> 24."""
    fps = float(fps or 0)
    for comum in (24, 25, 30, 48, 50, 60):
        if abs(fps - comum) < 1:
            return comum
    return round(fps)


def listar_qualidades(dados):
    """Lista as resoluções disponíveis do vídeo, da maior para a menor.

    Cada item: {"res": 1080, "fps": 60, "h264": True, "tamanho": bytes aprox.}
    "h264" = já existe versão H.264 nessa resolução (não precisa converter).
    """
    duracao = dados.get("duration") or 0
    # tamanho aproximado do melhor áudio (somado ao do vídeo)
    audio = 0
    for f in dados.get("formats") or []:
        if f.get("vcodec") in (None, "none") and f.get("acodec") not in (None, "none"):
            audio = max(audio, f.get("filesize") or f.get("filesize_approx") or 0)

    por_res = {}
    for f in dados.get("formats") or []:
        vcodec = f.get("vcodec")
        if vcodec == "none":
            continue  # só áudio ou imagens de prévia
        # Alguns sites (ex.: clips da Twitch) não informam codec nem largura, só a altura.
        largura, altura = f.get("width"), f.get("height")
        if not altura:
            continue
        res = min(largura, altura) if largura else altura
        if res < 144:
            continue
        q = por_res.setdefault(res, {"res": res, "fps": 0, "h264": False, "tamanho": 0})
        q["fps"] = max(q["fps"], _fps_comum(f.get("fps")))
        if (vcodec or "").startswith("avc1") or (not vcodec and f.get("ext") == "mp4"):
            q["h264"] = True
        tamanho = f.get("filesize") or f.get("filesize_approx")
        if not tamanho and f.get("tbr") and duracao:
            tamanho = f["tbr"] * 1000 / 8 * duracao
        q["tamanho"] = max(q["tamanho"], int(tamanho or 0))

    qualidades = sorted(por_res.values(), key=lambda q: q["res"], reverse=True)
    for q in qualidades:
        if q["tamanho"]:
            q["tamanho"] += audio
    return qualidades


def baixar_miniatura(url_imagem, timeout=15):
    """Baixa a imagem da miniatura e devolve um objeto PIL.Image (ou None)."""
    if not url_imagem:
        return None
    from PIL import Image  # importado aqui para o módulo não depender de Pillow
    try:
        req = urllib.request.Request(url_imagem, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return Image.open(BytesIO(resp.read())).convert("RGB")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------
def nome_tempo(segundos):
    """Tempo para usar em nome de arquivo (sem ":"): 65 -> "01m05s", 3725 -> "1h02m05s"."""
    decimo = round((segundos - int(segundos)) * 10)       # clips podem ter décimos (ex.: 40.5)
    segundos = int(segundos)
    h, resto = divmod(segundos, 3600)
    m, s = divmod(resto, 60)
    seg = f"{s:02d}" + (f".{decimo}" if decimo else "")
    return f"{h}h{m:02d}m{seg}s" if h else f"{m:02d}m{seg}s"


_REGEX_TEMPO_FFMPEG = re.compile(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)")
_REGEX_VELOCIDADE_FFMPEG = re.compile(r"speed=\s*([\d.]+)x")


def _linhas(fluxo):
    """Lê a saída de um processo linha a linha, separando também por "\r".

    O FFmpeg atualiza o andamento reescrevendo a mesma linha (com "\r"), então
    um simples `for linha in fluxo` só enxergaria isso no final.
    """
    resto = b""
    while True:
        pedaco = fluxo.read1(4096) if hasattr(fluxo, "read1") else fluxo.read(4096)
        if not pedaco:
            break
        resto += pedaco
        *completas, resto = re.split(rb"[\r\n]+", resto)
        for linha in completas:
            yield linha.decode("utf-8", errors="replace").strip()
    if resto.strip():
        yield resto.decode("utf-8", errors="replace").strip()


def _numero(valor):
    """Converte o texto do template ("123", "123.4" ou "NA") em número ou None."""
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Encoder H.264: usa a placa de vídeo se ela funcionar (bem mais rápido em 4K)
# ---------------------------------------------------------------------------
# Qualidade alta em todos (equivalente a "visualmente sem perda").
ARGUMENTOS_ENCODER = {
    "h264_nvenc": ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "19", "-b:v", "0"],
    "h264_qsv": ["-c:v", "h264_qsv", "-preset", "medium", "-global_quality", "20"],
    "h264_amf": ["-c:v", "h264_amf", "-quality", "quality", "-rc", "cqp",
                 "-qp_i", "18", "-qp_p", "20", "-qp_b", "22"],
    "libx264": ["-c:v", "libx264", "-preset", "faster", "-crf", "18"],
}
_ENCODERS_GPU = [("placa NVIDIA", "h264_nvenc"), ("Intel Quick Sync", "h264_qsv"),
                 ("placa AMD", "h264_amf")]
_encoder_escolhido = None


def escolher_encoder_h264(ffmpeg):
    """Testa (uma vez só) qual encoder H.264 funciona neste PC.

    Retorna (nome amigável, encoder). Se nenhuma placa de vídeo funcionar
    (ex.: driver antigo), usa o processador (libx264).
    """
    global _encoder_escolhido
    if _encoder_escolhido:
        return _encoder_escolhido
    for amigavel, encoder in _ENCODERS_GPU:
        teste = subprocess.run(
            [ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "lavfi",
             "-i", "color=black:s=1280x720:r=30", "-frames:v", "10",
             *ARGUMENTOS_ENCODER[encoder], "-pix_fmt", "yuv420p", "-f", "null", "-"],
            capture_output=True, creationflags=SEM_JANELA)
        if teste.returncode == 0:
            _encoder_escolhido = (amigavel, encoder)
            return _encoder_escolhido
    _encoder_escolhido = ("processador", "libx264")
    return _encoder_escolhido


class Baixador:
    """Executa um download por vez e permite cancelar o atual."""

    def __init__(self):
        self._processo = None
        self._cancelado = threading.Event()

    def cancelar(self):
        """Mata o yt-dlp (e o FFmpeg, se estiver rodando) do download atual."""
        self._cancelado.set()
        proc = self._processo
        if proc and proc.poll() is None:
            # /T encerra também os processos filhos (ex.: ffmpeg).
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                           capture_output=True, creationflags=SEM_JANELA)

    @staticmethod
    def _apagar_parciais(destinos, pasta=None, antes=None):
        """Apaga os pedaços incompletos (.part, .ytdl, fragmentos) de um download cancelado.

        Além dos arquivos que o yt-dlp avisou, apaga tudo o que apareceu na pasta durante
        este download (o yt-dlp às vezes imprime o nome sem alguns caracteres do título,
        e o HLS da Twitch deixa muitos arquivos de fragmento)."""
        time.sleep(0.8)  # dá tempo do Windows liberar os arquivos
        candidatos = []
        for caminho in destinos:
            candidatos += [caminho, caminho + ".part", caminho + ".ytdl"]
        if pasta and antes is not None:
            try:
                candidatos += [os.path.join(pasta, nome) for nome in os.listdir(pasta)
                               if nome not in antes]
            except OSError:
                pass
        for arquivo in candidatos:
            try:
                if os.path.isfile(arquivo):
                    os.remove(arquivo)
            except OSError:
                pass

    @staticmethod
    def _local_ffmpeg():
        ffmpeg = localizar_ferramenta("ffmpeg")
        return ["--ffmpeg-location", os.path.dirname(ffmpeg)] if ffmpeg else []

    def baixar(self, url, pasta, ao_progresso=None, ao_etapa=None, tentativas=3,
               limite_res=None, inicio=None, fim=None, login=None):
        """Baixa um vídeo (ou só um trecho dele, se inicio/fim forem informados, em
        segundos), tentando de novo se o YouTube recusar com erro 403
        (isso acontece de vez em quando e normalmente some na tentativa seguinte).

        Links do Instagram seguem outro caminho (veja _baixar_instagram)."""
        if instagram.eh_instagram(url):
            return self._baixar_instagram(url, pasta, ao_progresso, ao_etapa, login)
        if twitch.eh_twitch(url) and not twitch.eh_video_twitch(url):
            raise ErroDownload(twitch.mensagem_link_invalido_twitch(url))
        for tentativa in range(1, tentativas + 1):
            try:
                return self._baixar_uma_vez(url, pasta, ao_progresso, ao_etapa,
                                            limite_res, inicio, fim)
            except ErroDownload as e:
                temporario = "erro 403" in str(e)
                if not temporario or tentativa == tentativas or self._cancelado.is_set():
                    raise
                if ao_etapa:
                    ao_etapa(f"O YouTube recusou, tentando de novo ({tentativa + 1}/{tentativas})...")
                time.sleep(2)

    def _baixar_uma_vez(self, url, pasta, ao_progresso=None, ao_etapa=None,
                        limite_res=None, inicio=None, fim=None, login=None):
        """Baixa um vídeo. Bloqueia até terminar (chame dentro de uma thread).

        ao_progresso(dict): recebe {"percentual", "velocidade", "restante"}.
        ao_etapa(str): recebe textos como "Baixando vídeo...".
        Retorna "ok" ou "ja_existia". Lança ErroDownload ou Cancelado.
        """
        ytdlp = localizar_ytdlp()
        if not ytdlp:
            raise _erro_sem_ytdlp()

        os.makedirs(pasta, exist_ok=True)
        self._cancelado.clear()
        antes = set(os.listdir(pasta))      # para limpar só o que este download criar

        template = (MARCA_PROGRESSO +
                    "%(progress.downloaded_bytes)s|%(progress.total_bytes)s|"
                    "%(progress.total_bytes_estimate)s|%(progress.speed)s|%(progress.eta)s")
        # O yt-dlp escreve aqui o caminho do arquivo final (para podermos conferir
        # o formato depois). Usamos --print-to-file porque ele não esconde o progresso.
        arquivo_caminho = os.path.join(tempfile.gettempdir(),
                                       f"baixador_yt_{os.getpid()}_{threading.get_ident()}.txt")
        if os.path.exists(arquivo_caminho):
            os.remove(arquivo_caminho)

        # Clip: baixa só o trecho [inicio, fim]. O --force-keyframes-at-cuts faz o
        # corte exato (sem sobra no começo), e o arquivo ganha o trecho no nome.
        clipe = inicio is not None and fim is not None
        duracao_clipe = (fim - inicio) if clipe else None
        argumentos_clipe = []
        if clipe:
            argumentos_clipe = [
                "--download-sections", f"*{inicio:.2f}-{fim:.2f}",
                "--force-keyframes-at-cuts",
                "-o", f"%(title).100s [%(id)s] clip {nome_tempo(inicio)}-{nome_tempo(fim)}.%(ext)s",
            ]

        # Instagram: posts com vários vídeos viram uma "playlist" (todos devem ser baixados),
        # os cookies do login vão junto e o arquivo se chama "usuario - id".
        ig = instagram.eh_instagram(url)
        argumentos_ig = []
        if ig:
            argumentos_ig = [*instagram.argumentos_login(login),
                             "-o", "%(uploader_id|instagram)s - %(id)s.%(ext)s"]

        # Twitch: as gravações são HLS (milhares de pedacinhos) e podem ter muitas horas;
        # baixar 4 pedaços ao mesmo tempo acelera bastante. O nome inclui o canal.
        argumentos_tw = []
        if twitch.eh_twitch(url):
            argumentos_tw = ["--concurrent-fragments", "4"]
            if not clipe:
                argumentos_tw += ["-o", "%(uploader|twitch)s - %(title).80s [%(id)s].%(ext)s"]

        comando = [
            *ytdlp,
            *argumentos_js(ytdlp),
            "-f", FORMATO,
            "-S", ordenacao(limite_res),
            *argumentos_clipe,
            *argumentos_ig,
            *argumentos_tw,
            "--merge-output-format", "mp4",
            "--print-to-file", "after_move:filepath", arquivo_caminho,
            "-P", pasta,
            *([] if ig else ["--no-playlist"]),   # link com "&list=" baixa só o vídeo, não a playlist
            *self._local_ffmpeg(),    # diz ao yt-dlp onde está o FFmpeg (mesmo fora do PATH)
            "--newline",              # uma linha por atualização de progresso
            "--color", "never",
            "--progress-template", "download:" + template,
            url,
        ]

        self._processo = subprocess.Popen(
            comando, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            creationflags=SEM_JANELA, env=_ambiente_utf8(),
        )

        linhas_erro = []
        partes = 0
        destinos = []   # arquivos que o yt-dlp está criando (para limpar se cancelar)
        ja_existia = False

        for linha in _linhas(self._processo.stdout):
            if not linha:
                continue

            if clipe and linha.startswith("frame=") and ao_progresso:
                # Andamento do corte (vem do FFmpeg): "time=00:00:05.00 speed=1.5x"
                tempo = _REGEX_TEMPO_FFMPEG.search(linha)
                if tempo:
                    h, m, seg = tempo.groups()
                    feito = int(h) * 3600 + int(m) * 60 + float(seg)
                    vel = _REGEX_VELOCIDADE_FFMPEG.search(linha)
                    vel_x = float(vel.group(1)) if vel else None
                    ao_progresso({
                        "percentual": max(0.0, min(feito / duracao_clipe, 1.0)),
                        "velocidade": None,
                        "restante": ((duracao_clipe - feito) / vel_x) if vel_x else None,
                    })
            elif linha.startswith(MARCA_PROGRESSO):
                baixado, total, estimado, velocidade, restante = (
                    _numero(v) for v in linha[len(MARCA_PROGRESSO):].split("|"))
                total = total or estimado
                if ao_progresso and baixado is not None:
                    ao_progresso({
                        "percentual": (baixado / total) if total else None,
                        "velocidade": velocidade,
                        "restante": restante,
                    })
            elif linha.startswith("[download] Destination:"):
                partes += 1
                destinos.append(linha.split(":", 1)[1].strip())
                if ao_etapa:
                    if clipe:
                        ao_etapa("Cortando o clip (vídeo)..." if partes == 1
                                 else "Cortando o clip (áudio)...")
                    else:
                        ao_etapa("Baixando vídeo..." if partes == 1 else "Baixando áudio...")
            elif "has already been downloaded" in linha:
                ja_existia = True
            elif linha.startswith("[Merger]"):
                if ao_etapa:
                    ao_etapa("Juntando vídeo e áudio...")
            elif linha.startswith("ERROR:"):
                linhas_erro.append(linha)

        codigo = self._processo.wait()
        self._processo = None

        if self._cancelado.is_set():
            self._apagar_parciais(destinos, pasta, antes)
            raise Cancelado()
        if codigo != 0:
            texto_erro = "\n".join(linhas_erro)
            raise ErroDownload(traduzir_erro_plataforma(texto_erro, url, login), original=texto_erro)

        # Confere os arquivos finais (um post do Instagram pode ter vários) e converte
        # para H.264/AAC o que precisar.
        try:
            with open(arquivo_caminho, "r", encoding="utf-8") as f:
                caminhos_finais = [l.strip() for l in f.read().splitlines() if l.strip()]
            os.remove(arquivo_caminho)
        except OSError:
            caminhos_finais = []
        for caminho_final in caminhos_finais:
            if os.path.isfile(caminho_final):
                self.garantir_compativel(caminho_final, ao_progresso, ao_etapa)

        return "ja_existia" if ja_existia and partes == 0 else "ok"

    # ------------------------------------------------------------------
    # Instagram
    # ------------------------------------------------------------------
    def _baixar_instagram(self, url, pasta, ao_progresso, ao_etapa, login):
        """Vídeo/reel pelo yt-dlp; se o post só tiver fotos (ou o yt-dlp não souber), gallery-dl."""
        if not instagram.eh_post_instagram(url):
            raise ErroDownload("Use o link de um post, reel ou story do Instagram "
                               "(perfis inteiros não são suportados).")
        try:
            return self._baixar_uma_vez(url, pasta, ao_progresso, ao_etapa, login=login)
        except ErroDownload as erro1:
            if self._cancelado.is_set():
                raise
            texto = erro1.original
            if instagram.erro_de_cookies(texto) or str(erro1).startswith("Sem conexão"):
                raise
            if not comando_gallerydl():
                if instagram.precisa_gallerydl(texto):
                    raise ErroDownload("Esse post só tem fotos e isso precisa do gallery-dl. "
                                       "Instale com: python -m pip install gallery-dl", original=texto)
                raise
            if ao_etapa:
                ao_etapa("Baixando as fotos do post...")
            try:
                return self._baixar_gallerydl(url, pasta, ao_progresso, ao_etapa, login)
            except ErroDownload as erro2:
                # Mostra a causa mais útil (login, conta privada...) em vez de um erro genérico
                junto = f"{texto} {erro2.original}"
                frase = instagram.traduzir_erro_instagram(junto, login)
                raise ErroDownload(frase or str(erro2), original=junto)

    def _baixar_gallerydl(self, url, pasta, ao_progresso, ao_etapa, login):
        """Baixa fotos (e vídeos) de um post com o gallery-dl."""
        gallerydl = comando_gallerydl()
        if not gallerydl:
            raise ErroDownload("Falta o gallery-dl. Instale com: python -m pip install gallery-dl")
        os.makedirs(pasta, exist_ok=True)
        self._cancelado.clear()
        comando = [
            *gallerydl, "--no-colors", "-D", pasta,
            "-f", "{username}_{post_shortcode|media_id|id}_{num}.{extension}",
            *instagram.argumentos_login(login),
            url,
        ]
        self._processo = subprocess.Popen(
            comando, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            creationflags=SEM_JANELA, env=_ambiente_utf8())

        baixados, existentes, linhas_erro = [], [], []
        for linha in _linhas(self._processo.stdout):
            if not linha:
                continue
            existente = linha.startswith("# ")
            caminho = linha[2:].strip() if existente else linha
            if os.path.isfile(caminho):
                (existentes if existente else baixados).append(caminho)
                if ao_etapa:
                    ao_etapa(f"Baixando do Instagram... ({len(baixados) + len(existentes)} arquivo(s))")
            elif "[error]" in linha.lower() or linha.lower().startswith("error"):
                linhas_erro.append(linha)

        codigo = self._processo.wait()
        self._processo = None
        if self._cancelado.is_set():
            raise Cancelado()
        if not baixados and not existentes:
            texto = "\n".join(linhas_erro)
            if codigo != 0 or texto:
                raise ErroDownload(traduzir_erro_plataforma(texto, url, login), original=texto)
            raise ErroDownload("Não encontrei fotos nem vídeos nesse link.")

        for caminho in baixados:                  # vídeos de post com fotos: deixa compatível
            if caminho.lower().endswith((".mp4", ".mov", ".webm", ".m4v")):
                self.garantir_compativel(caminho, ao_progresso, ao_etapa)
        if ao_progresso:
            ao_progresso({"percentual": 1.0, "velocidade": None, "restante": None})
        return "ja_existia" if not baixados else "ok"

    # ------------------------------------------------------------------
    # Compatibilidade: garante vídeo H.264 + áudio AAC
    # ------------------------------------------------------------------
    @staticmethod
    def ler_codecs(caminho):
        """Retorna (codec_video, codec_audio, duracao_seg) usando o ffprobe."""
        ffprobe = localizar_ferramenta("ffprobe")
        if not ffprobe:
            return None, None, None

        def consultar(argumentos):
            r = subprocess.run([ffprobe, "-v", "error", *argumentos, "-of",
                                "default=noprint_wrappers=1:nokey=1", caminho],
                               capture_output=True, creationflags=SEM_JANELA)
            return r.stdout.decode("utf-8", errors="replace").strip().splitlines()

        video = consultar(["-select_streams", "v:0", "-show_entries", "stream=codec_name"])
        audio = consultar(["-select_streams", "a:0", "-show_entries", "stream=codec_name"])
        duracao = consultar(["-show_entries", "format=duration"])
        return (video[0] if video else None,
                audio[0] if audio else None,
                _numero(duracao[0]) if duracao else None)

    def garantir_compativel(self, caminho, ao_progresso=None, ao_etapa=None):
        """Se o vídeo não estiver em H.264 + AAC, converte com o FFmpeg.

        Na maioria dos vídeos o YouTube já entrega H.264 e nada é feito aqui.
        A conversão só acontece quando não existe versão H.264 (raro).
        """
        video, audio, duracao = self.ler_codecs(caminho)
        if video is None or (video == "h264" and audio in ("aac", None)):
            return  # já compatível (ou sem ffprobe para conferir)
        ffmpeg = localizar_ferramenta("ffmpeg")
        if not ffmpeg:
            raise ErroDownload("FFmpeg não encontrado. Ele é necessário para deixar "
                               "o vídeo em formato compatível.")
        if ao_etapa:
            via = escolher_encoder_h264(ffmpeg)[0]
            ao_etapa(f"Convertendo para formato compatível (H.264, via {via})...")

        temporario = caminho[:-4] + ".convertendo.mp4"
        encoder = escolher_encoder_h264(ffmpeg)
        try:
            self._converter(ffmpeg, encoder, caminho, temporario, audio, duracao, ao_progresso)
        except ErroDownload:
            if encoder[1] == "libx264":
                raise
            # A placa de vídeo falhou no meio: tenta de novo pelo processador.
            self._converter(ffmpeg, ("CPU", "libx264"), caminho, temporario, audio,
                            duracao, ao_progresso)
        os.replace(temporario, caminho)   # troca o original pelo convertido

    def _converter(self, ffmpeg, encoder, caminho, temporario, audio, duracao, ao_progresso):
        """Roda o FFmpeg para converter para H.264 + AAC."""
        _, nome_encoder = encoder
        comando = [
            ffmpeg, "-y", "-hide_banner", "-nostats", "-loglevel", "error",
            "-i", caminho,
            "-map", "0:v:0", "-map", "0:a:0?",
            *ARGUMENTOS_ENCODER[nome_encoder],
            "-pix_fmt", "yuv420p",              # 8 bits 4:2:0 = abre em tudo
            "-c:a", "copy" if audio == "aac" else "aac", "-b:a", "192k",
            "-movflags", "+faststart",          # começa a tocar antes de carregar tudo
            "-progress", "pipe:1",
            temporario,
        ]
        self._processo = subprocess.Popen(
            comando, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=SEM_JANELA)

        velocidade_x = None
        for bruto in self._processo.stdout:
            linha = bruto.decode("utf-8", errors="replace").strip()
            if linha.startswith("speed="):
                velocidade_x = _numero(linha[6:].rstrip("x"))
            elif linha.startswith("out_time_us=") and duracao and ao_progresso:
                feito = (_numero(linha[12:]) or 0) / 1_000_000
                restante = ((duracao - feito) / velocidade_x) if velocidade_x else None
                ao_progresso({"percentual": max(0.0, min(feito / duracao, 1.0)),
                              "velocidade": None, "restante": restante})

        erro = self._processo.stderr.read().decode("utf-8", errors="replace")
        codigo = self._processo.wait()
        self._processo = None

        if self._cancelado.is_set() or codigo != 0:
            time.sleep(0.3)
            try:
                os.remove(temporario)
            except OSError:
                pass
            if self._cancelado.is_set():
                raise Cancelado()
            raise ErroDownload("O vídeo foi baixado, mas não deu para convertê-lo "
                               f"para H.264: {erro.strip()[:150]}")
