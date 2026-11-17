"""
clip_ui.py
----------
A área "Recortar clip" do ClipTube:

  * Linha do tempo com miniaturas do vídeo inteiro e duas alças vermelhas
    (arraste as pontas para mudar o início/fim, ou arraste o meio para mover
    o clip todo sem mudar o tamanho).
  * Dois quadros de prévia: o que aparece no INÍCIO e no FIM do clip.
  * Botões de ±1 s e campos de tempo para acertar no detalhe.
  * "Ampliar": dá zoom na região escolhida, para ajustar com precisão.
  * "Ver prévia": abre um player que toca o clip (imagem e som) antes de baixar.

As imagens vêm do previas.py (miniaturas do YouTube e FFmpeg), sem baixar o
vídeo inteiro.
"""

import queue
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor

import customtkinter as ctk
from PIL import Image, ImageEnhance, ImageOps, ImageTk

import previas
from tema import (AMARELO, BOTAO_CINZA, BOTAO_CINZA_HOVER, CAMPO, CARTAO, ERRO, FONTE,
                  TEXTO, TEXTO_APAGADO, TEXTO_SEC, VERMELHO, VERMELHO_HOVER)

# Medidas (em pixels "normais"; são ajustadas à escala do Windows)
ALT_TIRA = 48          # altura da faixa de miniaturas
ALT_REGUA = 16         # altura da régua de tempo, logo abaixo
ALT_CAIXA = 80         # altura dos quadros de prévia (início/fim)
LARG_ALCA = 10         # largura das alças vermelhas
MIN_CLIP = 1.0         # menor clip permitido, em segundos


# ---------------------------------------------------------------------------
# Tempo
# ---------------------------------------------------------------------------
def fmt(t):
    """Formata segundos como 01:25, 1:02:03 ou 01:25.5 (com décimos se houver)."""
    t = round(float(t) * 10) / 10
    inteiro = int(t)
    decimo = round((t - inteiro) * 10)
    h, resto = divmod(inteiro, 3600)
    m, s = divmod(resto, 60)
    base = f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
    return base + (f".{decimo}" if decimo else "")


def ler_tempo(texto):
    """Lê "90", "1:30", "1:02:03" ou "1:30.5" e devolve segundos (float) ou None."""
    texto = texto.strip().replace(",", ".")
    if not texto:
        return None
    try:
        partes = [float(p) for p in texto.split(":")]
    except ValueError:
        return None
    if len(partes) > 3 or any(p < 0 for p in partes):
        return None
    total = 0.0
    for p in partes:
        total = total * 60 + p
    return total


# ---------------------------------------------------------------------------
# Seletor do clip
# ---------------------------------------------------------------------------
class SeletorClip(ctk.CTkFrame):
    def __init__(self, mestre, icone=None):
        super().__init__(mestre, fg_color=CAMPO, corner_radius=10)
        self._icone = icone
        try:
            self._esc = float(self._get_widget_scaling())
        except Exception:
            self._esc = 1.0

        # estado
        self._dur = None                  # duração do vídeo (s); None = nenhum vídeo
        self._ini = self._fim = 0.0
        self._v0 = self._v1 = 0.0         # trecho do vídeo visível na linha do tempo (zoom)
        self._asp = 16 / 9
        self._stream = None
        self._sb_tira = self._sb_grande = None
        self._arrasto = None
        self._tira_base = self._tira_escura = None
        self._tk_refs = {}
        self._tokens = {"ini": 0, "fim": 0}
        self._timers = {"ini": None, "fim": None}
        self._remontar_id = None
        self._janela_previa = None

        # trabalho em segundo plano (as threads nunca mexem na tela: usam esta fila)
        self._fila = queue.Queue()
        self._exec = ThreadPoolExecutor(max_workers=3)
        self._id_sondar = self.after(40, self._sondar)

        self._montar()
        self.resetar()

    # ---------------------------------------------------------- construção
    def _px(self, v):
        return max(1, int(round(v * self._esc)))

    def _montar(self):
        self.grid_columnconfigure(0, weight=1)

        topo = ctk.CTkFrame(self, fg_color="transparent")
        topo.grid(row=0, column=0, sticky="ew", padx=12, pady=(6, 2))
        topo.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(topo, text="✂  Recortar clip", text_color=TEXTO,
                     font=(FONTE, 13, "bold")).grid(row=0, column=0, sticky="w")
        self.label_dica = ctk.CTkLabel(topo, text="", text_color=TEXTO_SEC,
                                       font=(FONTE, 12), anchor="e")
        self.label_dica.grid(row=0, column=1, sticky="e")

        # Linha do tempo (miniaturas + alças + régua)
        self.tela = tk.Canvas(self, height=self._px(ALT_TIRA + ALT_REGUA), bg=CAMPO,
                              highlightthickness=0, bd=0)
        self.tela.grid(row=1, column=0, sticky="ew", padx=12)
        self.tela.bind("<Configure>", lambda e: self._agendar_remontar())
        self.tela.bind("<ButtonPress-1>", self._ao_apertar)
        self.tela.bind("<B1-Motion>", self._ao_arrastar)
        self.tela.bind("<ButtonRelease-1>", self._ao_soltar)
        self.tela.bind("<Motion>", self._ao_passar)

        # Linha de baixo: [quadro início][campos][centro][campos][quadro fim]
        baixo = ctk.CTkFrame(self, fg_color="transparent")
        baixo.grid(row=2, column=0, sticky="ew", padx=12, pady=(6, 8))
        baixo.grid_columnconfigure(2, weight=1)

        self.caixa = {}
        self.entrada = {}
        self.botoes_tempo = []
        self.caixa["ini"] = self._criar_caixa(baixo)
        self.caixa["ini"].grid(row=0, column=0, sticky="w")
        self._criar_coluna_tempo(baixo, "ini", "Início").grid(row=0, column=1, padx=(8, 4), sticky="n")

        centro = ctk.CTkFrame(baixo, fg_color="transparent")
        centro.grid(row=0, column=2, sticky="nsew", padx=4)
        centro.grid_columnconfigure(0, weight=1)
        self.label_duracao = ctk.CTkLabel(centro, text="--", text_color=TEXTO,
                                          font=(FONTE, 17, "bold"))
        self.label_duracao.grid(row=0, column=0, pady=(0, 0))
        self.botao_previa = ctk.CTkButton(
            centro, text="▶  Ver prévia", height=28, corner_radius=8, width=130,
            fg_color=VERMELHO, hover_color=VERMELHO_HOVER, font=(FONTE, 13, "bold"),
            command=self._abrir_previa)
        self.botao_previa.grid(row=1, column=0, pady=(6, 4))
        self.botao_zoom = ctk.CTkButton(
            centro, text="🔍  Ampliar trecho", height=24, corner_radius=8, width=130,
            fg_color=BOTAO_CINZA, hover_color=BOTAO_CINZA_HOVER, font=(FONTE, 12),
            command=self._alternar_zoom)
        self.botao_zoom.grid(row=2, column=0)

        self._criar_coluna_tempo(baixo, "fim", "Fim").grid(row=0, column=3, padx=(4, 8), sticky="n")
        self.caixa["fim"] = self._criar_caixa(baixo)
        self.caixa["fim"].grid(row=0, column=4, sticky="e")

    def _criar_caixa(self, mestre):
        return tk.Canvas(mestre, width=self._px(156), height=self._px(ALT_CAIXA), bg="#101010",
                         highlightthickness=1, highlightbackground=BOTAO_CINZA, bd=0)

    def _criar_coluna_tempo(self, mestre, lado, titulo):
        coluna = ctk.CTkFrame(mestre, fg_color="transparent")
        ctk.CTkLabel(coluna, text=titulo, text_color=TEXTO_SEC, height=16,
                     font=(FONTE, 12)).pack(anchor="w", pady=(0, 1))
        entrada = ctk.CTkEntry(coluna, width=84, height=28, corner_radius=8, justify="center",
                               fg_color=CARTAO, border_width=0, text_color=TEXTO, font=(FONTE, 14, "bold"))
        entrada.pack()
        entrada.bind("<Return>", lambda e, l=lado: self._ao_editar_tempo(l))
        entrada.bind("<FocusOut>", lambda e, l=lado: self._ao_editar_tempo(l))
        self.entrada[lado] = entrada
        linha = ctk.CTkFrame(coluna, fg_color="transparent")
        linha.pack(pady=(3, 0))
        for texto, delta in (("−1s", -1.0), ("+1s", 1.0)):
            b = ctk.CTkButton(linha, text=texto, width=40, height=24, corner_radius=7,
                              fg_color=BOTAO_CINZA, hover_color=BOTAO_CINZA_HOVER,
                              font=(FONTE, 12), command=lambda l=lado, d=delta: self._ajustar(l, d))
            b.pack(side="left", padx=1)
            self.botoes_tempo.append(b)
        return coluna

    # ----------------------------------------------- fila e tarefas em 2º plano
    def _sondar(self):
        try:
            while True:
                self._fila.get_nowait()()
        except queue.Empty:
            pass
        self._id_sondar = self.after(40, self._sondar)

    def destroy(self):
        try:
            self.after_cancel(self._id_sondar)
        except Exception:
            pass
        self._exec.shutdown(wait=False, cancel_futures=True)
        if self._janela_previa is not None:
            try:
                self._janela_previa.destroy()
            except Exception:
                pass
        super().destroy()

    # --------------------------------------------------------- estados gerais
    def _escrever(self, entrada, texto, habilitada):
        entrada.configure(state="normal")
        entrada.delete(0, "end")
        entrada.insert(0, texto)
        entrada.configure(state="normal" if habilitada else "disabled")

    def resetar(self, dica="Cole um link para escolher o trecho do clip."):
        """Nenhum vídeo carregado: desativa tudo."""
        self._dur = None
        self._ini = self._fim = 0.0
        self._stream = self._sb_tira = self._sb_grande = None
        self._arrasto = None
        self._tira_base = self._tira_escura = None
        self._tokens["ini"] += 1
        self._tokens["fim"] += 1
        self.label_dica.configure(text=dica)
        self.label_duracao.configure(text="Clip de --")
        for lado in ("ini", "fim"):
            self._escrever(self.entrada[lado], "--:--", False)
        for b in self.botoes_tempo + [self.botao_previa, self.botao_zoom]:
            b.configure(state="disabled")
        self.botao_zoom.configure(text="🔍  Ampliar trecho")
        self._remontar()
        for lado in ("ini", "fim"):
            self._limpar_caixa(lado)

    def configurar(self, info):
        """Ativa o recorte para o vídeo descrito em `info`. Retorna False se não der."""
        dur = float(info.get("duracao") or 0)
        if dur < 2:
            self.resetar("Não dá para recortar: o vídeo não tem duração conhecida.")
            return False
        previa = info.get("previa") or {}
        self._stream = previa.get("stream")
        niveis = list(previa.get("storyboards") or [])
        self._sb_tira = self._sb_grande = None
        if niveis:
            maior = niveis[-1]
            proporcao = maior["w"] / maior["h"]
            niveis = [n for n in niveis if abs(n["w"] / n["h"] - proporcao) < 0.15]
            grande = Storyboard_(niveis[-1])
            tira = next((n for n in niveis if n["h"] >= ALT_TIRA), niveis[-1])
            self._sb_grande = grande
            self._sb_tira = grande if tira is niveis[-1] else Storyboard_(tira)
            self._sb_tira.precarregar(lambda: self._fila.put(self._agendar_remontar))
        if self._stream:
            self._asp = self._stream["largura"] / self._stream["altura"]
        elif self._sb_grande:
            self._asp = self._sb_grande.proporcao
        else:
            self._asp = 16 / 9
        largura = max(48, min(156, round(ALT_CAIXA * self._asp)))
        for lado in ("ini", "fim"):
            self.caixa[lado].configure(width=self._px(largura), height=self._px(ALT_CAIXA))

        self._dur = dur
        self._v0, self._v1 = 0.0, dur
        self._ini, self._fim = 0.0, round(min(30.0, dur), 1)
        for b in self.botoes_tempo + [self.botao_zoom]:
            b.configure(state="normal")
        self.botao_previa.configure(state="normal" if self._stream else "disabled")
        self.botao_zoom.configure(text="🔍  Ampliar trecho")
        self.label_dica.configure(text="Arraste as alças vermelhas • arraste o meio para mover o clip")
        self._atualizar(("ini", "fim"))
        self._agendar_remontar()
        return True

    def trecho(self):
        """(início, fim) escolhidos, em segundos, ou None se não há vídeo carregado."""
        return (self._ini, self._fim) if self._dur else None

    # ------------------------------------------------------ tempo <-> posição
    def _largura(self):
        return max(self.tela.winfo_width(), 10)

    def _altura_tira(self):
        return self._px(ALT_TIRA)

    def _t_para_x(self, t):
        return (t - self._v0) / max(self._v1 - self._v0, 0.001) * self._largura()

    def _x_para_t(self, x):
        t = self._v0 + x / self._largura() * (self._v1 - self._v0)
        return max(0.0, min(round(t * 10) / 10, self._dur))

    # --------------------------------------------------- definir o trecho
    def _definir(self, ini=None, fim=None, lado="ambos"):
        """Aplica um novo trecho, sempre válido (0 <= início < fim <= duração)."""
        ini = self._ini if ini is None else ini
        fim = self._fim if fim is None else fim
        dur = self._dur
        ini = max(0.0, min(ini, dur - MIN_CLIP))
        fim = max(MIN_CLIP, min(fim, dur))
        if lado == "ini":
            ini = min(ini, fim - MIN_CLIP)
        elif lado == "fim":
            fim = max(fim, ini + MIN_CLIP)
        ini, fim = round(ini, 1), round(fim, 1)
        mudou = tuple(l for l, novo, velho in (("ini", ini, self._ini), ("fim", fim, self._fim))
                      if novo != velho)
        self._ini, self._fim = ini, fim
        if mudou:
            self._atualizar(mudou)

    def _ajustar(self, lado, delta):
        if not self._dur:
            return
        if lado == "ini":
            self._definir(ini=self._ini + delta, lado="ini")
        else:
            self._definir(fim=self._fim + delta, lado="fim")

    def _ao_editar_tempo(self, lado):
        if not self._dur:
            return
        entrada = self.entrada[lado]
        valor = ler_tempo(entrada.get())
        atual = self._ini if lado == "ini" else self._fim
        if valor is None:
            valor = atual
        if lado == "ini":
            self._definir(ini=valor, lado="ini")
        else:
            self._definir(fim=valor, lado="fim")
        self._escrever(entrada, fmt(self._ini if lado == "ini" else self._fim), True)

    def _atualizar(self, lados):
        """Atualiza campos, duração, linha do tempo e quadros de prévia."""
        for lado, valor in (("ini", self._ini), ("fim", self._fim)):
            try:
                digitando = self.focus_get() is self.entrada[lado]._entry
            except Exception:
                digitando = False
            if not digitando:
                self._escrever(self.entrada[lado], fmt(valor), True)
        self.label_duracao.configure(text=f"Clip de {fmt(self._fim - self._ini)}")
        self._desenhar()
        for lado in lados:
            self._pedir_quadro(lado)

    # ------------------------------------------------------------- zoom
    def _alternar_zoom(self):
        if not self._dur:
            return
        if (self._v0, self._v1) == (0.0, self._dur):
            margem = max(self._fim - self._ini, 10.0)
            self._v0 = max(0.0, self._ini - margem)
            self._v1 = min(self._dur, self._fim + margem)
            self.botao_zoom.configure(text="↔  Ver tudo")
        else:
            self._v0, self._v1 = 0.0, self._dur
            self.botao_zoom.configure(text="🔍  Ampliar trecho")
        self._remontar()

    # --------------------------------------------------- linha do tempo (desenho)
    def _agendar_remontar(self):
        if self._remontar_id:
            self.after_cancel(self._remontar_id)
        self._remontar_id = self.after(90, self._remontar)

    def _remontar(self):
        self._remontar_id = None
        self._montar_tira()
        self._desenhar()

    def _montar_tira(self):
        """Compõe a faixa de miniaturas (clara e escura) para o trecho visível."""
        self._tira_base = self._tira_escura = None
        if not self._dur:
            return
        largura, altura = self._largura(), self._altura_tira()
        if largura < 40:
            return
        n = max(1, round(largura / (altura * 0.8)))
        base = Image.new("RGB", (largura, altura), "#2B2B2B")
        for i in range(n):
            x0, x1 = round(i * largura / n), round((i + 1) * largura / n)
            t = self._v0 + (i + 0.5) / n * (self._v1 - self._v0)
            quadro = self._sb_tira.quadro(t, baixar=False) if self._sb_tira else None
            if quadro is not None and x1 > x0:
                base.paste(ImageOps.fit(quadro, (x1 - x0, altura), Image.BILINEAR), (x0, 0))
        self._tira_base = base
        self._tira_escura = ImageEnhance.Brightness(base).enhance(0.30)

    def _desenhar(self):
        c = self.tela
        c.delete("all")
        largura, altura = self._largura(), self._altura_tira()
        if not self._dur or self._tira_base is None:
            texto = self.label_dica.cget("text") if not self._dur else "Carregando miniaturas..."
            c.create_rectangle(0, 0, largura, altura, fill="#1E1E1E", outline="")
            c.create_text(largura / 2, altura / 2, text=texto, fill=TEXTO_APAGADO, font=(FONTE, 11))
            return

        self._tk_refs["escura"] = ImageTk.PhotoImage(self._tira_escura)
        c.create_image(0, 0, image=self._tk_refs["escura"], anchor="nw")

        x1 = max(0, min(largura, round(self._t_para_x(self._ini))))
        x2 = max(0, min(largura, round(self._t_para_x(self._fim))))
        borda = self._px(3)
        if x2 > x1:
            self._tk_refs["clara"] = ImageTk.PhotoImage(self._tira_base.crop((x1, 0, x2, altura)))
            c.create_image(x1, 0, image=self._tk_refs["clara"], anchor="nw")
            c.create_rectangle(x1, 0, x2, borda, fill=VERMELHO, outline="")
            c.create_rectangle(x1, altura - borda, x2, altura, fill=VERMELHO, outline="")
            if x2 - x1 > self._px(120):          # duração escrita no meio da seleção
                meio = (x1 + x2) / 2
                texto = fmt(self._fim - self._ini)
                c.create_text(meio + 1, altura / 2 + 1, text=texto, fill="#000000", font=(FONTE, 12, "bold"))
                c.create_text(meio, altura / 2, text=texto, fill="#FFFFFF", font=(FONTE, 12, "bold"))
        alca = self._px(LARG_ALCA)
        for lado, x in (("ini", x1), ("fim", x2)):
            visivel = self._v0 - 0.01 <= (self._ini if lado == "ini" else self._fim) <= self._v1 + 0.01
            if not visivel:
                continue
            esq = x if lado == "ini" else x - alca
            esq = max(0, min(largura - alca, esq))
            c.create_rectangle(esq, 0, esq + alca, altura, fill=VERMELHO, outline="")
            for dx in (alca * 0.35, alca * 0.65):
                c.create_line(esq + dx, altura * 0.3, esq + dx, altura * 0.7, fill="#FFFFFF", width=1)
        self._desenhar_regua(largura, altura)

    def _desenhar_regua(self, largura, altura):
        c = self.tela
        span = max(self._v1 - self._v0, 0.001)
        por_seg = largura / span
        passo = next((p for p in (1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200)
                      if p * por_seg >= self._px(78)), 7200)
        t = (int(self._v0 // passo)) * passo
        while t <= self._v1 + 0.001:
            if t >= self._v0 - 0.001:
                x = self._t_para_x(t)
                c.create_line(x, altura, x, altura + self._px(4), fill=TEXTO_APAGADO)
                ancora = "nw" if x < self._px(18) else ("ne" if x > largura - self._px(18) else "n")
                c.create_text(x + (1 if ancora == "nw" else 0), altura + self._px(4), text=fmt(t),
                              fill=TEXTO_APAGADO, font=(FONTE, 8), anchor=ancora)
            t += passo

    # ----------------------------------------------------------- mouse
    def _alvo(self, x):
        """Onde o mouse está: "ini" (alça), "fim" (alça), "meio" (seleção) ou "fora"."""
        x1, x2 = self._t_para_x(self._ini), self._t_para_x(self._fim)
        tol = self._px(LARG_ALCA) + self._px(4)
        d1, d2 = abs(x - x1), abs(x - x2)
        if d1 <= tol and d1 <= d2:
            return "ini"
        if d2 <= tol:
            return "fim"
        if x1 < x < x2:
            return "meio"
        return "fora"

    def _ao_passar(self, e):
        if not self._dur or self._arrasto:
            return
        self.tela.configure(cursor={"ini": "sb_h_double_arrow", "fim": "sb_h_double_arrow",
                                    "meio": "fleur", "fora": "hand2"}[self._alvo(e.x)])

    def _ao_apertar(self, e):
        if not self._dur:
            return
        alvo = self._alvo(e.x)
        if alvo == "fora":                       # clique fora: leva a alça mais próxima até lá
            alvo = "ini" if e.x < self._t_para_x(self._ini) else "fim"
        deslocamento = (self._x_para_t(e.x) - self._ini) if alvo == "meio" else 0.0
        self._arrasto = (alvo, deslocamento)
        self._ao_arrastar(e)

    def _ao_arrastar(self, e):
        if not self._dur or not self._arrasto:
            return
        modo, deslocamento = self._arrasto
        t = self._x_para_t(max(0, min(e.x, self._largura())))
        if modo == "ini":
            self._definir(ini=t, lado="ini")
        elif modo == "fim":
            self._definir(fim=t, lado="fim")
        else:
            tamanho = self._fim - self._ini
            novo = max(0.0, min(t - deslocamento, self._dur - tamanho))
            self._definir(ini=novo, fim=novo + tamanho, lado="ambos")

    def _ao_soltar(self, e):
        self._arrasto = None

    # --------------------------------------------------- quadros de prévia
    def _limpar_caixa(self, lado):
        c = self.caixa[lado]
        c.delete("all")
        c.create_text(c.winfo_reqwidth() / 2, c.winfo_reqheight() / 2,
                      text="sem prévia", fill=TEXTO_APAGADO, font=(FONTE, 10))

    def _pedir_quadro(self, lado):
        """Mostra já o quadro das miniaturas e, logo depois, o quadro exato."""
        if not self._dur:
            return
        t = self._ini if lado == "ini" else self._fim
        self._tokens[lado] += 1
        token = self._tokens[lado]
        if self._sb_grande is not None:
            rapido = self._sb_grande.quadro(t, baixar=False)
            if rapido is not None:
                self._mostrar_quadro(lado, rapido, t, token)
            else:
                self._exec.submit(self._tarefa_rapida, lado, token, t)
        if self._stream:
            if self._timers[lado]:
                self.after_cancel(self._timers[lado])
            self._timers[lado] = self.after(
                380, lambda: self._exec.submit(self._tarefa_exata, lado, token, t))

    def _tarefa_rapida(self, lado, token, t):
        if token != self._tokens[lado]:
            return
        imagem = self._sb_grande.quadro(t, baixar=True)
        if imagem is not None:
            self._fila.put(lambda: self._mostrar_quadro(lado, imagem, t, token))

    def _tarefa_exata(self, lado, token, t):
        if token != self._tokens[lado] or not self._stream:
            return
        altura = self.caixa[lado].winfo_reqheight() * 2
        imagem = previas.quadro_exato(self._stream["video"], t, altura)
        if imagem is not None and token == self._tokens[lado]:
            self._fila.put(lambda: self._mostrar_quadro(lado, imagem, t, token))

    def _mostrar_quadro(self, lado, imagem, t, token):
        if token != self._tokens[lado] or not self._dur:
            return
        c = self.caixa[lado]
        w, h = c.winfo_reqwidth(), c.winfo_reqheight()
        self._tk_refs[lado] = ImageTk.PhotoImage(imagem.resize((w, h), Image.LANCZOS))
        c.delete("all")
        c.create_image(0, 0, image=self._tk_refs[lado], anchor="nw")
        texto = fmt(t)
        larg_texto = self._px(7) * len(texto) + self._px(10)
        c.create_rectangle(4, h - self._px(20), 4 + larg_texto, h - 4, fill="#101010", outline="")
        c.create_text(4 + larg_texto / 2, h - self._px(12), text=texto, fill="#FFFFFF", font=(FONTE, 9, "bold"))

    # ------------------------------------------------------------ prévia
    def _abrir_previa(self):
        if not self._dur or not self._stream:
            return
        if self._janela_previa is not None:
            try:
                self._janela_previa.destroy()
            except Exception:
                pass
        self._janela_previa = JanelaPrevia(self.winfo_toplevel(), self._stream,
                                           self._ini, self._fim, self._icone)


def Storyboard_(nivel):
    return previas.Storyboard(nivel)


# ---------------------------------------------------------------------------
# Janela que toca a prévia do clip
# ---------------------------------------------------------------------------
class JanelaPrevia(ctk.CTkToplevel):
    def __init__(self, mestre, stream, ini, fim, icone=None):
        super().__init__(mestre)
        self.title(f"Prévia do clip  •  {fmt(ini)} → {fmt(fim)}")
        self.configure(fg_color="#0F0F0F")
        self.resizable(False, False)
        self.transient(mestre)
        self._stream, self._ini, self._fim = stream, ini, fim
        self._rep = None
        self._ultimo = -1
        self._tkimg = None
        self._id = None

        try:
            esc = float(self._get_window_scaling())
        except Exception:
            esc = 1.0
        asp = stream["largura"] / stream["altura"]
        if asp >= 1:
            self._larg_v = 560
            self._alt_v = round(self._larg_v / asp)
        else:
            self._alt_v = 340
            self._larg_v = round(self._alt_v * asp)
        total_w = max(self._larg_v + 32, 440)
        self.geometry(f"{int((total_w) * esc)}x{int((self._alt_v + 118) * esc)}")

        self.tela = tk.Label(self, bg="black", bd=0, width=self._larg_v, height=self._alt_v)
        self.tela.configure(width=self._larg_v, height=self._alt_v)
        quadro_preto = ImageTk.PhotoImage(Image.new("RGB", (self._larg_v, self._alt_v), "black"))
        self._tkimg = quadro_preto
        self.tela.configure(image=quadro_preto)
        self.tela.pack(pady=(14, 8))
        self.tela.bind("<Button-1>", lambda e: self._rever())
        self.aviso = tk.Label(self.tela, text="Carregando prévia...", bg="black", fg=TEXTO_SEC,
                              font=(FONTE, 12))
        self.aviso.place(relx=0.5, rely=0.5, anchor="center")

        barra = ctk.CTkFrame(self, fg_color="transparent")
        barra.pack(fill="x", padx=16)
        barra.grid_columnconfigure(0, weight=1)
        self.barra = ctk.CTkProgressBar(barra, height=8, corner_radius=4, progress_color=VERMELHO,
                                        fg_color=CAMPO)
        self.barra.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        self.barra.set(0)
        self.label_tempo = ctk.CTkLabel(barra, text="00:00 / 00:00", text_color=TEXTO_SEC,
                                        font=(FONTE, 12))
        self.label_tempo.grid(row=0, column=1)

        botoes = ctk.CTkFrame(self, fg_color="transparent")
        botoes.pack(pady=(10, 4))
        self.botao_rever = ctk.CTkButton(botoes, text="↻  Rever", width=110, height=34, corner_radius=9,
                                         fg_color=BOTAO_CINZA, hover_color=BOTAO_CINZA_HOVER,
                                         font=(FONTE, 13), command=self._rever)
        self.botao_rever.pack(side="left", padx=5)
        ctk.CTkButton(botoes, text="Fechar", width=100, height=34, corner_radius=9,
                      fg_color=BOTAO_CINZA, hover_color=BOTAO_CINZA_HOVER, font=(FONTE, 13),
                      command=self.destroy).pack(side="left", padx=5)
        nota = ""
        if fim - ini > previas.LIMITE_PREVIA_SEG:
            nota = "A prévia mostra só os primeiros 5 minutos do clip."
        ctk.CTkLabel(self, text=nota, text_color=AMARELO, font=(FONTE, 11)).pack()

        if icone:
            self.after(250, lambda: self._aplicar_icone(icone))
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self._rever()

    def _aplicar_icone(self, icone):
        try:
            self.iconbitmap(icone)
        except Exception:
            pass

    def _rever(self):
        """(Re)começa a tocar o clip do início."""
        if self._rep is not None:
            self._rep.parar()
        self._rep = previas.Reprodutor(self._stream["video"], self._stream["audio"], self._ini,
                                       self._fim, self._larg_v, self._alt_v)
        self._ultimo = -1
        self.barra.set(0)
        self.botao_rever.configure(fg_color=BOTAO_CINZA, hover_color=BOTAO_CINZA_HOVER)
        self.aviso.configure(text="Carregando prévia...", fg=TEXTO_SEC)
        self.aviso.place(relx=0.5, rely=0.5, anchor="center")
        self._rep.iniciar()
        if self._id is None:
            self._id = self.after(30, self._atualizar)

    def _atualizar(self):
        r = self._rep
        if r is not None:
            if r.quadro_atual is not None and r.indice != self._ultimo:
                self._ultimo = r.indice
                imagem = Image.frombytes("RGB", (self._larg_v, self._alt_v), r.quadro_atual)
                self._tkimg = ImageTk.PhotoImage(imagem)
                self.tela.configure(image=self._tkimg)
                self.aviso.place_forget()
            if r.duracao:
                self.barra.set(max(0.0, min(r.tempo_atual / r.duracao, 1.0)))
            self.label_tempo.configure(text=f"{fmt(r.tempo_atual)} / {fmt(r.duracao)}")
            if r.estado == "erro":
                self.aviso.configure(text="Não consegui carregar a prévia.\nO link do vídeo pode ter "
                                          "expirado: cole o link de novo.", fg=ERRO)
                self.aviso.place(relx=0.5, rely=0.5, anchor="center")
            elif r.estado == "fim":
                self.botao_rever.configure(fg_color=VERMELHO, hover_color=VERMELHO_HOVER)
        self._id = self.after(30, self._atualizar)

    def destroy(self):
        if self._id is not None:
            try:
                self.after_cancel(self._id)
            except Exception:
                pass
            self._id = None
        if self._rep is not None:
            self._rep.parar()
        super().destroy()
