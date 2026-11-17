"""
previas.py
----------
Imagens e vídeo de PRÉVIA para o recorte de clips, sem baixar o vídeo inteiro:

  * Storyboard: o YouTube publica "folhas" com miniaturas do vídeo todo
    (1 quadro a cada ~5 s). Usamos isso para a linha do tempo e para mostrar
    o quadro de qualquer instante de forma instantânea.
  * quadro_exato(): pede ao FFmpeg o quadro EXATO de um instante (leva ~1 s).
  * Reprodutor: toca o trecho escolhido (imagem + som) para você ver como o
    clip vai ficar. O vídeo é lido do YouTube só no trecho pedido.

Nada aqui usa a interface; quem desenha as imagens é o clip_ui.py.
"""

import io
import os
import subprocess
import tempfile
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from PIL import Image

from preparo import localizar_ferramenta

try:
    import winsound          # só existe no Windows (toca o áudio da prévia)
except ImportError:          # pragma: no cover
    winsound = None

SEM_JANELA = 0x08000000 if os.name == "nt" else 0
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
LIMITE_PREVIA_SEG = 300      # a prévia toca no máximo 5 min do clip


# ---------------------------------------------------------------------------
# Dados do JSON do yt-dlp
# ---------------------------------------------------------------------------
def extrair_dados_previa(dados):
    """Tira do JSON do yt-dlp o que a prévia precisa: storyboards e links de stream."""
    niveis = []
    for f in dados.get("formats") or []:
        if (str(f.get("format_id", "")).startswith("sb") and f.get("fragments")
                and f.get("width") and f.get("height") and f.get("rows") and f.get("columns")):
            niveis.append({
                "w": f["width"], "h": f["height"],
                "linhas": f["rows"], "colunas": f["columns"],
                "fragmentos": [(fr["url"], float(fr.get("duration") or 0)) for fr in f["fragments"]],
            })
    niveis.sort(key=lambda n: n["w"] * n["h"])
    return {"storyboards": niveis, "stream": _escolher_stream(dados)}


def _escolher_stream(dados):
    """Escolhe um vídeo pequeno (>= 360p) e a faixa de áudio ORIGINAL (não dublada)."""
    formatos = [f for f in (dados.get("formats") or [])
                if f.get("url") and f.get("protocol") == "https"]

    def lado_menor(f):
        return min(f["width"], f["height"])

    videos = [f for f in formatos if f.get("vcodec") not in (None, "none")
              and f.get("acodec") in (None, "none") and f.get("width") and f.get("height")]
    bons = [f for f in videos if lado_menor(f) >= 360]
    bons.sort(key=lambda f: (not (f.get("vcodec") or "").startswith("avc1"), lado_menor(f)))
    video = bons[0] if bons else (max(videos, key=lado_menor) if videos else None)
    if not video:
        return None

    audios = [f for f in formatos if f.get("acodec") not in (None, "none")
              and f.get("vcodec") in (None, "none") and "drc" not in str(f.get("format_id", ""))]
    # language_preference alta = idioma original do vídeo (os outros são dublagens)
    audio = max(audios, key=lambda f: (f.get("language_preference") or 0,
                                       f.get("ext") == "m4a", f.get("abr") or 0)) if audios else None
    return {"video": video["url"], "audio": audio["url"] if audio else None,
            "largura": video["width"], "altura": video["height"]}


# ---------------------------------------------------------------------------
# Storyboard (miniaturas do vídeo todo)
# ---------------------------------------------------------------------------
class Storyboard:
    """Um nível de storyboard: várias folhas, cada uma com uma grade de quadros."""

    def __init__(self, nivel):
        self.w, self.h = nivel["w"], nivel["h"]
        self.linhas, self.colunas = nivel["linhas"], nivel["colunas"]
        self.fragmentos = nivel["fragmentos"]
        self.por_folha = self.linhas * self.colunas
        primeira = self.fragmentos[0][1] if self.fragmentos else 0
        self.intervalo = (primeira / self.por_folha) if primeira else 5.0   # segundos por quadro
        self._inicios, soma = [], 0.0
        for _, duracao in self.fragmentos:
            self._inicios.append(soma)
            soma += duracao
        self._folhas = {}
        self._trava = threading.Lock()

    @property
    def proporcao(self):
        return self.w / self.h

    def _indice_folha(self, t):
        for i in range(len(self.fragmentos) - 1, -1, -1):
            if t >= self._inicios[i]:
                return i
        return 0

    def _baixar_folha(self, i):
        requisicao = urllib.request.Request(self.fragmentos[i][0], headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(requisicao, timeout=15) as resposta:
            return Image.open(io.BytesIO(resposta.read())).convert("RGB")

    def folha(self, i, baixar=True):
        with self._trava:
            if i in self._folhas:
                return self._folhas[i]
        if not baixar:
            return None
        try:
            imagem = self._baixar_folha(i)
        except Exception:
            imagem = None
        with self._trava:
            self._folhas[i] = imagem
        return imagem

    def quadro(self, t, baixar=True):
        """Quadro mais próximo do instante t (PIL.Image) ou None se ainda não carregou."""
        i = self._indice_folha(t)
        folha = self.folha(i, baixar)
        if folha is None:
            return None
        indice = max(0, min(int((t - self._inicios[i]) / self.intervalo), self.por_folha - 1))
        while indice >= 0:                       # a última folha pode ter menos quadros
            linha, coluna = divmod(indice, self.colunas)
            x, y = coluna * self.w, linha * self.h
            if x + self.w <= folha.width and y + self.h <= folha.height:
                return folha.crop((x, y, x + self.w, y + self.h))
            indice -= 1
        return None

    def precarregar(self, ao_folha=None):
        """Baixa todas as folhas em segundo plano. ao_folha() é chamado a cada folha pronta."""
        def tarefa(i):
            self.folha(i)
            if ao_folha:
                ao_folha()
        executor = ThreadPoolExecutor(max_workers=4)
        for i in range(len(self.fragmentos)):
            executor.submit(tarefa, i)
        executor.shutdown(wait=False)


# ---------------------------------------------------------------------------
# Quadro exato
# ---------------------------------------------------------------------------
def quadro_exato(url_video, t, altura=200, tempo_limite=25):
    """Quadro exato do instante t (PIL.Image), lido direto do stream. None se falhar."""
    ffmpeg = localizar_ferramenta("ffmpeg")
    if not ffmpeg or not url_video:
        return None
    try:
        r = subprocess.run(
            [ffmpeg, "-v", "error", "-ss", f"{t:.2f}", "-i", url_video, "-frames:v", "1",
             "-vf", f"scale=-2:{altura}", "-q:v", "3", "-f", "mjpeg", "pipe:1"],
            capture_output=True, timeout=tempo_limite, creationflags=SEM_JANELA)
        if r.returncode != 0 or not r.stdout:
            return None
        return Image.open(io.BytesIO(r.stdout)).convert("RGB")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Player da prévia (imagem + som)
# ---------------------------------------------------------------------------
class Reprodutor:
    """Toca o trecho [ini, fim] do vídeo.

    Roda em threads. A interface só precisa ler:
      estado         "carregando" | "tocando" | "fim" | "erro"
      quadro_atual   bytes RGB do quadro mostrado agora (largura x altura x 3)
      indice         número do quadro (muda a cada quadro novo)
      tempo_atual    segundos tocados
    """
    FPS = 20

    def __init__(self, url_video, url_audio, ini, fim, largura, altura):
        self.url_video, self.url_audio = url_video, url_audio
        self.ini = ini
        self.duracao = min(fim - ini, LIMITE_PREVIA_SEG)
        self.largura, self.altura = largura, altura
        self.estado = "carregando"
        self.quadro_atual = None
        self.indice = -1
        self.tempo_atual = 0.0
        self._parar = threading.Event()
        self._processos = []
        self._wav = None

    def iniciar(self):
        threading.Thread(target=self._rodar, daemon=True).start()

    def parar(self):
        self._parar.set()
        for processo in self._processos:
            try:
                processo.kill()
            except Exception:
                pass
        if winsound:
            try:
                winsound.PlaySound(None, winsound.SND_PURGE)
            except Exception:
                pass
        if self._wav:
            wav, self._wav = self._wav, None
            threading.Timer(1.0, lambda: _apagar(wav)).start()

    def _ler(self, processo, tamanho):
        dados = processo.stdout.read(tamanho)
        return dados if dados and len(dados) == tamanho else None

    def _rodar(self):
        ffmpeg = localizar_ferramenta("ffmpeg")
        if not ffmpeg:
            self.estado = "erro"
            return
        try:
            ini, dur = f"{self.ini:.2f}", f"{self.duracao:.2f}"
            audio = None
            if self.url_audio and winsound:
                # O áudio vira um WAV temporário (rápido) que o winsound toca.
                self._wav = os.path.join(tempfile.gettempdir(),
                                         f"cliptube_previa_{os.getpid()}_{id(self)}.wav")
                audio = subprocess.Popen(
                    [ffmpeg, "-v", "error", "-ss", ini, "-t", dur, "-i", self.url_audio, "-vn",
                     "-ac", "2", "-ar", "44100", "-acodec", "pcm_s16le", "-y", self._wav],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=SEM_JANELA)
                self._processos.append(audio)

            video = subprocess.Popen(
                [ffmpeg, "-v", "error", "-ss", ini, "-t", dur, "-i", self.url_video, "-an",
                 "-vf", f"scale={self.largura}:{self.altura},fps={self.FPS}",
                 "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=SEM_JANELA)
            self._processos.append(video)

            tamanho = self.largura * self.altura * 3
            quadro = self._ler(video, tamanho)
            if quadro is None:
                if not self._parar.is_set():
                    self.estado = "erro"
                return
            tem_audio = False
            if audio is not None:
                tem_audio = audio.wait() == 0 and os.path.isfile(self._wav or "")
            if self._parar.is_set():
                return

            inicio = time.perf_counter()          # a partir daqui imagem e som andam juntos
            if tem_audio:
                winsound.PlaySound(self._wav, winsound.SND_FILENAME | winsound.SND_ASYNC)
            self.estado = "tocando"
            i = 0
            while quadro is not None and not self._parar.is_set():
                espera = inicio + i / self.FPS - time.perf_counter()
                if espera > 0:
                    time.sleep(espera)
                if espera > -0.25:                # se atrasou muito, pula o quadro
                    self.quadro_atual, self.indice = quadro, i
                self.tempo_atual = i / self.FPS
                i += 1
                quadro = self._ler(video, tamanho)
            if not self._parar.is_set():
                self.tempo_atual = self.duracao
                self.estado = "fim"
        except Exception:
            if not self._parar.is_set():
                self.estado = "erro"


def _apagar(caminho):
    try:
        os.remove(caminho)
    except OSError:
        pass
