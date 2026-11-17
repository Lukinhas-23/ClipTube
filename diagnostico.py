"""
diagnostico.py
--------------
Testa, passo a passo, se o ClipTube consegue baixar neste computador e grava o resultado
em diagnostico.txt (na pasta do ClipTube). Use quando algo der erro: dê dois cliques em
diagnostico.bat e mande o conteúdo do diagnostico.txt para quem estiver ajudando.

Testes (usam um vídeo curto e público do YouTube, 19 segundos, em 144p):
  1. versões e locais das ferramentas (yt-dlp, FFmpeg, Deno, gallery-dl, winget)
  2. ler as informações do vídeo
  3. baixar o vídeo
  4. baixar um clip de 4 segundos
"""

import glob
import os
import shutil
import sys
import tempfile
import time
import traceback

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)

LINK_TESTE = "https://www.youtube.com/watch?v=jNQXAC9IVRw"
SAIDA = os.path.join(AQUI, "diagnostico.txt")
linhas = []


def escrever(texto=""):
    print(texto)
    linhas.append(texto)


def etapa(nome, funcao):
    escrever()
    escrever(f"=== {nome}")
    inicio = time.time()
    try:
        resultado = funcao()
        escrever(f"[OK] {resultado or ''}  ({time.time() - inicio:.1f} s)")
        return True
    except Exception as e:
        escrever(f"[FALHOU] {e}")
        original = getattr(e, "original", "")
        if original and original != str(e):
            escrever("--- texto técnico do erro ---")
            escrever(original.strip()[:3000])
        else:
            escrever(traceback.format_exc()[-1500:])
        return False


def main():
    escrever("ClipTube - diagnóstico")
    escrever(time.strftime("Data: %Y-%m-%d %H:%M:%S"))
    try:
        import downloader as dl
    except Exception:
        escrever("Não consegui carregar o ClipTube (faltam bibliotecas?):")
        escrever(traceback.format_exc())
        return

    escrever()
    escrever("=== 1. Ambiente")
    escrever(dl.info_ambiente())
    if "4551" in dl.info_ambiente():
        escrever()
        escrever(dl.COMO_RESOLVER_BLOQUEIO)

    pasta = tempfile.mkdtemp(prefix="cliptube_diag_")
    baixador = dl.Baixador()

    def ler_info():
        info = dl.obter_info(LINK_TESTE)
        qualidades = ", ".join(f"{q['res']}p" for q in info["qualidades"][:6])
        return f"{info['titulo']!r}, {info['duracao']} s, qualidades: {qualidades}"

    def baixar_video():
        etapas = []
        resultado = baixador.baixar(LINK_TESTE, pasta, None, etapas.append, limite_res=144)
        arquivos = glob.glob(os.path.join(pasta, "*.mp4"))
        detalhe = ""
        if arquivos:
            codecs = baixador.ler_codecs(arquivos[0])
            detalhe = f"{os.path.basename(arquivos[0])} codecs={codecs[:2]} {os.path.getsize(arquivos[0]) // 1024} KB"
        return f"{resultado}; etapas: {etapas}; {detalhe}"

    def baixar_clip():
        pasta_clip = os.path.join(pasta, "clip")
        resultado = baixador.baixar(LINK_TESTE, pasta_clip, None, None, limite_res=144, inicio=2, fim=6)
        arquivos = glob.glob(os.path.join(pasta_clip, "*.mp4"))
        detalhe = ""
        if arquivos:
            codecs = baixador.ler_codecs(arquivos[0])
            detalhe = f"{os.path.basename(arquivos[0])} duração={codecs[2]} s"
        return f"{resultado}; {detalhe}"

    ok1 = etapa("2. Ler informações do vídeo de teste", ler_info)
    ok2 = etapa("3. Baixar o vídeo de teste (144p)", baixar_video) if ok1 else False
    ok3 = etapa("4. Baixar um clip de 4 segundos", baixar_clip) if ok1 else False

    shutil.rmtree(pasta, ignore_errors=True)
    escrever()
    escrever("=== RESULTADO")
    escrever(f"ler informações: {'OK' if ok1 else 'FALHOU'} | baixar vídeo: {'OK' if ok2 else 'FALHOU'} "
             f"| baixar clip: {'OK' if ok3 else 'FALHOU'}")


if __name__ == "__main__":
    try:
        main()
    finally:
        try:
            with open(SAIDA, "w", encoding="utf-8") as f:
                f.write("\n".join(linhas))
            print()
            print(f"Resultado gravado em: {SAIDA}")
        except OSError as erro:
            print(f"Não consegui gravar {SAIDA}: {erro}")
