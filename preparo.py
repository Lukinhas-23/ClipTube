"""
preparo.py
----------
Prepara o computador na primeira vez que o ClipTube abre.

  1) Bibliotecas Python (customtkinter, pillow): instaladas com pip se faltarem.
     (No ClipTube.exe elas já vêm dentro do arquivo, então nada é instalado.)
  2) Ferramentas externas (yt-dlp e FFmpeg): instaladas com o winget se faltarem.

Este arquivo usa só a biblioteca padrão do Python, para poder rodar ANTES de
qualquer outra coisa estar instalada.
"""

import glob
import importlib
import os
import shutil
import subprocess
import sys

SEM_JANELA = 0x08000000 if os.name == "nt" else 0

# Pacotes do winget que o app precisa (o FFmpeg inclui o ffprobe).
PACOTE_YTDLP = ("yt-dlp.yt-dlp", "yt-dlp")
PACOTE_FFMPEG = ("yt-dlp.FFmpeg", "FFmpeg")

_PASTA_APP = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------------------
# Encontrar programas
# ---------------------------------------------------------------------------
def _pasta_winget():
    return os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet")


def atualizar_path():
    """Relê o PATH do Windows (o winget acabou de mexer nele, mas o nosso processo
    ainda enxerga o PATH antigo) e inclui a pasta de atalhos do winget."""
    novos = []
    try:
        import winreg
        for raiz, subchave in (
                (winreg.HKEY_LOCAL_MACHINE,
                 r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
                (winreg.HKEY_CURRENT_USER, "Environment")):
            try:
                with winreg.OpenKey(raiz, subchave) as chave:
                    valor, _ = winreg.QueryValueEx(chave, "Path")
                    novos += os.path.expandvars(valor).split(os.pathsep)
            except OSError:
                pass
    except ImportError:
        pass
    novos.append(os.path.join(_pasta_winget(), "Links"))

    atuais = os.environ.get("PATH", "").split(os.pathsep)
    minusculos = {a.lower() for a in atuais}
    for pasta in novos:
        if pasta and pasta.lower() not in minusculos:
            atuais.append(pasta)
            minusculos.add(pasta.lower())
    os.environ["PATH"] = os.pathsep.join(atuais)


def localizar_ferramenta(nome):
    """Acha um programa (yt-dlp, ffmpeg, ffprobe...). Retorna o caminho ou None.

    Procura no PATH, na pasta de atalhos do winget e dentro dos pacotes do winget
    (o FFmpeg do winget às vezes não cria atalho, só fica na pasta do pacote).
    """
    caminho = shutil.which(nome)
    if caminho:
        return caminho
    base = _pasta_winget()
    atalho = os.path.join(base, "Links", nome + ".exe")
    if os.path.isfile(atalho):
        return atalho
    achados = glob.glob(os.path.join(base, "Packages", "**", nome + ".exe"), recursive=True)
    return achados[0] if achados else None


def ferramentas_faltando():
    """Lista os pacotes do winget que ainda precisam ser instalados.

    Retorna lista de (id_winget, nome_amigavel). Vazia = tudo certo.
    """
    faltando = []
    if not localizar_ferramenta("yt-dlp"):
        faltando.append(PACOTE_YTDLP)
    if not (localizar_ferramenta("ffmpeg") and localizar_ferramenta("ffprobe")):
        faltando.append(PACOTE_FFMPEG)
    return faltando


# ---------------------------------------------------------------------------
# Instalar ferramentas com o winget
# ---------------------------------------------------------------------------
def localizar_winget():
    return shutil.which("winget") or next(iter(glob.glob(os.path.join(
        os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WindowsApps", "winget.exe"))), None)


def instalar_ferramentas(pacotes, ao_log=None):
    """Instala os pacotes com o winget. Bloqueia até terminar (use numa thread).

    ao_log(texto): recebe uma linha de andamento ("Instalando FFmpeg...").
    Retorna (ok, mensagem). Só consideramos sucesso se o programa realmente
    aparecer depois da instalação.
    """
    def log(texto):
        if ao_log:
            ao_log(texto)

    winget = localizar_winget()
    if not winget:
        return False, ("O winget não foi encontrado neste computador. Instale o "
                       "'App Installer' na Microsoft Store, ou instale yt-dlp e FFmpeg "
                       "manualmente.")

    for id_pacote, nome in pacotes:
        log(f"Instalando {nome}... (pode demorar um pouco)")
        try:
            processo = subprocess.Popen(
                [winget, "install", "--id", id_pacote, "--exact", "--silent",
                 "--accept-package-agreements", "--accept-source-agreements"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                creationflags=SEM_JANELA)
            for bruto in processo.stdout:
                # O winget escreve barras de progresso com \r; pegamos só texto útil.
                for parte in bruto.decode("utf-8", errors="replace").replace("\r", "\n").split("\n"):
                    parte = parte.strip()
                    if parte and not set(parte) <= set("-\\|/ █▒"):
                        log(f"{nome}: {parte[:70]}")
            processo.wait()
        except OSError as e:
            return False, f"Não foi possível executar o winget: {e}"

    atualizar_path()
    ainda = ferramentas_faltando()
    if ainda:
        nomes = ", ".join(n for _, n in ainda)
        return False, f"A instalação terminou, mas não encontrei: {nomes}."
    return True, "Tudo instalado!"


# ---------------------------------------------------------------------------
# Bibliotecas Python
# ---------------------------------------------------------------------------
def _bibliotecas_ok():
    try:
        importlib.import_module("customtkinter")
        importlib.import_module("PIL")
        return True
    except ImportError:
        return False


def garantir_bibliotecas():
    """Instala customtkinter e pillow com o pip se faltarem (só no modo .py).

    Mostra uma janelinha simples enquanto instala. Se não der certo, avisa o
    motivo e fecha o programa.
    """
    if getattr(sys, "frozen", False) or _bibliotecas_ok():
        return

    import threading
    import tkinter as tk
    from tkinter import messagebox

    janela = tk.Tk()
    janela.title("ClipTube")
    janela.geometry("380x110")
    janela.resizable(False, False)
    janela.configure(bg="#0F0F0F")
    tk.Label(janela, text="Preparando o ClipTube pela primeira vez...", fg="white",
             bg="#0F0F0F", font=("Segoe UI", 11, "bold")).pack(pady=(20, 4))
    tk.Label(janela, text="Instalando bibliotecas (só acontece uma vez).", fg="#AAAAAA",
             bg="#0F0F0F", font=("Segoe UI", 9)).pack()
    resultado = {}

    def instalar():
        requisitos = os.path.join(_PASTA_APP, "requirements.txt")
        comando = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check"]
        comando += ["-r", requisitos] if os.path.isfile(requisitos) else ["customtkinter", "pillow"]
        proc = subprocess.run(comando, capture_output=True, creationflags=SEM_JANELA)
        resultado["erro"] = (proc.stderr or proc.stdout).decode("utf-8", errors="replace")[-400:] \
            if proc.returncode != 0 else None
        janela.after(0, janela.destroy)

    threading.Thread(target=instalar, daemon=True).start()
    janela.mainloop()

    importlib.invalidate_caches()
    if resultado.get("erro") is not None or not _bibliotecas_ok():
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "ClipTube",
            "Não consegui instalar as bibliotecas automaticamente.\n\n"
            "Abra o terminal nesta pasta e rode:\n"
            "python -m pip install -r requirements.txt\n\n"
            + (resultado.get("erro") or ""))
        sys.exit(1)
