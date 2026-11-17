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
import importlib.util
import os
import shutil
import subprocess
import sys

SEM_JANELA = 0x08000000 if os.name == "nt" else 0

# Pacotes do winget que o app precisa (o FFmpeg inclui o ffprobe).
# yt-dlp e gallery-dl são instalados de preferência como bibliotecas do Python (pip), porque
# o Windows pode bloquear os .exe deles ("Controle de Aplicativo"/Smart App Control), mas
# nunca bloqueia o python.exe. O winget fica como plano B.
PACOTE_YTDLP = ("yt-dlp.yt-dlp", "yt-dlp")
PACOTE_FFMPEG = ("yt-dlp.FFmpeg", "FFmpeg")
# Fotos do Instagram (o app oferece instalar quando você cola um link do Instagram).
PACOTE_GALLERYDL = ("mikf.gallery-dl", "gallery-dl")
# O YouTube exige um interpretador de JavaScript para o yt-dlp (o pacote do yt-dlp no winget
# já traz o Deno como dependência; isto é só um reforço).
PACOTE_DENO = ("DenoLand.Deno", "Deno")

# Como instalar cada pacote pelo pip (biblioteca Python), quando houver
PIP_DO_PACOTE = {
    PACOTE_YTDLP[0]: "yt-dlp[default]",       # [default] inclui o que o yt-dlp usa para o YouTube
    PACOTE_GALLERYDL[0]: "gallery-dl",
}

# Programas que cada pacote do winget deve deixar instalados
EXECUTAVEIS = {
    PACOTE_YTDLP[0]: ("yt-dlp",),
    PACOTE_FFMPEG[0]: ("ffmpeg", "ffprobe"),
    PACOTE_GALLERYDL[0]: ("gallery-dl",),
    PACOTE_DENO[0]: ("deno",),
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


def python_console():
    """python.exe (com console, para capturar a saída). O app roda com pythonw.exe."""
    pasta, nome = os.path.split(sys.executable)
    if nome.lower() == "pythonw.exe":
        candidato = os.path.join(pasta, "python.exe")
        if os.path.isfile(candidato):
            return candidato
    return sys.executable


def _roda(comando, tempo=30):
    """(ok, saída): o comando executa de verdade? (False se não existir ou se o Windows bloquear)"""
    try:
        r = subprocess.run(comando, capture_output=True, timeout=tempo, creationflags=SEM_JANELA)
        return r.returncode == 0, (r.stdout or r.stderr).decode("utf-8", errors="replace")
    except Exception as e:
        return False, str(e)


_cache_comandos = {}


def limpar_cache_comandos():
    """Esquece o que já foi descoberto (use depois de instalar algo)."""
    _cache_comandos.clear()


def comando_programa(nome, modulo):
    """Como executar o programa `nome` (yt-dlp ou gallery-dl).

    Prefere a versão em Python (`python -m modulo`), que roda dentro do python.exe e por isso
    o Windows não bloqueia. Se ela não estiver instalada, tenta o .exe. Retorna uma lista
    (ex.: [python.exe, "-m", "yt_dlp"]) ou None se nenhum dos dois funcionar.
    """
    if nome in _cache_comandos:
        return _cache_comandos[nome]
    comando = None
    if not getattr(sys, "frozen", False) and importlib.util.find_spec(modulo) is not None:
        candidato = [python_console(), "-m", modulo]
        if _roda(candidato + ["--version"])[0]:
            comando = candidato
    if comando is None:
        exe = localizar_ferramenta(nome)
        if exe and _roda([exe, "--version"])[0]:
            comando = [exe]
    _cache_comandos[nome] = comando
    return comando


def comando_ytdlp():
    return comando_programa("yt-dlp", "yt_dlp")


def comando_gallerydl():
    return comando_programa("gallery-dl", "gallery_dl")


def _pacote_ok(id_pacote):
    """O pacote está instalado e FUNCIONA?"""
    if id_pacote == PACOTE_YTDLP[0]:
        return bool(comando_ytdlp())
    if id_pacote == PACOTE_GALLERYDL[0]:
        return bool(comando_gallerydl())
    return all(localizar_ferramenta(x) for x in EXECUTAVEIS.get(id_pacote, ()))


def ferramentas_faltando():
    """Lista o que ainda precisa ser instalado para o app baixar.

    Retorna lista de (id_pacote, nome_amigavel). Vazia = tudo certo.
    """
    faltando = []
    if not comando_ytdlp():
        faltando.append(PACOTE_YTDLP)
    if not (localizar_ferramenta("ffmpeg") and localizar_ferramenta("ffprobe")):
        faltando.append(PACOTE_FFMPEG)
    if not localizar_ferramenta("deno"):
        faltando.append(PACOTE_DENO)
    return faltando


# ---------------------------------------------------------------------------
# Instalar ferramentas com o winget
# ---------------------------------------------------------------------------
def localizar_winget():
    return shutil.which("winget") or next(iter(glob.glob(os.path.join(
        os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WindowsApps", "winget.exe"))), None)


def _pip_instalar(requisito, nome, log):
    """Instala uma biblioteca Python com o pip. Retorna True se o pip terminou sem erro."""
    log(f"Instalando {nome} (biblioteca Python)... (pode demorar um pouco)")
    try:
        r = subprocess.run([python_console(), "-m", "pip", "install", "--disable-pip-version-check",
                            "--upgrade", requisito], capture_output=True, creationflags=SEM_JANELA)
    except OSError:
        return False
    return r.returncode == 0


def _winget_instalar(winget, id_pacote, nome, log):
    """Instala um pacote com o winget, mostrando as linhas úteis do andamento."""
    log(f"Instalando {nome}... (pode demorar um pouco)")
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


def instalar_ferramentas(pacotes, ao_log=None):
    """Instala os pacotes. Bloqueia até terminar (use numa thread).

    yt-dlp e gallery-dl: primeiro como biblioteca Python (pip), que o Windows não bloqueia;
    se não der, pelo winget. FFmpeg e Deno: pelo winget.
    ao_log(texto): recebe uma linha de andamento ("Instalando FFmpeg...").
    Retorna (ok, mensagem). Só consideramos sucesso se o programa realmente
    FUNCIONAR depois da instalação.
    """
    def log(texto):
        if ao_log:
            ao_log(texto)

    winget = localizar_winget()
    for id_pacote, nome in pacotes:
        if id_pacote in PIP_DO_PACOTE:
            _pip_instalar(PIP_DO_PACOTE[id_pacote], nome, log)
            limpar_cache_comandos()
            if _pacote_ok(id_pacote):
                continue
            log(f"{nome}: a versão em Python não funcionou, tentando pelo winget...")
        if not winget:
            return False, ("O winget não foi encontrado neste computador. Instale o "
                           "'App Installer' na Microsoft Store, ou instale FFmpeg e Deno "
                           "manualmente.")
        try:
            _winget_instalar(winget, id_pacote, nome, log)
        except OSError as e:
            return False, f"Não foi possível executar o winget: {e}"

    atualizar_path()
    limpar_cache_comandos()
    ainda = [(i, n) for i, n in pacotes if not _pacote_ok(i)]
    if ainda:
        nomes = ", ".join(n for _, n in ainda)
        return False, f"A instalação terminou, mas não consegui fazer funcionar: {nomes}."
    return True, "Tudo instalado!"


# ---------------------------------------------------------------------------
# Bibliotecas Python
# ---------------------------------------------------------------------------
def _bibliotecas_ok():
    """customtkinter e pillow (o app precisa deles já) + yt_dlp e gallery_dl (que ele chama)."""
    try:
        importlib.import_module("customtkinter")
        importlib.import_module("PIL")
    except ImportError:
        return False
    if getattr(sys, "frozen", False):        # no .exe só vale o que está dentro dele
        return True
    return all(importlib.util.find_spec(m) is not None for m in ("yt_dlp", "gallery_dl"))


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

    print("[1/3] Bibliotecas do Python (inclui yt-dlp e gallery-dl)")
    libs_ok = _instalar_bibliotecas_console()
    limpar_cache_comandos()
    print("      " + ("OK" if libs_ok else "FALHOU (veja a mensagem acima)"))

    print("[2/3] FFmpeg e Deno (programas do Windows que o yt-dlp usa)")
    faltando = ferramentas_faltando()
    if faltando:
        ok, mensagem = instalar_ferramentas(faltando, ao_log=lambda t: print("      " + t))
        print("      " + ("OK" if ok else "FALHOU: " + mensagem))
        essenciais_ok = ok
    else:
        print("      ja instalados")
        essenciais_ok = True

    print("[3/3] Conferindo se tudo funciona")
    for nome, comando in (("yt-dlp", comando_ytdlp()), ("gallery-dl (fotos do Instagram)", comando_gallerydl())):
        if comando:
            via = "versao em Python" if len(comando) > 1 else "programa .exe"
            print(f"      {nome}: OK ({via})")
        else:
            print(f"      {nome}: nao funciona (o Windows pode ter bloqueado o programa)")
    for programa in ("ffmpeg", "deno"):
        print(f"      {programa}: " + ("OK" if localizar_ferramenta(programa) else "nao encontrado"))

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
