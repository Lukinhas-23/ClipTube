# ClipTube

ClipTube é um app com interface gráfica que baixa vídeos do YouTube usando o yt-dlp.

## Instalação (automática na primeira vez)

Você só precisa do **Windows 10/11** (com o winget, que já vem nele) e do **Python 3.10+** (se for rodar pelo código; o `.exe` não precisa de Python).

Na primeira vez que o ClipTube abre, ele mesmo prepara tudo:

- **Bibliotecas Python** (customtkinter e pillow): instaladas com o pip, numa janelinha de andamento. No `.exe` elas já vêm dentro.
- **yt-dlp e FFmpeg**: se faltarem, o app mostra uma janela "Primeira configuração" e instala os dois com o winget quando você clica em **Instalar agora**. Se a instalação falhar, aparece o motivo e o botão **Tentar de novo**.

Depois disso, nada mais é instalado. Para abrir: `python app.py` (ou gere o `.exe`, veja abaixo).

Se preferir instalar na mão:

```
python -m pip install -r requirements.txt
winget install yt-dlp.yt-dlp
winget install yt-dlp.FFmpeg
```

### Qualidade

Depois que você cola o link, o menu **Qualidade** mostra todas as resoluções que o vídeo tem, com quadros por segundo e tamanho aproximado. Exemplo:

```
Original  •  2160p (4K)  •  60fps  •  ≈ 2.1 GB  •  converte H.264
1440p (2K)  •  60fps  •  ≈ 1.1 GB  •  converte H.264
1080p (Full HD)  •  60fps  •  ≈ 591 MB
720p (HD)  •  60fps  •  ≈ 374 MB
...
```

- O padrão é **Original**: a maior qualidade em que o vídeo foi enviado (4K, 8K etc.).
- Cada link na fila guarda a qualidade escolhida (aparece numa etiqueta, ex.: `4K`, `1080p`).
- Links colados vários de uma vez entram na qualidade **Original**.
- **"converte H.264"**: o YouTube só oferece essa resolução em VP9/AV1 (comum em 1440p e 4K). O app baixa e converte para H.264, para abrir em qualquer lugar. A conversão é feita pelo processador e leva mais ou menos 1,5x a duração do vídeo em 4K60 (um vídeo de 10 min leva ~15 min).
  - Se a placa de vídeo puder fazer a conversão, o app usa ela automaticamente (bem mais rápido). Na sua GTX 1060, isso exige **atualizar o driver da NVIDIA** (versão 610 ou mais nova).
- Se o arquivo já existir na pasta em outro formato (VP9/AV1), ele também é convertido.

## Arquivos

| Arquivo | Para que serve |
|---|---|
| `app.py` | A janela (interface, fila, prévia, barra de progresso) |
| `downloader.py` | Conversa com o yt-dlp: busca informações, baixa, traduz erros |
| `preparo.py` | Configuração da primeira vez: instala bibliotecas (pip) e yt-dlp/FFmpeg (winget) |
| `dist\ClipTube.exe` | Gerado pelo `gerar_exe.bat`: o app em um arquivo só, com ícone |
| `gerar_exe.bat` | Gera o `ClipTube.exe` (com ícone) |
| `assets\` | Ícone do app: `icone_original.jpg` (arte oficial), `icone.ico`/`icone.png` (gerados) e `criar_icone.py` |
| `requirements.txt` | Bibliotecas Python necessárias |
| `config.json` | Criado automaticamente; guarda a última pasta escolhida |

## Como usar

1. Abra o `ClipTube.exe` (veja "Gerar o .exe") ou rode `python app.py`.
2. Clique em **Colar** (ou cole com Ctrl+V) e a miniatura e o título aparecem.
3. Clique em **Baixar**.

**Fila:** para baixar vários vídeos, cole um link e clique em **+ Fila** (ou aperte Enter) para cada um.
Se você copiar vários links de uma vez (um por linha) e clicar em **Colar**, todos entram na fila direto.
Você pode adicionar links enquanto outro download está rodando. Eles são baixados um depois do outro.

- **Cancelar** interrompe o vídeo atual e pausa a fila. **Baixar** continua os que ficaram aguardando.
- Se um item der erro, passe o mouse em **"Erro ⓘ"** para ver o motivo.
- **Abrir pasta** abre a pasta de destino no Explorer. O botão fica vermelho por alguns segundos quando um download termina.

## Gerar o .exe (abrir sem terminal)

Dê dois cliques em **`gerar_exe.bat`**. Leva uns 1–2 minutos. O executável fica em:

```
dist\ClipTube.exe
```

Ou, manualmente, no terminal desta pasta:

```
python -m pip install -r requirements.txt pyinstaller
python -m PyInstaller --noconfirm --onefile --windowed --name "ClipTube" --icon "assets\icone.ico" --add-data "assets\icone.ico;assets" --add-data "assets\icone.png;assets" --collect-data customtkinter app.py
```

Você pode copiar o `.exe` para qualquer pasta (ou criar um atalho na Área de Trabalho).
O `config.json` é criado ao lado do `.exe`.

## Observações

- O app usa o **yt-dlp e o FFmpeg instalados pelo winget**. Para atualizar (resolve a maioria dos erros novos do YouTube):
  ```
  winget upgrade yt-dlp
  ```
  Não é preciso gerar o .exe de novo depois de atualizar.
- Foi adicionado `--no-playlist`: um link com `&list=...` baixa só aquele vídeo, não a playlist inteira.
- Se o YouTube recusar o download (erro 403, que acontece de vez em quando), o app tenta de novo sozinho até 3 vezes.

## Ícone

O ícone do ClipTube é sempre a arte `assets\icone_original.jpg`. Ele aparece na janela, na barra de tarefas, no atalho e no `.exe`.
Para trocar a arte, substitua esse arquivo e rode:

```
python assets\criar_icone.py
```

Depois, gere o `.exe` de novo com o `gerar_exe.bat`.
