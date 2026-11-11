"""
criar_icone.py
--------------
Gera os arquivos de ícone do ClipTube a partir da arte oficial:

    assets/icone_original.jpg   (arte do ClipTube, 2000x2000)

Saídas (na mesma pasta):
  * icone.png  (1024x1024, com cantos transparentes; usado dentro do app)
  * icone.ico  (vários tamanhos; usado na janela, na barra de tarefas,
                no atalho "ClipTube" e no ClipTube.exe)

O ícone do ClipTube é SEMPRE esta arte. Para trocar, substitua o
icone_original.jpg e rode:  python assets\\criar_icone.py
"""

import os
from PIL import Image, ImageDraw, ImageFilter

PASTA = os.path.dirname(os.path.abspath(__file__))
ORIGINAL = os.path.join(PASTA, "icone_original.jpg")

# A arte é um quadrado com cantos arredondados sobre fundo branco.
# Recortamos esse formato e deixamos os cantos transparentes.
RAIO = 0.197        # raio dos cantos, em proporção do tamanho (≈ 395 px em 2000 px)
RECUO = 0.003       # recuo pequeno para não sobrar borda branca


def carregar_recortado():
    arte = Image.open(ORIGINAL).convert("RGB")
    lado = min(arte.size)
    arte = arte.crop((0, 0, lado, lado))

    # Máscara desenhada em 4x e reduzida = borda suave (anti-serrilhado)
    grande = lado * 4
    mascara = Image.new("L", (grande, grande), 0)
    recuo = int(grande * RECUO)
    ImageDraw.Draw(mascara).rounded_rectangle(
        [recuo, recuo, grande - recuo, grande - recuo],
        radius=int(grande * RAIO), fill=255)
    mascara = mascara.resize((lado, lado), Image.LANCZOS)

    icone = arte.convert("RGBA")
    icone.putalpha(mascara)
    return icone


def reduzir(imagem, tamanho):
    """Reduz com boa qualidade e dá uma leve nitidez nos tamanhos pequenos."""
    menor = imagem.resize((tamanho, tamanho), Image.LANCZOS)
    if tamanho <= 64:
        menor = menor.filter(ImageFilter.UnsharpMask(radius=1, percent=60, threshold=2))
    return menor


if __name__ == "__main__":
    icone = carregar_recortado()
    reduzir(icone, 1024).save(os.path.join(PASTA, "icone.png"))

    tamanhos = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    imagens = [reduzir(icone, t) for t in tamanhos]
    imagens[-1].save(os.path.join(PASTA, "icone.ico"), format="ICO",
                     sizes=[(t, t) for t in tamanhos], append_images=imagens[:-1])
    print("Ícone gerado em", PASTA)
