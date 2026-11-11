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

import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.request
from io import BytesIO

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
    """Erro já traduzido para uma mensagem simples em português."""


class Cancelado(Exception):
    """O usuário clicou em Cancelar."""


# ---------------------------------------------------------------------------
# Localização do yt-dlp
# ---------------------------------------------------------------------------
def localizar_ytdlp():
    """Procura o yt-dlp no PATH e, se não achar, na pasta de links do winget."""
    caminho = shutil.which("yt-dlp")
    if caminho:
        return caminho
    winget = os.path.join(os.environ.get("LOCALAPPDATA", ""),
                          "Microsoft", "WinGet", "Links", "yt-dlp.exe")
    if os.path.isfile(winget):
        return winget
    return None


def _ambiente_utf8():
    """Faz o yt-dlp escrever a saída em UTF-8 (títulos com acento/emoji)."""
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


# ---------------------------------------------------------------------------
# Tradução de erros
# ---------------------------------------------------------------------------
# Cada regra: (trechos que podem aparecer no erro do yt-dlp, mensagem amigável).
# A ordem importa: as mais específicas vêm primeiro.
_REGRAS_ERRO = [
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


# ---------------------------------------------------------------------------
# Informações do vídeo (título, canal, duração, miniatura)
# ---------------------------------------------------------------------------
def obter_info(url, timeout=90):
    """Pergunta ao yt-dlp os dados do vídeo, sem baixar nada.

    Retorna um dicionário com: titulo, canal, duracao (segundos), miniatura (URL).
    """
    ytdlp = localizar_ytdlp()
    if not ytdlp:
        raise ErroDownload("yt-dlp não encontrado. Instale com: winget install yt-dlp")

    try:
        proc = subprocess.run(
            [ytdlp, "-J", "--no-playlist", "--no-warnings", url],
            capture_output=True, timeout=timeout,
            creationflags=SEM_JANELA, env=_ambiente_utf8(),
        )
    except subprocess.TimeoutExpired:
        raise ErroDownload("O YouTube demorou demais para responder. Tente de novo.")

    saida = proc.stdout.decode("utf-8", errors="replace")
    erro = proc.stderr.decode("utf-8", errors="replace")
    if proc.returncode != 0 or not saida.strip():
        raise ErroDownload(traduzir_erro(erro))

    dados = json.loads(saida)
    return {
        "titulo": dados.get("title") or "(sem título)",
        "canal": dados.get("uploader") or dados.get("channel") or "",
        "duracao": dados.get("duration"),
        "miniatura": dados.get("thumbnail"),
        "qualidades": listar_qualidades(dados),
    }


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
        if f.get("vcodec") in (None, "none"):
            continue  # só áudio ou imagens de prévia
        largura, altura = f.get("width"), f.get("height")
        if not largura or not altura:
            continue
        res = min(largura, altura)
        if res < 144:
            continue
        q = por_res.setdefault(res, {"res": res, "fps": 0, "h264": False, "tamanho": 0})
        q["fps"] = max(q["fps"], int(f.get("fps") or 0))
        if (f.get("vcodec") or "").startswith("avc1"):
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
    def _apagar_parciais(destinos):
        """Apaga os pedaços incompletos (.part, .ytdl) de um download cancelado."""
        time.sleep(0.5)  # dá tempo do Windows liberar os arquivos
        for caminho in destinos:
            for arquivo in (caminho, caminho + ".part", caminho + ".ytdl"):
                try:
                    if os.path.isfile(arquivo):
                        os.remove(arquivo)
                except OSError:
                    pass

    def baixar(self, url, pasta, ao_progresso=None, ao_etapa=None, tentativas=3,
               limite_res=None):
        """Baixa um vídeo, tentando de novo se o YouTube recusar com erro 403
        (isso acontece de vez em quando e normalmente some na tentativa seguinte)."""
        for tentativa in range(1, tentativas + 1):
            try:
                return self._baixar_uma_vez(url, pasta, ao_progresso, ao_etapa, limite_res)
            except ErroDownload as e:
                temporario = "erro 403" in str(e)
                if not temporario or tentativa == tentativas or self._cancelado.is_set():
                    raise
                if ao_etapa:
                    ao_etapa(f"O YouTube recusou, tentando de novo ({tentativa + 1}/{tentativas})...")
                time.sleep(2)

    def _baixar_uma_vez(self, url, pasta, ao_progresso=None, ao_etapa=None, limite_res=None):
        """Baixa um vídeo. Bloqueia até terminar (chame dentro de uma thread).

        ao_progresso(dict): recebe {"percentual", "velocidade", "restante"}.
        ao_etapa(str): recebe textos como "Baixando vídeo...".
        Retorna "ok" ou "ja_existia". Lança ErroDownload ou Cancelado.
        """
        ytdlp = localizar_ytdlp()
        if not ytdlp:
            raise ErroDownload("yt-dlp não encontrado. Instale com: winget install yt-dlp")

        os.makedirs(pasta, exist_ok=True)
        self._cancelado.clear()

        template = (MARCA_PROGRESSO +
                    "%(progress.downloaded_bytes)s|%(progress.total_bytes)s|"
                    "%(progress.total_bytes_estimate)s|%(progress.speed)s|%(progress.eta)s")
        # O yt-dlp escreve aqui o caminho do arquivo final (para podermos conferir
        # o formato depois). Usamos --print-to-file porque ele não esconde o progresso.
        arquivo_caminho = os.path.join(tempfile.gettempdir(),
                                       f"baixador_yt_{os.getpid()}_{threading.get_ident()}.txt")
        if os.path.exists(arquivo_caminho):
            os.remove(arquivo_caminho)

        comando = [
            ytdlp,
            "-f", FORMATO,
            "-S", ordenacao(limite_res),
            "--merge-output-format", "mp4",
            "--print-to-file", "after_move:filepath", arquivo_caminho,
            "-P", pasta,
            "--no-playlist",          # link com "&list=" baixa só o vídeo, não a playlist
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

        for bruto in self._processo.stdout:
            linha = bruto.decode("utf-8", errors="replace").strip()
            if not linha:
                continue

            if linha.startswith(MARCA_PROGRESSO):
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
            self._apagar_parciais(destinos)
            raise Cancelado()
        if codigo != 0:
            raise ErroDownload(traduzir_erro("\n".join(linhas_erro)))

        # Confere o arquivo final e converte para H.264/AAC se precisar.
        try:
            with open(arquivo_caminho, "r", encoding="utf-8") as f:
                caminho_final = f.read().strip().splitlines()[-1]
            os.remove(arquivo_caminho)
        except (OSError, IndexError):
            caminho_final = None
        if caminho_final and os.path.isfile(caminho_final):
            self.garantir_compativel(caminho_final, ao_progresso, ao_etapa)

        return "ja_existia" if ja_existia and partes == 0 else "ok"

    # ------------------------------------------------------------------
    # Compatibilidade: garante vídeo H.264 + áudio AAC
    # ------------------------------------------------------------------
    @staticmethod
    def ler_codecs(caminho):
        """Retorna (codec_video, codec_audio, duracao_seg) usando o ffprobe."""
        ffprobe = shutil.which("ffprobe")
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
        ffmpeg = shutil.which("ffmpeg")
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
