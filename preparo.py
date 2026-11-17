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
# Só é instalado quando você baixa FOTOS do Instagram (pergunta antes).
PACOTE_GALLERYDL = ("mikf.gallery-dl", "gallery-dl")

# Programas que cada pacote do winget deve deixar instalados
EXECUTAVEIS = {
    PACOTE_YTDLP[0]: ("yt-dlp",),
    PACOTE_FFMPEG[0]: ("ffmpeg", "ffprobe"),
    PACOTE_GALLERYDL[0]: ("gallery-dl",),
}

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
    ainda = [(i, n) for i, n in pacotes
             if not all(localizar_ferramenta(x) for x in EXECUTAVEIS.get(i, ()))]
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


# ---------------------------------------------------------------------------
# Modo "linha de comando": usado pelo ClipTube.bat na primeira vez
#   python preparo.py --verificar   -> código 0 se tudo que o app precisa já está instalado
#   python preparo.py --instalar    -> instala o que faltar (mostrando o andamento)
# ---------------------------------------------------------------------------
def _instalar_bibliotecas_console():
    """Instala customtkinter e pillow com o pip, mostrando o andamento."""
    if _bibliotecas_ok():
        return True
    print("  Instalando as bibliotecas do Python (customtkinter, pillow)...")
    requisitos = os.path.join(_PASTA_APP, "requirements.txt")
    comando = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--quiet"]
    comando += ["-r", requisitos] if os.path.isfile(requisitos) else ["customtkinter", "pillow"]
    try:
        codigo = subprocess.run(comando).returncode
    except OSError:
        return False
    importlib.invalidate_caches()
    return codigo == 0 and _bibliotecas_ok()


def _tudo_pronto():
    return _bibliotecas_ok() and not ferramentas_faltando()


def instalar_tudo():
    """Instala o que faltar. Retorna 0 se o app já pode funcionar, 1 se não."""
    print()
    print("  ClipTube - preparando o computador (so na primeira vez).")
    print("  Precisa de internet e pode levar alguns minutos. Nao feche esta janela.")
    print()
    atualizar_path()

    print("[1/3] Bibliotecas do Python")
    libs_ok = _instalar_bibliotecas_console()
    print("      " + ("OK" if libs_ok else "FALHOU (veja a mensagem acima)"))

    print("[2/3] yt-dlp e FFmpeg (baixam os videos)")
    faltando = ferramentas_faltando()
    if faltando:
        ok, mensagem = instalar_ferramentas(faltando, ao_log=lambda t: print("      " + t))
        print("      " + ("OK" if ok else "FALHOU: " + mensagem))
        essenciais_ok = ok
    else:
        print("      ja instalados")
        essenciais_ok = True

    print("[3/3] gallery-dl (fotos do Instagram)")
    if localizar_ferramenta("gallery-dl"):
        print("      ja instalado")
    else:
        ok, mensagem = instalar_ferramentas([PACOTE_GALLERYDL], ao_log=lambda t: print("      " + t))
        # Opcional: sem ele só as fotos do Instagram não funcionam; o app oferece de novo depois.
        print("      " + ("OK" if ok else "nao foi possivel agora (o app oferece instalar depois)"))

    print()
    if libs_ok and essenciais_ok:
        print("  Tudo pronto! Abrindo o ClipTube...")
        return 0
    print("  Nem tudo foi instalado. O ClipTube vai abrir e mostrar o que falta.")
    return 1


if __name__ == "__main__":
    argumentos = sys.argv[1:]
    if "--verificar" in argumentos:
        sys.exit(0 if _tudo_pronto() else 1)
    if "--instalar" in argumentos:
        sys.exit(instalar_tudo())
    print("Uso: python preparo.py --verificar | --instalar")
    sys.exit(2)
