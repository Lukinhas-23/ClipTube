"""
app.py
------
ClipTube — baixador de vídeos do YouTube (interface em CustomTkinter).

Como funciona, em resumo:
  * A interface roda na thread principal (o Tkinter exige isso).
  * Downloads e buscas de título/miniatura rodam em threads separadas, para a
    janela nunca travar.
  * As threads NUNCA mexem direto nos widgets: elas colocam pequenas funções
    numa fila (self._eventos) e a thread principal executa essas funções a
    cada 80 ms (método _processar_eventos).
"""

import json
import os
import re
import sys
import threading
import time
import queue

import preparo

# Na primeira vez, instala as bibliotecas que faltarem (antes de importá-las).
preparo.garantir_bibliotecas()

import customtkinter as ctk
from tkinter import filedialog

import downloader as dl

# ---------------------------------------------------------------------------
# Configurações gerais e cores
# ---------------------------------------------------------------------------
TITULO_APP = "ClipTube"
PASTA_PADRAO = r"D:\Clips IShowSpeed certa"

FONTE = "Segoe UI"
VERMELHO = "#FF0033"
VERMELHO_HOVER = "#CC0029"
FUNDO = "#0F0F0F"
CARTAO = "#1C1C1C"
CAMPO = "#272727"
BOTAO_CINZA = "#3A3A3A"
BOTAO_CINZA_HOVER = "#4A4A4A"
TEXTO = "#F1F1F1"
TEXTO_SEC = "#AAAAAA"
TEXTO_APAGADO = "#6E6E6E"     # texto de exemplo (placeholder), com pouca opacidade
VERDE = "#3DDC84"
AMARELO = "#F5C451"
ERRO = "#FF6B6B"

# Reconhece links do YouTube (vídeos, shorts, youtu.be, music...)
REGEX_URL = re.compile(r"https?://[^\s<>\"']+")
REGEX_YOUTUBE = re.compile(
    r"^https?://([a-z0-9-]+\.)?(youtube\.com|youtu\.be|youtube-nocookie\.com)/", re.I)


def pasta_do_app():
    """Pasta onde o app está (funciona tanto no .py quanto no .exe)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def recurso(caminho_relativo):
    """Caminho de um arquivo que vai junto com o app (ex.: o ícone).

    No .exe do PyInstaller esses arquivos ficam numa pasta temporária (sys._MEIPASS).
    """
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, caminho_relativo)


ARQUIVO_CONFIG = os.path.join(pasta_do_app(), "config.json")
ICONE_ICO = recurso(os.path.join("assets", "icone.ico"))
ICONE_PNG = recurso(os.path.join("assets", "icone.png"))


def carregar_config():
    try:
        with open(ARQUIVO_CONFIG, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def salvar_config(config):
    try:
        with open(ARQUIVO_CONFIG, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
    except Exception:
        pass  # não conseguir salvar a config não deve quebrar o app


def eh_link_youtube(texto):
    return bool(REGEX_YOUTUBE.match(texto.strip()))


def formatar_tamanho(bytes_por_seg):
    if not bytes_por_seg:
        return "--"
    for unidade in ("B/s", "KB/s", "MB/s", "GB/s"):
        if bytes_por_seg < 1024:
            return f"{bytes_por_seg:.1f} {unidade}"
        bytes_por_seg /= 1024
    return f"{bytes_por_seg:.1f} TB/s"


def formatar_tempo(segundos):
    if segundos is None:
        return "--:--"
    segundos = int(segundos)
    h, resto = divmod(segundos, 3600)
    m, s = divmod(resto, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def formatar_bytes(n):
    if not n:
        return ""
    for unidade in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unidade}" if unidade != "GB" else f"{n:.1f} GB"
        n /= 1024
    return f"{n:.1f} TB"


QUALIDADE_PADRAO = "Melhor disponível (qualidade original)"


def montar_opcoes_qualidade(qualidades):
    """Transforma a lista de resoluções do vídeo em textos para o menu.

    Retorna lista de (texto, limite_res, rotulo_curto). limite_res None = original.
    """
    opcoes = []
    for i, q in enumerate(qualidades):
        partes = [dl.nome_resolucao(q["res"])]
        if q["fps"] > 30:
            partes.append(f"{q['fps']}fps")
        if q["tamanho"]:
            partes.append(f"≈ {formatar_bytes(q['tamanho'])}")
        if not q["h264"]:
            partes.append("converte H.264")
        texto = "  •  ".join(partes)
        curto = dl.NOMES_RESOLUCAO.get(q["res"]) or f"{q['res']}p"
        if q["res"] in (1080, 720):
            curto = f"{q['res']}p"
        if i == 0:
            opcoes.append((f"Original  •  {texto}", None, f"Original {curto}"))
        else:
            opcoes.append((texto, q["res"], curto))
    return opcoes


def encurtar(texto, limite):
    return texto if len(texto) <= limite else texto[:limite - 1] + "…"


# ---------------------------------------------------------------------------
# Item da fila de downloads
# ---------------------------------------------------------------------------
class ItemFila:
    # status possíveis: aguardando, baixando, concluido, erro, cancelado
    TEXTOS = {
        "aguardando": ("Aguardando", TEXTO_SEC),
        "baixando": ("Baixando...", AMARELO),
        "concluido": ("Concluído", VERDE),
        "ja_existia": ("Já estava na pasta", VERDE),
        "erro": ("Erro", ERRO),
        "cancelado": ("Cancelado", TEXTO_SEC),
    }

    def __init__(self, url, limite_res=None, rotulo_qualidade="Original"):
        self.url = url
        self.limite_res = limite_res              # None = qualidade original
        self.rotulo_qualidade = rotulo_qualidade  # texto curto mostrado na fila
        self.titulo = None
        self.status = "aguardando"
        self.mensagem = ""          # detalhe do erro, se houver
        self.widgets = None         # (frame, label_titulo, label_status, botao_remover, label_qualidade)


# ---------------------------------------------------------------------------
# Janela principal
# ---------------------------------------------------------------------------
class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        ctk.set_appearance_mode("dark")
        self.title(TITULO_APP)
        self._aplicar_icone()
        self.geometry("700x610")
        self.minsize(660, 570)
        self.configure(fg_color=FUNDO)

        # Estado
        self.config_app = carregar_config()
        self.pasta = self.config_app.get("pasta") or PASTA_PADRAO
        self.fila = []
        self.trabalhando = False
        self.baixador = dl.Baixador()
        self._eventos = queue.Queue()
        self._cache_info = {}                       # url -> dict de info
        self._limite_buscas = threading.Semaphore(2)  # no máx. 2 buscas de info juntas
        self._token_previa = 0
        self._ultimo_link = ""
        self._opcoes_qualidade = []   # [(texto, limite_res, rotulo_curto)] do link atual
        self._agendamento_previa = None
        self._imagem_previa = None
        # Imagem "vazia" usada quando não há miniatura. (Remover a imagem de um
        # CTkLabel depois de já ter mostrado uma causa erro no CustomTkinter.)
        from PIL import Image
        vazia = Image.new("RGB", (128, 72), CAMPO)
        self._imagem_vazia = ctk.CTkImage(light_image=vazia, dark_image=vazia, size=(128, 72))

        self._montar_interface()
        self._id_eventos = self.after(80, self._processar_eventos)
        self.protocol("WM_DELETE_WINDOW", self._ao_fechar)

        # Primeira execução: confere se yt-dlp e FFmpeg estão instalados.
        preparo.atualizar_path()
        faltando = preparo.ferramentas_faltando()
        if faltando:
            self.after(300, lambda: self._abrir_instalacao(faltando))

    # ------------------------------------------------- instalação das ferramentas
    def _abrir_instalacao(self, faltando):
        """Janela que oferece instalar yt-dlp / FFmpeg com o winget."""
        nomes = " e ".join(nome for _, nome in faltando)
        self._definir_status(f"Faltam programas necessários: {nomes}.", AMARELO)
        self.botao_baixar.configure(state="disabled")

        janela = ctk.CTkToplevel(self)
        janela.title("ClipTube — primeira configuração")
        janela.geometry("460x250")
        janela.resizable(False, False)
        janela.configure(fg_color=FUNDO)
        janela.transient(self)
        janela.after(200, janela.grab_set)
        janela.after(250, lambda: janela.iconbitmap(ICONE_ICO) if os.path.isfile(ICONE_ICO) else None)
        janela.protocol("WM_DELETE_WINDOW", lambda: None)   # só fecha pelos botões

        ctk.CTkLabel(janela, text="Primeira configuração", text_color=TEXTO,
                     font=(FONTE, 18, "bold")).pack(pady=(18, 4))
        texto = ctk.CTkLabel(
            janela, text=f"O ClipTube precisa de: {nomes}.\n"
                         "Posso instalar para você agora "
                         "(usa o winget, pode demorar alguns minutos).",
            text_color=TEXTO_SEC, font=(FONTE, 13), justify="center", wraplength=410)
        texto.pack(padx=20)
        andamento = ctk.CTkLabel(janela, text="", text_color=AMARELO, font=(FONTE, 12),
                                 wraplength=410)
        andamento.pack(pady=(10, 4))
        barra = ctk.CTkProgressBar(janela, mode="indeterminate", progress_color=VERMELHO,
                                   fg_color=CAMPO, height=8)

        botoes = ctk.CTkFrame(janela, fg_color="transparent")
        botoes.pack(side="bottom", pady=16)
        botao_instalar = ctk.CTkButton(botoes, text="Instalar agora", width=150, height=38,
                                       fg_color=VERMELHO, hover_color=VERMELHO_HOVER,
                                       font=(FONTE, 14, "bold"))
        botao_sair = ctk.CTkButton(botoes, text="Agora não", width=110, height=38,
                                   fg_color=BOTAO_CINZA, hover_color=BOTAO_CINZA_HOVER,
                                   font=(FONTE, 13))
        botao_instalar.pack(side="left", padx=6)
        botao_sair.pack(side="left", padx=6)

        def fechar(concluido):
            barra.stop()
            janela.grab_release()
            janela.destroy()
            if concluido:
                self.botao_baixar.configure(state="normal")
                self._definir_status("Tudo pronto! Cole um link para começar.", VERDE)
            else:
                self._definir_status("Instale yt-dlp e FFmpeg para poder baixar "
                                     "(winget install yt-dlp.yt-dlp yt-dlp.FFmpeg).", ERRO)

        def terminou(ok, mensagem):
            barra.stop()
            if ok:
                fechar(True)
                return
            andamento.configure(text=mensagem, text_color=ERRO)
            botao_instalar.configure(state="normal", text="Tentar de novo")
            botao_sair.configure(state="normal", text="Fechar")

        def instalar():
            botao_instalar.configure(state="disabled")
            botao_sair.configure(state="disabled")
            andamento.configure(text="Começando...", text_color=AMARELO)
            barra.pack(fill="x", padx=30, pady=(0, 4))
            barra.start()

            def tarefa():
                ok, msg = preparo.instalar_ferramentas(
                    preparo.ferramentas_faltando(),
                    ao_log=lambda t: self._na_ui(
                        lambda: andamento.configure(text=t, text_color=AMARELO)))
                self._na_ui(terminou, ok, msg)
            threading.Thread(target=tarefa, daemon=True).start()

        botao_instalar.configure(command=instalar)
        botao_sair.configure(command=lambda: fechar(False))

    def _aplicar_icone(self):
        """Coloca o ícone do ClipTube na janela e na barra de tarefas."""
        try:
            # Sem isso, o Windows agrupa o app como "Python" e mostra o ícone do Python.
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ClipTube.App")
        except Exception:
            pass
        if os.path.isfile(ICONE_ICO):
            self.iconbitmap(ICONE_ICO)

    # ------------------------------------------------------------------ UI
    def _montar_interface(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(5, weight=1)   # a fila ocupa o espaço que sobrar
        px = 16

        # --- Cabeçalho -----------------------------------------------------
        topo = ctk.CTkFrame(self, fg_color="transparent")
        topo.grid(row=0, column=0, sticky="ew", padx=px, pady=(14, 8))
        if os.path.isfile(ICONE_PNG):
            from PIL import Image
            logo = Image.open(ICONE_PNG)
            self._logo = ctk.CTkImage(light_image=logo, dark_image=logo, size=(34, 34))
            ctk.CTkLabel(topo, text="", image=self._logo).pack(side="left")
        ctk.CTkLabel(topo, text="  Clip", text_color=TEXTO,
                     font=(FONTE, 22, "bold")).pack(side="left")
        ctk.CTkLabel(topo, text="Tube", text_color=VERMELHO,
                     font=(FONTE, 22, "bold")).pack(side="left")
        ctk.CTkLabel(topo, text="   baixador de vídeos do YouTube", text_color=TEXTO_SEC,
                     font=(FONTE, 12)).pack(side="left", pady=(6, 0))

        # --- Cartão do link + prévia --------------------------------------
        cartao_link = ctk.CTkFrame(self, fg_color=CARTAO, corner_radius=14)
        cartao_link.grid(row=1, column=0, sticky="ew", padx=px, pady=4)
        cartao_link.grid_columnconfigure(0, weight=1)

        # Obs.: o campo NÃO usa textvariable, porque com ela o CustomTkinter não
        # mostra o texto de exemplo (placeholder).
        self.campo_link = ctk.CTkEntry(
            cartao_link, height=38, corner_radius=10,
            placeholder_text="Cole aqui a url do vídeo",
            placeholder_text_color=TEXTO_APAGADO,
            fg_color=CAMPO, border_width=0, font=(FONTE, 13))
        self.campo_link.grid(row=0, column=0, sticky="ew", padx=(12, 6), pady=(12, 8))
        self.campo_link.bind("<Return>", lambda e: self._adicionar_link_digitado())
        self.campo_link.bind("<KeyRelease>", lambda e: self._agendar_previa())

        ctk.CTkButton(cartao_link, text="Colar", width=72, height=38, corner_radius=10,
                      fg_color=BOTAO_CINZA, hover_color=BOTAO_CINZA_HOVER,
                      font=(FONTE, 13), command=self._colar).grid(
            row=0, column=1, padx=3, pady=(12, 8))
        ctk.CTkButton(cartao_link, text="+ Fila", width=72, height=38, corner_radius=10,
                      fg_color=BOTAO_CINZA, hover_color=BOTAO_CINZA_HOVER,
                      font=(FONTE, 13), command=self._adicionar_link_digitado).grid(
            row=0, column=2, padx=(3, 12), pady=(12, 8))

        # Prévia: miniatura à esquerda, título e detalhes à direita
        previa = ctk.CTkFrame(cartao_link, fg_color="transparent")
        previa.grid(row=1, column=0, columnspan=3, sticky="ew", padx=12, pady=(0, 12))
        previa.grid_columnconfigure(1, weight=1)

        self.label_miniatura = ctk.CTkLabel(
            previa, text="sem prévia", image=self._imagem_vazia, compound="center",
            width=128, height=72, corner_radius=8,
            fg_color=CAMPO, text_color=TEXTO_SEC, font=(FONTE, 11))
        self.label_miniatura.grid(row=0, column=0, rowspan=3, sticky="w")

        self.label_titulo = ctk.CTkLabel(
            previa, text="Cole um link para ver o título e a miniatura do vídeo.",
            anchor="w", justify="left", wraplength=470, text_color=TEXTO,
            font=(FONTE, 14, "bold"))
        self.label_titulo.grid(row=0, column=1, sticky="sw", padx=(12, 0))
        self.label_detalhes = ctk.CTkLabel(
            previa, text="", anchor="w", text_color=TEXTO_SEC, font=(FONTE, 12))
        self.label_detalhes.grid(row=1, column=1, sticky="nw", padx=(12, 0))

        linha_qualidade = ctk.CTkFrame(previa, fg_color="transparent")
        linha_qualidade.grid(row=2, column=1, sticky="ew", padx=(12, 0), pady=(4, 0))
        ctk.CTkLabel(linha_qualidade, text="Qualidade:", text_color=TEXTO_SEC,
                     font=(FONTE, 12)).pack(side="left", padx=(0, 6))
        self.menu_qualidade = ctk.CTkOptionMenu(
            linha_qualidade, values=[QUALIDADE_PADRAO], width=200, height=28,
            corner_radius=8, fg_color=CAMPO, button_color=BOTAO_CINZA,
            button_hover_color=BOTAO_CINZA_HOVER, dropdown_fg_color=CARTAO,
            dropdown_hover_color=BOTAO_CINZA, font=(FONTE, 12), dropdown_font=(FONTE, 12),
            dynamic_resizing=False, state="disabled")
        self.menu_qualidade.pack(side="left", fill="x", expand=True)

        # --- Pasta de destino --------------------------------------------
        cartao_pasta = ctk.CTkFrame(self, fg_color=CARTAO, corner_radius=14)
        cartao_pasta.grid(row=2, column=0, sticky="ew", padx=px, pady=4)
        cartao_pasta.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(cartao_pasta, text="📁", font=(FONTE, 16)).grid(
            row=0, column=0, padx=(12, 4), pady=10)
        self.var_pasta = ctk.StringVar(value=self.pasta)
        ctk.CTkEntry(cartao_pasta, textvariable=self.var_pasta, state="readonly",
                     height=34, corner_radius=10, fg_color=CAMPO, border_width=0,
                     font=(FONTE, 12)).grid(row=0, column=1, sticky="ew", pady=10)
        ctk.CTkButton(cartao_pasta, text="Escolher pasta", width=118, height=34,
                      corner_radius=10, fg_color=BOTAO_CINZA, hover_color=BOTAO_CINZA_HOVER,
                      font=(FONTE, 13), command=self._escolher_pasta).grid(
            row=0, column=2, padx=(6, 3), pady=10)
        self.botao_abrir = ctk.CTkButton(
            cartao_pasta, text="Abrir pasta", width=100, height=34, corner_radius=10,
            fg_color=BOTAO_CINZA, hover_color=BOTAO_CINZA_HOVER, font=(FONTE, 13),
            command=self._abrir_pasta)
        self.botao_abrir.grid(row=0, column=3, padx=(3, 12), pady=10)

        # --- Botões Baixar / Cancelar ------------------------------------
        acoes = ctk.CTkFrame(self, fg_color="transparent")
        acoes.grid(row=3, column=0, sticky="ew", padx=px, pady=(8, 4))
        acoes.grid_columnconfigure(0, weight=1)
        self.botao_baixar = ctk.CTkButton(
            acoes, text="↓  Baixar", height=48, corner_radius=12,
            fg_color=VERMELHO, hover_color=VERMELHO_HOVER,
            font=(FONTE, 17, "bold"), command=self._clicar_baixar)
        self.botao_baixar.grid(row=0, column=0, sticky="ew")
        self.botao_cancelar = ctk.CTkButton(
            acoes, text="Cancelar", width=110, height=48, corner_radius=12,
            fg_color=BOTAO_CINZA, hover_color=BOTAO_CINZA_HOVER,
            font=(FONTE, 13), state="disabled", command=self._cancelar)
        self.botao_cancelar.grid(row=0, column=1, padx=(8, 0))

        # --- Progresso ----------------------------------------------------
        prog = ctk.CTkFrame(self, fg_color="transparent")
        prog.grid(row=4, column=0, sticky="ew", padx=px, pady=(4, 2))
        prog.grid_columnconfigure(0, weight=1)
        self.label_status = ctk.CTkLabel(prog, text="Pronto.", anchor="w",
                                         text_color=TEXTO_SEC, font=(FONTE, 13))
        self.label_status.grid(row=0, column=0, sticky="w")
        self.label_numeros = ctk.CTkLabel(prog, text="", anchor="e",
                                          text_color=TEXTO_SEC, font=(FONTE, 12))
        self.label_numeros.grid(row=0, column=1, sticky="e")
        self.barra = ctk.CTkProgressBar(prog, height=10, corner_radius=5,
                                        progress_color=VERMELHO, fg_color=CAMPO)
        self.barra.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(2, 0))
        self.barra.set(0)

        # --- Fila de downloads -------------------------------------------
        cartao_fila = ctk.CTkFrame(self, fg_color=CARTAO, corner_radius=14)
        cartao_fila.grid(row=5, column=0, sticky="nsew", padx=px, pady=(8, 14))
        cartao_fila.grid_columnconfigure(0, weight=1)
        cartao_fila.grid_rowconfigure(1, weight=1)

        self.label_fila = ctk.CTkLabel(cartao_fila, text="Fila de downloads (0)",
                                       anchor="w", text_color=TEXTO,
                                       font=(FONTE, 13, "bold"))
        self.label_fila.grid(row=0, column=0, sticky="w", padx=14, pady=(8, 2))
        ctk.CTkButton(cartao_fila, text="Limpar finalizados", width=130, height=26,
                      corner_radius=8, fg_color="transparent", hover_color=BOTAO_CINZA,
                      text_color=TEXTO_SEC, font=(FONTE, 12),
                      command=self._limpar_finalizados).grid(
            row=0, column=1, padx=8, pady=(8, 2))

        self.lista = ctk.CTkScrollableFrame(cartao_fila, fg_color="transparent",
                                            corner_radius=0, height=80)
        self.lista.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=6, pady=(0, 8))
        self.lista.grid_columnconfigure(0, weight=1)
        self.label_fila_vazia = ctk.CTkLabel(
            self.lista, text="Nenhum link na fila. Cole vários links e clique em “+ Fila”.",
            text_color=TEXTO_SEC, font=(FONTE, 12))
        self.label_fila_vazia.grid(row=0, column=0, pady=8)

    # ------------------------------------------------- comunicação threads
    def _na_ui(self, funcao, *args):
        """Chamado pelas threads: agenda `funcao(*args)` na thread da interface."""
        self._eventos.put((funcao, args))

    def _processar_eventos(self):
        # Processa no máximo 200 eventos por vez, para a janela sempre ter
        # tempo de se redesenhar (mesmo que chegue muita coisa de uma vez).
        for _ in range(200):
            try:
                funcao, args = self._eventos.get_nowait()
            except queue.Empty:
                break
            funcao(*args)
        self._id_eventos = self.after(80, self._processar_eventos)

    # --------------------------------------------------------- status/progr.
    def _definir_status(self, texto, cor=TEXTO_SEC):
        self.label_status.configure(text=texto, text_color=cor)

    def _resetar_progresso(self):
        self.barra.set(0)
        self.label_numeros.configure(text="")

    def _atualizar_progresso(self, item, dados):
        pct = dados.get("percentual")
        if pct is not None:
            self.barra.set(max(0.0, min(1.0, pct)))
            texto_pct = f"{pct * 100:.0f}%"
            item.mensagem = texto_pct
            self._atualizar_linha(item)
        else:
            texto_pct = "--%"
        self.label_numeros.configure(
            text=f"{texto_pct}   •   {formatar_tamanho(dados.get('velocidade'))}"
                 f"   •   resta {formatar_tempo(dados.get('restante'))}")

    # ---------------------------------------------------------------- prévia
    def _ler_link(self):
        return self.campo_link.get().strip()

    def _definir_link(self, texto):
        self.campo_link.delete(0, "end")
        if texto:
            self.campo_link.insert(0, texto)
            self.campo_link.icursor("end")
        self._agendar_previa()

    def _agendar_previa(self):
        """Espera o usuário parar de digitar/colar (500 ms) antes de buscar."""
        if self._ler_link() == self._ultimo_link:
            return  # o texto não mudou (ex.: só apertou uma seta)
        self._ultimo_link = self._ler_link()
        if self._agendamento_previa:
            self.after_cancel(self._agendamento_previa)
        self._agendamento_previa = self.after(500, self._buscar_previa)

    def _buscar_previa(self):
        self._agendamento_previa = None
        url = self._ler_link()
        self._token_previa += 1
        token = self._token_previa

        if not url:
            self._mostrar_previa_vazia()
            return
        if not eh_link_youtube(url):
            self._mostrar_previa_vazia("Link inválido. Use um link do YouTube "
                                       "(youtube.com ou youtu.be).", ERRO)
            return

        self.label_titulo.configure(text="Buscando informações do vídeo...", text_color=TEXTO_SEC)
        self.label_detalhes.configure(text="")
        self.label_miniatura.configure(image=self._imagem_vazia, text="carregando...")
        self._resetar_qualidades("Carregando qualidades...")

        def tarefa():
            try:
                info = self._obter_info_com_cache(url)
                imagem = dl.baixar_miniatura(info.get("miniatura"))
                self._na_ui(self._mostrar_previa, token, info, imagem)
            except dl.ErroDownload as e:
                self._na_ui(self._mostrar_erro_previa, token, str(e))
            except Exception as e:
                self._na_ui(self._mostrar_erro_previa, token, f"Erro ao ler o vídeo: {e}")

        threading.Thread(target=tarefa, daemon=True).start()

    def _obter_info_com_cache(self, url):
        if url not in self._cache_info:
            with self._limite_buscas:
                self._cache_info[url] = dl.obter_info(url)
        return self._cache_info[url]

    def _mostrar_previa_vazia(self, texto="Cole um link para ver o título e a miniatura do vídeo.",
                              cor=TEXTO):
        self.label_miniatura.configure(image=self._imagem_vazia, text="sem prévia")
        self._imagem_previa = None
        self.label_titulo.configure(text=texto, text_color=cor)
        self.label_detalhes.configure(text="")
        self._resetar_qualidades()

    def _resetar_qualidades(self, texto=QUALIDADE_PADRAO):
        self._opcoes_qualidade = []
        self.menu_qualidade.configure(values=[texto], state="disabled")
        self.menu_qualidade.set(texto)

    def _qualidade_escolhida(self):
        """Retorna (limite_res, rotulo_curto) da opção selecionada no menu."""
        atual = self.menu_qualidade.get()
        for texto, limite, curto in self._opcoes_qualidade:
            if texto == atual:
                return limite, curto
        return None, "Original"

    def _mostrar_previa(self, token, info, imagem):
        if token != self._token_previa:
            return  # o usuário já colou outro link; ignora o resultado antigo
        self.label_titulo.configure(text=encurtar(info["titulo"], 110), text_color=TEXTO)
        partes = [p for p in (info.get("canal"),
                              formatar_tempo(info["duracao"]) if info.get("duracao") else None) if p]
        self.label_detalhes.configure(text="   •   ".join(partes))
        self._opcoes_qualidade = montar_opcoes_qualidade(info.get("qualidades") or [])
        if self._opcoes_qualidade:
            textos = [t for t, _, _ in self._opcoes_qualidade]
            self.menu_qualidade.configure(values=textos, state="normal")
            self.menu_qualidade.set(textos[0])   # padrão: qualidade original do vídeo
        else:
            self._resetar_qualidades()
        if imagem is not None:
            self._imagem_previa = ctk.CTkImage(light_image=imagem, dark_image=imagem, size=(128, 72))
            self.label_miniatura.configure(image=self._imagem_previa, text="")
        else:
            self.label_miniatura.configure(image=self._imagem_vazia, text="sem miniatura")

    def _mostrar_erro_previa(self, token, mensagem):
        if token != self._token_previa:
            return
        self._mostrar_previa_vazia(mensagem, ERRO)

    # ----------------------------------------------------------- link/fila
    def _colar(self):
        """Pega o texto da área de transferência. Se tiver vários links, vão todos para a fila."""
        try:
            texto = self.clipboard_get()
        except Exception:
            self._definir_status("A área de transferência está vazia.", AMARELO)
            return
        links = REGEX_URL.findall(texto)
        if len(links) > 1:
            adicionados = self._adicionar_links(links)
            self._definir_status(f"{adicionados} links adicionados à fila.", VERDE)
        else:
            self._definir_link((links[0] if links else texto).strip())

    def _adicionar_link_digitado(self):
        url = self._ler_link()
        if not url:
            self._definir_status("Cole um link primeiro.", AMARELO)
            return False
        if not eh_link_youtube(url):
            self._definir_status("Link inválido. Use um link do YouTube.", ERRO)
            return False
        limite, curto = self._qualidade_escolhida()
        self._adicionar_links([url], limite, curto)
        self._definir_link("")
        self._definir_status(f"Link adicionado à fila ({curto}).", TEXTO_SEC)
        return True

    def _adicionar_links(self, links, limite_res=None, rotulo="Original"):
        """Adiciona links do YouTube à fila (ignora repetidos que ainda não foram baixados)."""
        pendentes = {i.url for i in self.fila if i.status in ("aguardando", "baixando")}
        adicionados = 0
        for url in links:
            url = url.strip()
            if not eh_link_youtube(url) or url in pendentes:
                continue
            item = ItemFila(url, limite_res, rotulo)
            self.fila.append(item)
            pendentes.add(url)
            self._criar_linha(item)
            self._buscar_titulo_item(item)
            adicionados += 1
        self._atualizar_contador()
        return adicionados

    def _buscar_titulo_item(self, item):
        """Busca o título de um item da fila em segundo plano."""
        def tarefa():
            try:
                info = self._obter_info_com_cache(item.url)
                item.titulo = info["titulo"]
                self._na_ui(self._ao_receber_titulo, item)
            except Exception:
                pass  # se falhar, a linha continua mostrando o link
        threading.Thread(target=tarefa, daemon=True).start()

    def _ao_receber_titulo(self, item):
        self._atualizar_linha(item)
        if item.status == "baixando":
            self._mostrar_etapa(item)   # atualiza a linha de status com o título

    def _criar_linha(self, item):
        self.label_fila_vazia.grid_remove()
        linha = ctk.CTkFrame(self.lista, fg_color=CAMPO, corner_radius=8, height=34)
        linha.grid(column=0, sticky="ew", pady=2, padx=2)
        linha.grid_columnconfigure(0, weight=1)
        titulo = ctk.CTkLabel(linha, text="", anchor="w", text_color=TEXTO, font=(FONTE, 12))
        titulo.grid(row=0, column=0, sticky="ew", padx=(10, 6), pady=4)
        qualidade = ctk.CTkLabel(linha, text=item.rotulo_qualidade, text_color=TEXTO_SEC,
                                 fg_color=BOTAO_CINZA, corner_radius=6, height=20,
                                 font=(FONTE, 11))
        qualidade.grid(row=0, column=1, padx=4)
        status = ctk.CTkLabel(linha, text="", anchor="e", font=(FONTE, 12, "bold"))
        status.grid(row=0, column=2, padx=6)
        remover = ctk.CTkButton(linha, text="✕", width=26, height=24, corner_radius=6,
                                fg_color="transparent", hover_color=BOTAO_CINZA,
                                text_color=TEXTO_SEC, command=lambda: self._remover_item(item))
        remover.grid(row=0, column=3, padx=(0, 6))
        item.widgets = (linha, titulo, status, remover, qualidade)
        self._atualizar_linha(item)

    def _atualizar_linha(self, item):
        if not item.widgets:
            return
        _, titulo, status, remover, _ = item.widgets
        titulo.configure(text=encurtar(item.titulo or item.url, 48))
        texto, cor = ItemFila.TEXTOS[item.status]
        if item.status == "baixando" and item.mensagem:
            texto = f"Baixando {item.mensagem}"
        elif item.status == "erro" and item.mensagem:
            texto = "Erro ⓘ"
        status.configure(text=texto, text_color=cor)
        # Mostra o detalhe do erro ao passar o mouse
        if item.status == "erro":
            status.bind("<Enter>", lambda e: self._definir_status(item.mensagem, ERRO))
        remover.configure(state="disabled" if item.status == "baixando" else "normal")

    def _remover_item(self, item):
        if item.status == "baixando":
            return
        self.fila.remove(item)
        if item.widgets:
            item.widgets[0].destroy()
        self._atualizar_contador()

    def _limpar_finalizados(self):
        for item in [i for i in self.fila if i.status not in ("aguardando", "baixando")]:
            self._remover_item(item)

    def _atualizar_contador(self):
        pendentes = sum(1 for i in self.fila if i.status in ("aguardando", "baixando"))
        self.label_fila.configure(
            text=f"Fila de downloads ({len(self.fila)})"
                 + (f"  •  {pendentes} pendente(s)" if pendentes else ""))
        if not self.fila:
            self.label_fila_vazia.grid()

    # ---------------------------------------------------------------- pasta
    def _escolher_pasta(self):
        inicial = self.pasta if os.path.isdir(self.pasta) else os.path.expanduser("~")
        escolhida = filedialog.askdirectory(title="Escolha a pasta de destino", initialdir=inicial)
        if escolhida:
            self.pasta = os.path.normpath(escolhida)
            self.var_pasta.set(self.pasta)
            self.config_app["pasta"] = self.pasta
            salvar_config(self.config_app)   # lembra da pasta na próxima vez

    def _abrir_pasta(self):
        try:
            os.makedirs(self.pasta, exist_ok=True)
            os.startfile(self.pasta)
        except Exception as e:
            self._definir_status(f"Não foi possível abrir a pasta: {e}", ERRO)

    # -------------------------------------------------------------- download
    def _clicar_baixar(self):
        # Se tem link no campo, coloca na fila primeiro
        if self._ler_link():
            if not self._adicionar_link_digitado():
                return
        if not any(i.status == "aguardando" for i in self.fila):
            if not self.trabalhando:
                self._definir_status("Cole um link do YouTube primeiro.", AMARELO)
            return
        self._iniciar_fila()

    def _iniciar_fila(self):
        if self.trabalhando:
            return  # já está baixando; os novos itens entram na sequência
        self.trabalhando = True
        self.botao_cancelar.configure(state="normal")
        self.botao_baixar.configure(text="↓  Baixando... (pode adicionar mais links)")
        threading.Thread(target=self._trabalhador, daemon=True).start()

    def _trabalhador(self):
        """Roda em uma thread separada: baixa os itens da fila, um de cada vez."""
        baixados, erros = 0, 0
        while True:
            item = next((i for i in self.fila if i.status == "aguardando"), None)
            if item is None:
                break
            pasta = self.pasta
            item.status, item.mensagem = "baixando", ""
            self._na_ui(self._ao_iniciar_item, item)
            ultimo_envio = [0.0]

            def ao_progresso(dados, it=item):
                # O yt-dlp manda centenas de atualizações por segundo; repassamos
                # para a tela no máximo ~10 por segundo (e sempre o 100%).
                agora = time.monotonic()
                pct = dados.get("percentual") or 0
                if agora - ultimo_envio[0] >= 0.1 or pct >= 0.999:
                    ultimo_envio[0] = agora
                    self._na_ui(self._atualizar_progresso, it, dados)

            try:
                resultado = self.baixador.baixar(
                    item.url, pasta,
                    ao_progresso=ao_progresso,
                    ao_etapa=lambda t, it=item: self._na_ui(self._mostrar_etapa, it, t),
                    limite_res=item.limite_res,
                )
                item.status = "ja_existia" if resultado == "ja_existia" else "concluido"
                item.mensagem = ""
                baixados += 1
            except dl.Cancelado:
                item.status, item.mensagem = "cancelado", ""
                self._na_ui(self._atualizar_linha, item)
                self._na_ui(self._ao_terminar_fila, baixados, erros, True)
                return
            except dl.ErroDownload as e:
                item.status, item.mensagem = "erro", str(e)
                erros += 1
            except Exception as e:
                item.status, item.mensagem = "erro", f"Erro inesperado: {e}"
                erros += 1
            self._na_ui(self._ao_terminar_item, item)

        self._na_ui(self._ao_terminar_fila, baixados, erros, False)

    def _mostrar_etapa(self, item, etapa=None):
        """Mostra a etapa atual ("Baixando vídeo...") junto com o título do vídeo."""
        if etapa:
            self._etapa_atual = etapa
        etapa = getattr(self, "_etapa_atual", "Preparando...")
        titulo = encurtar(item.titulo or item.url, 55)
        self._definir_status(f"{etapa}   {titulo}", AMARELO)

    def _ao_iniciar_item(self, item):
        self._resetar_progresso()
        self._mostrar_etapa(item, "Preparando...")
        self._atualizar_linha(item)
        self._atualizar_contador()

    def _ao_terminar_item(self, item):
        self._atualizar_linha(item)
        self._atualizar_contador()
        if item.status == "erro":
            self._definir_status(item.mensagem, ERRO)
        else:
            self.barra.set(1)
            self._definir_status("Concluído!" if item.status == "concluido"
                                 else "Concluído! (o vídeo já estava na pasta)", VERDE)

    def _ao_terminar_fila(self, baixados, erros, cancelado):
        self.trabalhando = False
        self.botao_cancelar.configure(state="disabled", text="Cancelar")
        self.botao_baixar.configure(text="↓  Baixar")
        self._atualizar_contador()
        if cancelado:
            self._resetar_progresso()
            self._definir_status("Download cancelado. Clique em Baixar para continuar a fila.",
                                 AMARELO)
            return
        if erros and baixados:
            self._definir_status(f"Concluído! {baixados} baixado(s), {erros} com erro "
                                 "(passe o mouse em “Erro ⓘ” para ver o motivo).", AMARELO)
        elif erros:
            ultimo = next((i for i in reversed(self.fila) if i.status == "erro"), None)
            self._definir_status(ultimo.mensagem if ultimo else "Erro no download.", ERRO)
        else:
            self._definir_status(
                "Concluído!" if baixados <= 1 else f"Concluído! {baixados} vídeos baixados.",
                VERDE)
        if baixados:
            # Destaca o botão "Abrir pasta" depois de um download bem-sucedido
            self.botao_abrir.configure(fg_color=VERMELHO, hover_color=VERMELHO_HOVER)
            self.after(6000, lambda: self.botao_abrir.configure(
                fg_color=BOTAO_CINZA, hover_color=BOTAO_CINZA_HOVER))

    def _cancelar(self):
        self.botao_cancelar.configure(state="disabled", text="Cancelando...")
        threading.Thread(target=self.baixador.cancelar, daemon=True).start()

    def _ao_fechar(self):
        if self.trabalhando:
            self.baixador.cancelar()
        self.after_cancel(self._id_eventos)
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
