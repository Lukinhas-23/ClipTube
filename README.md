# ClipTube

ClipTube é um app com interface gráfica que baixa vídeos do YouTube, vídeos e fotos do Instagram e gravações (VODs) e clips da Twitch, usando o yt-dlp.

## Como abrir (depois de baixar do GitHub)

1. Baixe o projeto: no GitHub clique em **Code → Download ZIP** e extraia a pasta (ou use `git clone https://github.com/Lukinhas-23/ClipTube.git`).
2. Dê dois cliques em **`ClipTube.bat`**, dentro da pasta. É o único arquivo que você precisa abrir.
3. **Na primeira vez** o `ClipTube.bat` abre uma janela preta e **instala tudo sozinho** (precisa de internet, pode levar alguns minutos; não feche a janela):
   - o **Python**, se o computador não tiver (pelo winget);
   - as bibliotecas do app (customtkinter e pillow);
   - o **yt-dlp** e o **gallery-dl** (baixam os vídeos e as fotos do Instagram), instalados como bibliotecas do Python;
   - o **FFmpeg** (converte e junta vídeo e áudio) e o **Deno** (o YouTube exige), pelo winget.
   Quando termina, o app abre. Nas próximas vezes ele abre direto, sem janela preta.
4. O `ClipTube.bat` também cria na pasta um atalho **ClipTube** com o ícone do app. Dali em diante pode abrir por esse atalho, copiá-lo para a Área de Trabalho ou fixá-lo na barra de tarefas.

Requisitos: Windows 10/11 com o **winget** (já vem no Windows 11 e no Windows 10 atualizado). Se o winget não existir, o `ClipTube.bat` explica como instalar o Python na mão.

## Instalação (o que o ClipTube.bat faz na primeira vez)

O `ClipTube.bat` chama o `preparo.py`, que confere e instala o que faltar. Se você preferir fazer na mão, ou rodar só o preparo: `python preparo.py --instalar`.

Na primeira vez que o ClipTube abre, ele mesmo prepara tudo:

- **Bibliotecas Python** (customtkinter e pillow): instaladas com o pip, numa janelinha de andamento. No `.exe` elas já vêm dentro.
- **yt-dlp e FFmpeg**: se faltarem, o app mostra uma janela "Primeira configuração" e instala os dois com o winget quando você clica em **Instalar agora**. Se a instalação falhar, aparece o motivo e o botão **Tentar de novo**.

Depois disso, nada mais é instalado. Para abrir: `ClipTube.bat` (ou `python app.py`, ou gere o `.exe`, veja abaixo).

Se preferir instalar na mão:

```
python -m pip install -r requirements.txt
winget install yt-dlp.FFmpeg
winget install DenoLand.Deno
```

**Por que o yt-dlp e o gallery-dl vão como biblioteca do Python (e não como `.exe`)?** O Windows (Controle inteligente de aplicativo / Controle de Aplicativo) bloqueia programas `.exe` que não tem assinatura digital, e isso quebrava os downloads em alguns computadores. Rodando dentro do `python.exe`, que o Windows aceita, o problema some. Se a biblioteca não estiver instalada, o app ainda tenta o `.exe` como plano B.

### Twitch (gravações inteiras da live e clips)

Cole o link de uma **gravação (VOD)** (`twitch.tv/videos/...`) ou de um **clip**:

- **Gravação inteira da live:** baixa o VOD completo, de qualquer duração (de minutos a muitas horas), em MP4 H.264 + AAC, com o menu de qualidade (1080p60, 720p60, 480p...) e o **tamanho estimado** de cada opção. Atenção: um VOD de 2 horas em 1080p60 passa de 7 GB. O app confere se há espaço no disco antes de começar e avisa se não houver.
- **Recorte de clip:** funciona também nas gravações: linha do tempo, quadros de início/fim e prévia com som, igual ao YouTube. Dá para tirar um trecho de uma live de horas sem baixar tudo.
- **Clips da Twitch:** baixam inteiros (já são curtos, até 1 minuto), sem a área de recorte.
- **Link do canal (a live ao vivo):** o app não baixa o canal e explica o que fazer: abra `twitch.tv/NOME_DO_CANAL/videos`, clique na gravação e cole esse link. **A gravação já aparece lá enquanto a live ainda está no ar** e dá para baixar até o ponto atual.
- Links de listas (`.../videos`, `.../clips`) também são recusados, para o app nunca baixar um canal inteiro sem querer.
- Gravações só para assinantes não são suportadas (o app ainda não entra com login na Twitch), e a Twitch apaga gravações antigas depois de alguns dias.
- Cancelar um download apaga os arquivos parciais.

### Instagram (vídeos, reels, stories e fotos)

Cole o link de um **post, reel ou story** do Instagram no mesmo campo. O ClipTube reconhece sozinho:

- **Vídeos e reels** baixam pelo yt-dlp, em MP4 H.264 + AAC. Se o post tiver vários vídeos, todos são baixados.
- **Fotos** (e posts com várias fotos) baixam pelo **gallery-dl**. Na primeira vez que você colar um link do Instagram, o app oferece instalar o gallery-dl com o winget (uma vez só).
- Os arquivos ficam na pasta de destino com o nome `usuario_post_número.jpg` (fotos) ou `usuario - id.mp4` (vídeos).
- No Instagram não há escolha de qualidade nem recorte de clip (isso é só do YouTube).

**Login:** o Instagram quase sempre exige uma conta logada. No menu **Login** (no lugar de "Qualidade") escolha:

- **Chrome / Edge / Firefox:** o app usa o login do navegador onde você já está logado no Instagram. Ele nunca vê nem guarda sua senha: só entrega os cookies do navegador ao yt-dlp/gallery-dl na hora de baixar. O app começa em **Sem login** e só lê um navegador depois que você escolher.
- **Arquivo cookies.txt…:** exporte os cookies do Instagram com uma extensão de navegador (por exemplo "Get cookies.txt LOCALLY") e escolha o arquivo. Use esta opção se o Chrome/Edge der erro: as versões novas desses navegadores bloqueiam a leitura dos cookies (o Firefox costuma funcionar melhor). **Nunca coloque o cookies.txt no GitHub:** quem tiver esse arquivo entra na sua conta. O `.gitignore` já ignora `cookies*.txt`.

Limites: posts de contas privadas só baixam se a conta logada seguir o perfil; perfis inteiros e destaques não são suportados; o Instagram muda com frequência, então às vezes é preciso atualizar (`python -m pip install -U yt-dlp gallery-dl`). Use só para conteúdo seu ou para uso pessoal, respeitando os direitos do autor.

### Clips (recortar um trecho)

Depois de colar o link, a área **✂ Recortar clip** mostra o vídeo inteiro numa linha do tempo com miniaturas:

- **Arraste as alças vermelhas** para escolher o início e o fim. Arraste o **meio** da faixa para mover o clip todo sem mudar o tamanho. Clicar fora leva a alça mais próxima até ali.
- Os dois quadros embaixo mostram **como é a imagem no início e no fim** do clip, com o tempo exato.
- Ajuste fino: botões **−1s / +1s** ou digite o tempo (`1:25`, `01:25.5`, `1:02:03`).
- **🔍 Ampliar trecho** dá zoom na região escolhida (e **↔ Ver tudo** volta).
- **▶ Ver prévia** abre um player que toca o clip (imagem e som) para você conferir antes de baixar. Se o clip tiver mais de 5 minutos, a prévia toca só os 5 primeiros.
- **✂ Clipar** baixa só esse trecho (não o vídeo inteiro) na pasta de destino, em **MP4 H.264 + AAC**, na qualidade escolhida no menu. O corte é exato e o arquivo se chama `Título [id] clip 01m40s-01m52s.mp4`.
- O link continua no campo depois de clipar: dá para escolher outro trecho e clipar de novo. Cada clip entra na fila com uma etiqueta do trecho.
- **Baixar** continua baixando o vídeo inteiro.

As miniaturas e a prévia vêm direto do YouTube (sem baixar o vídeo todo), então aparecem rápido.

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
| `ClipTube.bat` | **Abre o app** (dois cliques). Na primeira vez instala tudo e cria o atalho ClipTube com ícone |
| `app.py` | A janela (interface, fila, prévia, barra de progresso) |
| `downloader.py` | Conversa com o yt-dlp: busca informações, baixa, traduz erros |
| `clip_ui.py` | A área de recorte: linha do tempo, alças, quadros de início/fim e o player da prévia |
| `previas.py` | Miniaturas (storyboard), quadro exato e player da prévia, sem baixar o vídeo todo |
| `tema.py` | Cores e fonte do app |
| `instagram.py` | Regras do Instagram: links, login por cookies, erros em português |
| `twitch.py` | Regras da Twitch: gravações e clips, recusa de links de canal, erros em português |
| `diagnostico.bat` / `diagnostico.py` | Testam leitura, download e clip e gravam `diagnostico.txt` (para achar a causa de erros) |
| `preparo.py` | Instalação da primeira vez: bibliotecas (pip), yt-dlp, FFmpeg e gallery-dl (winget). Também roda sozinho: `python preparo.py --instalar` |
| `dist\ClipTube.exe` | Gerado pelo `gerar_exe.bat`: o app em um arquivo só, com ícone |
| `gerar_exe.bat` | Gera o `ClipTube.exe` (com ícone) |
| `assets\` | Ícone do app: `icone_original.jpg` (arte oficial), `icone.ico`/`icone.png` (gerados) e `criar_icone.py` |
| `requirements.txt` | Bibliotecas Python necessárias |
| `config.json` | Criado automaticamente; guarda a última pasta escolhida e o login do Instagram |

## Como usar

1. Dê dois cliques em `ClipTube.bat` (ou no atalho ClipTube que ele cria, ou no `ClipTube.exe`, veja "Gerar o .exe").
2. Clique em **Colar** (ou cole com Ctrl+V) e a miniatura e o título aparecem.
3. Clique em **Baixar**.

A pasta de destino começa em `D:\Clips IShowSpeed certa` (ou em `Vídeos\ClipTube`, se o computador não tiver disco D:). Use **Escolher pasta** para trocar; o app lembra da última escolhida.

**Fila:** para baixar vários vídeos, cole um link e clique em **+ Fila** (ou aperte Enter) para cada um.
Se você copiar vários links de uma vez (um por linha) e clicar em **Colar**, todos entram na fila direto.
Você pode adicionar links enquanto outro download está rodando. Eles são baixados um depois do outro.

- **Cancelar** interrompe o vídeo atual e pausa a fila. **Baixar** continua os que ficaram aguardando.
- Se um item der erro, passe o mouse em **"Erro ⓘ"** para ver o motivo.
- **Abrir pasta** abre a pasta de destino no Explorer. O botão fica vermelho por alguns segundos quando um download termina.

## Se der erro

1. **Clique no erro.** Na fila, clique em **"Erro ⓘ"**; na prévia, clique na mensagem vermelha. Abre uma janela com o **texto técnico completo** do erro e as versões das ferramentas. Use **Copiar tudo** e mande para quem estiver ajudando.
2. **Arquivo de erros:** todo erro fica gravado em `cliptube_erros.log`, na pasta do ClipTube (botão **Abrir arquivo de erros**).
3. **Diagnóstico:** dê dois cliques em **`diagnostico.bat`**. Ele testa ler um vídeo, baixar e criar um clip, e grava o resultado em `diagnostico.txt`. Mande esse arquivo.
4. **"O Windows bloqueou um dos programas" (erro 4551):** o Windows barra programas sem assinatura digital. O ClipTube já evita isso no yt-dlp e no gallery-dl (usa a versão em Python), mas pode acontecer com o FFmpeg ou o Deno. Se o computador é seu: Segurança do Windows → Controle de aplicativos e navegador → Configurações do Controle inteligente de aplicativo → **Desativado** (depois de desativar, só dá para ligar de novo reinstalando o Windows). Se é de empresa ou escola, peça ao administrador de TI para liberar o `ffmpeg.exe` e o `deno.exe`.

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

- O app usa o **yt-dlp** (biblioteca Python) e o **FFmpeg** (winget). Para atualizar o yt-dlp (resolve a maioria dos erros novos do YouTube):
  ```
  python -m pip install -U yt-dlp
  ```
- Foi adicionado `--no-playlist`: um link com `&list=...` baixa só aquele vídeo, não a playlist inteira.
- Se o YouTube recusar o download (erro 403, que acontece de vez em quando), o app tenta de novo sozinho até 3 vezes.

## Ícone

O ícone do ClipTube é sempre a arte `assets\icone_original.jpg`. Ele aparece na janela, na barra de tarefas, no atalho e no `.exe`.
Para trocar a arte, substitua esse arquivo e rode:

```
python assets\criar_icone.py
```

Depois, gere o `.exe` de novo com o `gerar_exe.bat`.
