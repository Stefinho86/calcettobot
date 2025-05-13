import os
import psycopg2
from datetime import datetime
from collections import Counter, defaultdict
from telegram import (
    Update,
    InputFile,
    ReplyKeyboardMarkup,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ConversationHandler,
    ContextTypes
)
from reportlab.lib.pagesizes import letter, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.lib import colors

SQUADRE, DATA, RISULTATO, GOL, ASSIST = range(5)
MODIFICA_PARTITA_SELEZIONE, MODIFICA_CAMPO, MODIFICA_VALORE = range(5,8)
ELIMINA_PARTITA_SELEZIONE = 8
AGGIUNGI_GIOCATORE = 9

DATABASE_URL = os.environ.get("DATABASE_URL")

def get_conn():
    return psycopg2.connect(DATABASE_URL)

def lista_giocatori(chat_id):
    with get_conn() as conn:
        with conn.cursor() as c:
            c.execute('SELECT nome FROM giocatori WHERE chat_id = %s ORDER BY nome', (chat_id,))
            nomi = [row[0] for row in c.fetchall()]
    return nomi

def aggiungi_giocatori_db(nomi, chat_id):
    with get_conn() as conn:
        with conn.cursor() as c:
            for nome in nomi:
                c.execute(
                    'INSERT INTO giocatori (nome, chat_id) VALUES (%s, %s) ON CONFLICT (nome, chat_id) DO NOTHING',
                    (nome, chat_id)
                )

def salva_partita(data, chat_id):
    with get_conn() as conn:
        with conn.cursor() as c:
            c.execute('INSERT INTO partite (data, squadra_a, squadra_b, risultato, chat_id) VALUES (%s, %s, %s, %s, %s) RETURNING id',
                      (data['data'], ','.join(data['squadra_a']), ','.join(data['squadra_b']), data['risultato'], chat_id))
            partita_id = c.fetchone()[0]
            gol = parse_stats(data['gol'])
            assist = parse_stats(data['assist'])
            gol_a, gol_b = map(int, data['risultato'].split('-'))
            for nome in data['squadra_a']:
                c.execute('SELECT id FROM giocatori WHERE nome=%s AND chat_id=%s', (nome, chat_id))
                giocatore_id = c.fetchone()[0]
                c.execute('INSERT INTO prestazioni (partita_id, giocatore_id, squadra, gol, assist, vittoria, pareggio, sconfitta, chat_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)',
                          (partita_id, giocatore_id, 'A', gol.get(nome,0), assist.get(nome,0), int(gol_a>gol_b), int(gol_a==gol_b), int(gol_a<gol_b), chat_id))
            for nome in data['squadra_b']:
                c.execute('SELECT id FROM giocatori WHERE nome=%s AND chat_id=%s', (nome, chat_id))
                giocatore_id = c.fetchone()[0]
                c.execute('INSERT INTO prestazioni (partita_id, giocatore_id, squadra, gol, assist, vittoria, pareggio, sconfitta, chat_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)',
                          (partita_id, giocatore_id, 'B', gol.get(nome,0), assist.get(nome,0), int(gol_b>gol_a), int(gol_a==gol_b), int(gol_b<gol_a), chat_id))

def parse_stats(s):
    d = {}
    for item in s.split(','):
        if ':' in item:
            nome, num = item.split(':')
            d[nome.strip()] = int(num)
    return d

def valida_data(data_str):
    try:
        dt = datetime.strptime(data_str, "%d/%m/%Y")
        return dt.strftime("%d/%m/%Y")
    except Exception:
        return None

def is_annulla(msg):
    return msg and msg.strip().lower() in ('annulla', '/annulla')

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [KeyboardButton("/nuovapartita"), KeyboardButton("/statistiche")],
        [KeyboardButton("/partite"), KeyboardButton("/partita")],
        [KeyboardButton("/giocatori"), KeyboardButton("/aggiungi_giocatore")],
        [KeyboardButton("/modifica_partita"), KeyboardButton("/elimina_partita")]
    ]
    await update.message.reply_text(
        "Menù principale. Scegli un comando:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )

async def annulla(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Operazione annullata. Torni al menù principale.",
        reply_markup=ReplyKeyboardMarkup([
            [KeyboardButton("/nuovapartita"), KeyboardButton("/statistiche")],
            [KeyboardButton("/partite"), KeyboardButton("/partita")],
            [KeyboardButton("/giocatori"), KeyboardButton("/aggiungi_giocatore")],
            [KeyboardButton("/modifica_partita"), KeyboardButton("/elimina_partita")]
        ], resize_keyboard=True)
    )
    return ConversationHandler.END

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await menu(update, context)

async def giocatori(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    nomi = lista_giocatori(chat_id)
    if not nomi:
        await update.message.reply_text("Nessun giocatore registrato. Usa /aggiungi_giocatore per aggiungerli.")
    else:
        await update.message.reply_text("🏃 Elenco giocatori:\n" + "\n".join(sorted(nomi)))

async def aggiungi_giocatore(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Inserisci uno o più nomi di giocatori separati da virgola (es: Rossi, Bianchi, Verdi):",
        reply_markup=ReplyKeyboardMarkup([["/annulla"]], resize_keyboard=True, one_time_keyboard=True)
    )
    return AGGIUNGI_GIOCATORE

async def aggiungi_giocatore_salva(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_annulla(update.message.text):
        return await annulla(update, context)
    chat_id = update.effective_chat.id
    testo = update.message.text
    nomi = [n.strip() for n in testo.split(',') if n.strip()]
    if not nomi:
        await update.message.reply_text("Nessun nome valido inserito. Riprova o /annulla.")
        return AGGIUNGI_GIOCATORE
    aggiungi_giocatori_db(nomi, chat_id)
    await update.message.reply_text("✅ Giocatore/i aggiunto/i: " + ", ".join(nomi))
    await menu(update, context)
    return ConversationHandler.END

async def nuova_partita(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    nomi = lista_giocatori(chat_id)
    if not nomi:
        await update.message.reply_text("⚠️ Nessun giocatore registrato. Usa prima /aggiungi_giocatore.")
        return ConversationHandler.END
    await update.message.reply_text(
        "Inserisci i nomi dei 5 giocatori della Squadra A, separati da virgola (scegli tra questi giocatori registrati):\n\n"
        + ", ".join(nomi),
        reply_markup=ReplyKeyboardMarkup([["/annulla"]], resize_keyboard=True, one_time_keyboard=True)
    )
    context.user_data['step'] = 0
    context.user_data['giocatori_registrati'] = set(nomi)
    return SQUADRE

async def squadre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if is_annulla(update.message.text):
        return await annulla(update, context)
    giocatori_registrati = context.user_data.get('giocatori_registrati', set())
    if context.user_data['step'] == 0:
        squadra_a = [n.strip() for n in update.message.text.split(',')]
        non_registrati = [n for n in squadra_a if n not in giocatori_registrati]
        if len(squadra_a) != 5 or non_registrati:
            await update.message.reply_text(
                f"❌ Errore. La tua Squadra A contiene giocatori non registrati: {', '.join(non_registrati)}\n"
                f"Inserisci esattamente 5 giocatori tra quelli registrati:\n" + ", ".join(sorted(giocatori_registrati))
            )
            return SQUADRE
        context.user_data['squadra_a'] = squadra_a
        await update.message.reply_text("Inserisci i nomi dei 5 giocatori della Squadra B, separati da virgola:")
        context.user_data['step'] = 1
        return SQUADRE
    else:
        squadra_b = [n.strip() for n in update.message.text.split(',')]
        non_registrati = [n for n in squadra_b if n not in giocatori_registrati]
        if len(squadra_b) != 5 or non_registrati:
            await update.message.reply_text(
                f"❌ Errore. La tua Squadra B contiene giocatori non registrati: {', '.join(non_registrati)}\n"
                f"Inserisci esattamente 5 giocatori tra quelli registrati:\n" + ", ".join(sorted(giocatori_registrati))
            )
            return SQUADRE
        if set(context.user_data['squadra_a']) & set(squadra_b):
            await update.message.reply_text("❌ Errore. Un giocatore non può essere in entrambe le squadre!")
            return SQUADRE
        context.user_data['squadra_b'] = squadra_b
        await update.message.reply_text("Inserisci la data della partita (GG/MM/AAAA):")
        return DATA

async def data_partita(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_annulla(update.message.text):
        return await annulla(update, context)
    data_str = update.message.text.strip()
    data_valida = valida_data(data_str)
    if not data_valida:
        await update.message.reply_text("❌ Formato data non valido. Scrivi la data in formato GG/MM/AAAA (es: 04/04/2024):")
        return DATA
    context.user_data['data'] = data_valida
    await update.message.reply_text("Inserisci il risultato della partita (es. 5-4):")
    return RISULTATO

async def risultato(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_annulla(update.message.text):
        return await annulla(update, context)
    context.user_data['risultato'] = update.message.text
    await update.message.reply_text("Inserisci i marcatori (es. Rossi:2, Bianchi:1, Verdi:2):")
    return GOL

async def gol(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_annulla(update.message.text):
        return await annulla(update, context)
    context.user_data['gol'] = update.message.text
    await update.message.reply_text("Inserisci gli assist (es. Neri:1, Rossi:2, Verdi:1):")
    return ASSIST

async def assist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_annulla(update.message.text):
        return await annulla(update, context)
    chat_id = update.effective_chat.id
    context.user_data['assist'] = update.message.text
    squadra = set(context.user_data['squadra_a'] + context.user_data['squadra_b'])
    marcatori = set(parse_stats(context.user_data['gol']).keys())
    assistman = set(parse_stats(context.user_data['assist']).keys())
    non_in_sq_marc = [n for n in marcatori if n not in squadra]
    non_in_sq_assist = [n for n in assistman if n not in squadra]
    if non_in_sq_marc or non_in_sq_assist:
        msg = ""
        if non_in_sq_marc:
            msg += f"❌ I seguenti marcatori non sono nelle formazioni: {', '.join(non_in_sq_marc)}\n"
        if non_in_sq_assist:
            msg += f"❌ I seguenti assistman non sono nelle formazioni: {', '.join(non_in_sq_assist)}\n"
        msg += "Correggi e reinserisci marcatori e assist."
        await update.message.reply_text(msg)
        return ASSIST
    salva_partita(context.user_data, chat_id)
    await update.message.reply_text(
        "✅ Partita salvata!",
        reply_markup=ReplyKeyboardMarkup([["/menu", "/statistiche"]], resize_keyboard=True, one_time_keyboard=True)
    )
    await menu(update, context)
    return ConversationHandler.END

async def statistiche(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    try:
        with get_conn() as conn:
            with conn.cursor() as c:
                c.execute('SELECT id, nome FROM giocatori WHERE chat_id = %s', (chat_id,))
                giocatori = c.fetchall()
                statistiche = []
                compagni_dict = {}
                avversari_dict = {}

                c.execute('SELECT id, data, squadra_a, squadra_b, risultato FROM partite WHERE chat_id = %s ORDER BY data', (chat_id,))
                partite = c.fetchall()
                c.execute('SELECT partita_id, giocatore_id, squadra, gol, assist, vittoria, pareggio, sconfitta FROM prestazioni WHERE chat_id = %s', (chat_id,))
                prestazioni = c.fetchall()

                partite_map = {p[0]: p for p in partite}
                giocatore_nome = {gid: nome for gid, nome in giocatori}
                nome_id = {nome: gid for gid, nome in giocatori}
                giocatore_partite = defaultdict(list)
                for pr in prestazioni:
                    giocatore_partite[pr[1]].append(pr)  # pr[1]=giocatore_id

                # Avanzate
                for gid, nome in giocatori:
                    compagni = Counter()
                    avversari = Counter()
                    partite_giocatore = giocatore_partite[gid]
                    for pr in partite_giocatore:
                        partita_id = pr[0]
                        squadra_gioc = pr[2]
                        prs = [p for p in prestazioni if p[0] == partita_id]
                        for p in prs:
                            if p[1] == gid:
                                continue
                            if p[2] == squadra_gioc:
                                compagni[giocatore_nome[p[1]]] += 1
                            else:
                                avversari[giocatore_nome[p[1]]] += 1
                    compagni_dict[nome] = compagni.most_common(3)
                    avversari_dict[nome] = avversari.most_common(3)

                for gid, nome in giocatori:
                    prs = giocatore_partite[gid]
                    presenze = len(prs)
                    gol_tot = sum(p[3] for p in prs)
                    assist_tot = sum(p[4] for p in prs)
                    vittorie = sum(p[5] for p in prs)
                    pareggi = sum(p[6] for p in prs)
                    sconfitte = sum(p[7] for p in prs)
                    media_gol = round(gol_tot/presenze,2) if presenze else 0
                    media_assist = round(assist_tot/presenze,2) if presenze else 0
                    perc_vittorie = f"{round(100*vittorie/presenze,1)}%" if presenze else "0%"
                    perc_pareggi = f"{round(100*pareggi/presenze,1)}%" if presenze else "0%"
                    perc_sconfitte = f"{round(100*sconfitte/presenze,1)}%" if presenze else "0%"
                    compagni_top = ', '.join([f"{n} ({c})" for n,c in compagni_dict[nome]]) if compagni_dict[nome] else "-"
                    avversari_top = ', '.join([f"{n} ({c})" for n,c in avversari_dict[nome]]) if avversari_dict[nome] else "-"
                    statistiche.append([
                        nome, presenze, gol_tot, media_gol, assist_tot, media_assist,
                        vittorie, perc_vittorie, pareggi, perc_pareggi, sconfitte, perc_sconfitte, compagni_top, avversari_top
                    ])
                header = [
                    "Nome", "Pres.", "Gol", "Media Gol", "Assist", "Media Assist",
                    "Vittorie", "%Vitt", "Pareggi", "%Par", "Sconfitte", "%Sco",
                    "Top Compagni", "Top Avversari"
                ]

                # CLASSIFICA CANNONIERI
                classifica_gol = []
                for gid, nome in giocatori:
                    tot_gol = sum(p[3] for p in giocatore_partite[gid])
                    classifica_gol.append([nome, tot_gol])
                classifica_gol.sort(key=lambda x: (-x[1], x[0]))

                # CLASSIFICA ASSISTMAN
                classifica_assist = []
                for gid, nome in giocatori:
                    tot_assist = sum(p[4] for p in giocatore_partite[gid])
                    classifica_assist.append([nome, tot_assist])
                classifica_assist.sort(key=lambda x: (-x[1], x[0]))

                # CLASSIFICA PRESENZE
                classifica_presenze = []
                for gid, nome in giocatori:
                    presenze = len(giocatore_partite[gid])
                    classifica_presenze.append([nome, presenze])
                classifica_presenze.sort(key=lambda x: (-x[1], x[0]))

                filename = "statistiche_avanzate.pdf"
                genera_pdf_multi(
                    [header]+statistiche,
                    [["Pos", "Giocatore", "Gol"]] + [[i+1, n, g] for i, (n, g) in enumerate(classifica_gol)],
                    [["Pos", "Giocatore", "Assist"]] + [[i+1, n, a] for i, (n, a) in enumerate(classifica_assist)],
                    [["Pos", "Giocatore", "Presenze"]] + [[i+1, n, p] for i, (n, p) in enumerate(classifica_presenze)],
                    filename
                )

                # --- PDF partite con marcatori e assist ---
                c.execute("SELECT id, data, squadra_a, squadra_b, risultato FROM partite WHERE chat_id = %s ORDER BY data", (chat_id,))
                partite_rows = c.fetchall()
                partite_data = []
                styles = getSampleStyleSheet()
                para_style = ParagraphStyle(
                    'MyStyle',
                    fontName='Helvetica',
                    fontSize=8,
                    leading=10,
                    alignment=TA_LEFT
                )
                for row in partite_rows:
                    partita_id, data, squadra_a, squadra_b, risultato = row
                    c.execute("""
                        SELECT giocatori.nome, prestazioni.gol, prestazioni.assist, prestazioni.squadra
                        FROM prestazioni JOIN giocatori ON prestazioni.giocatore_id = giocatori.id
                        WHERE partita_id = %s AND prestazioni.chat_id = %s AND (gol > 0 OR assist > 0)
                        ORDER BY prestazioni.squadra, giocatori.nome
                    """, (partita_id, chat_id))
                    dettaglio = c.fetchall()
                    marcatori = [f"{nome} ({gol})" for nome, gol, assist, sq in dettaglio if gol > 0]
                    assistman = [f"{nome} ({assist})" for nome, gol, assist, sq in dettaglio if assist > 0]

                    partite_data.append([
                        Paragraph(str(data), para_style),
                        Paragraph(squadra_a.replace(",", ", "), para_style),
                        Paragraph(squadra_b.replace(",", ", "), para_style),
                        Paragraph(str(risultato), para_style),
                        Paragraph("<br/>".join(marcatori) if marcatori else "-", para_style),
                        Paragraph("<br/>".join(assistman) if assistman else "-", para_style)
                    ])
                partite_header = [
                    Paragraph("Data", para_style),
                    Paragraph("Squadra A", para_style),
                    Paragraph("Squadra B", para_style),
                    Paragraph("Risultato", para_style),
                    Paragraph("Marcatori", para_style),
                    Paragraph("Assistman", para_style)
                ]
                partite_pdf_filename = "partite.pdf"
                genera_pdf_partite([partite_header]+partite_data, partite_pdf_filename)

        if len(statistiche) == 0:
            await update.message.reply_text("Nessuna statistica disponibile. Inserisci almeno una partita!")
            return
        await update.message.reply_document(
            document=InputFile(open(filename, "rb"), filename=filename),
            caption="📊 Statistiche avanzate, cannonieri, assistman e presenze"
        )
        await update.message.reply_document(
            document=InputFile(open(partite_pdf_filename, "rb"), filename=partite_pdf_filename),
            caption="📅 Lista partite con marcatori e assist"
        )
    except Exception as e:
        print("[ERRORE]", e)
        await update.message.reply_text("Si è verificato un errore nel generare le statistiche: " + str(e))

def genera_pdf_multi(statistiche, cannonieri, assistman, presenze, filename):
    # Calcolo automatico larghezza colonne
    from reportlab.lib.pagesizes import landscape, letter
    PAGE_WIDTH, PAGE_HEIGHT = landscape(letter)
    margin = 20
    usable_width = PAGE_WIDTH - 2 * margin

    def get_colwidths(data):
        n_col = len(data[0])
        return [usable_width / n_col] * n_col

    doc = SimpleDocTemplate(filename, pagesize=landscape(letter), rightMargin=margin, leftMargin=margin)
    elements = []
    styles = getSampleStyleSheet()
    table_style = TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.lightblue),
        ('TEXTCOLOR',(0,0),(-1,0),colors.black),
        ('ALIGN',(0,0),(-1,-1),'CENTER'),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,0), 9),
        ('FONTSIZE', (0,1), (-1,-1), 8),
        ('BOTTOMPADDING', (0,0), (-1,0), 6),
        ('GRID', (0,0), (-1,-1), 0.5, colors.grey)
    ])
    # Statistiche avanzate
    elements.append(Paragraph("Statistiche avanzate calcetto", styles['Title']))
    elements.append(Spacer(1,8))
    table1 = Table(statistiche, repeatRows=1, colWidths=get_colwidths(statistiche))
    table1.setStyle(table_style)
    elements.append(table1)
    elements.append(PageBreak())
    # Cannonieri
    elements.append(Paragraph("Classifica cannonieri", styles['Title']))
    elements.append(Spacer(1,8))
    table2 = Table(cannonieri, repeatRows=1, colWidths=get_colwidths(cannonieri))
    table2.setStyle(table_style)
    elements.append(table2)
    elements.append(PageBreak())
    # Assistman
    elements.append(Paragraph("Classifica assistman", styles['Title']))
    elements.append(Spacer(1,8))
    table3 = Table(assistman, repeatRows=1, colWidths=get_colwidths(assistman))
    table3.setStyle(table_style)
    elements.append(table3)
    elements.append(PageBreak())
    # Presenze
    elements.append(Paragraph("Classifica presenze", styles['Title']))
    elements.append(Spacer(1,8))
    table4 = Table(presenze, repeatRows=1, colWidths=get_colwidths(presenze))
    table4.setStyle(table_style)
    elements.append(table4)
    doc.build(elements)

def genera_pdf_partite(data, filename):
    # Calcolo automatico larghezza colonne
    from reportlab.lib.pagesizes import landscape, letter
    PAGE_WIDTH, PAGE_HEIGHT = landscape(letter)
    margin = 20
    usable_width = PAGE_WIDTH - 2 * margin
    n_col = len(data[0])
    colWidths = [usable_width / n_col] * n_col

    doc = SimpleDocTemplate(filename, pagesize=landscape(letter), rightMargin=margin, leftMargin=margin)
    style = TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.lightblue),
        ('TEXTCOLOR',(0,0),(-1,0),colors.black),
        ('ALIGN',(0,0),(-1,-1),'LEFT'),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,0), 9),
        ('FONTSIZE', (0,1), (-1,-1), 8),
        ('BOTTOMPADDING', (0,0), (-1,0), 6),
        ('GRID', (0,0), (-1,-1), 0.5, colors.grey)
    ])
    table = Table(
        data,
        repeatRows=1,
        colWidths=colWidths,
        splitByRow=1
    )
    table.setStyle(style)
    elements = []
    elements.append(Paragraph("Elenco partite (con marcatori e assist)", getSampleStyleSheet()['Title']))
    elements.append(Spacer(1,8))
    elements.append(table)
    doc.build(elements)

async def tutte_le_partite(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    with get_conn() as conn:
        with conn.cursor() as c:
            c.execute('SELECT data, squadra_a, squadra_b, risultato FROM partite WHERE chat_id = %s ORDER BY data', (chat_id,))
            partite = c.fetchall()
    if not partite:
        await update.message.reply_text("Nessuna partita registrata.")
        return
    lines = []
    for p in partite:
        lines.append(
            f"{p[0]} | Risultato: {p[3]} | Squadra A: {p[1]} | Squadra B: {p[2]}"
        )
    testo = "\n".join(lines)
    if len(testo) > 4000:
        with open("tutte_le_partite.txt", "w", encoding="utf-8") as f:
            f.write(testo)
        await update.message.reply_document(
            document=InputFile(open("tutte_le_partite.txt", "rb"), filename="tutte_le_partite.txt"),
            caption="Elenco completo partite"
        )
    else:
        await update.message.reply_text("Ecco la lista di tutte le partite giocate:\n\n" + testo)

async def partita(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Inserisci la data della partita che vuoi visualizzare (GG/MM/AAAA):")
    return 20

async def mostra_partita(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_annulla(update.message.text):
        return await annulla(update, context)
    chat_id = update.effective_chat.id
    data_richiesta = update.message.text.strip()
    data_valida = valida_data(data_richiesta)
    if not data_valida:
        await update.message.reply_text("❌ Formato data non valido. Scrivi la data in formato GG/MM/AAAA (es: 04/04/2024):")
        return 20
    with get_conn() as conn:
        with conn.cursor() as c:
            c.execute('SELECT id, squadra_a, squadra_b, risultato FROM partite WHERE data = %s AND chat_id = %s', (data_valida, chat_id))
            row = c.fetchone()
            if not row:
                await update.message.reply_text("❌ Nessuna partita trovata per questa data.")
                await menu(update, context)
                return ConversationHandler.END
            partita_id, squadra_a, squadra_b, risultato = row
            c.execute('SELECT giocatori.nome, prestazioni.gol, prestazioni.assist, prestazioni.squadra FROM prestazioni JOIN giocatori ON prestazioni.giocatore_id = giocatori.id WHERE partita_id = %s AND prestazioni.chat_id = %s', (partita_id, chat_id))
            dettagli = c.fetchall()
    tabella = [['Nome', 'Squadra', 'Gol', 'Assist']]
    for nome, gol, assist, squadra in dettagli:
        tabella.append([nome, squadra, str(gol), str(assist)])
    testo = f"📅 Partita del {data_valida}\nRisultato: {risultato}\nSquadra A: {squadra_a}\nSquadra B: {squadra_b}\n"
    testo += "\nMarcatori e assist:\n"
    for r in tabella[1:]:
        testo += f"{r[0]} (Squadra {r[1]}): Gol {r[2]}, Assist {r[3]}\n"
    await update.message.reply_text(testo)
    await menu(update, context)
    return ConversationHandler.END

async def elimina_partita(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Inserisci la data della partita da eliminare (GG/MM/AAAA):")
    return ELIMINA_PARTITA_SELEZIONE

async def elimina_partita_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_annulla(update.message.text):
        return await annulla(update, context)
    chat_id = update.effective_chat.id
    data_richiesta = update.message.text.strip()
    data_valida = valida_data(data_richiesta)
    if not data_valida:
        await update.message.reply_text("❌ Formato data non valido. Scrivi la data in formato GG/MM/AAAA (es: 04/04/2024):")
        return ELIMINA_PARTITA_SELEZIONE
    with get_conn() as conn:
        with conn.cursor() as c:
            c.execute('SELECT id, squadra_a, squadra_b, risultato FROM partite WHERE data = %s AND chat_id = %s', (data_valida, chat_id))
            partite = c.fetchall()
    if not partite:
        await update.message.reply_text("❌ Nessuna partita trovata per questa data.")
        await menu(update, context)
        return ConversationHandler.END
    keyboard = [
        [InlineKeyboardButton(f"{p[1]} vs {p[2]} ({p[3]})", callback_data=f"del_{p[0]}")]
        for p in partite
    ]
    await update.message.reply_text(
        "Seleziona la partita da eliminare:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ConversationHandler.END

async def elimina_partita_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    if query.data.startswith("del_"):
        partita_id = int(query.data.split("_")[1])
        with get_conn() as conn:
            with conn.cursor() as c:
                c.execute('DELETE FROM prestazioni WHERE partita_id = %s AND chat_id = %s', (partita_id, chat_id))
                c.execute('DELETE FROM partite WHERE id = %s AND chat_id = %s', (partita_id, chat_id))
        await query.edit_message_text("✅ Partita eliminata.")
        try:
            await menu(update, context)
        except Exception:
            pass

async def modifica_partita(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Inserisci la data della partita da modificare (GG/MM/AAAA):")
    return MODIFICA_PARTITA_SELEZIONE

async def modifica_partita_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_annulla(update.message.text):
        return await annulla(update, context)
    chat_id = update.effective_chat.id
    data_richiesta = update.message.text.strip()
    data_valida = valida_data(data_richiesta)
    if not data_valida:
        await update.message.reply_text("❌ Formato data non valido. Scrivi la data in formato GG/MM/AAAA (es: 04/04/2024):")
        return MODIFICA_PARTITA_SELEZIONE
    with get_conn() as conn:
        with conn.cursor() as c:
            c.execute('SELECT id, squadra_a, squadra_b, risultato FROM partite WHERE data = %s AND chat_id = %s', (data_valida, chat_id))
            partite = c.fetchall()
    if not partite:
        await update.message.reply_text("❌ Nessuna partita trovata per questa data.")
        await menu(update, context)
        return ConversationHandler.END
    keyboard = [
        [InlineKeyboardButton(f"{p[1]} vs {p[2]} ({p[3]})", callback_data=f"mod_{p[0]}")]
        for p in partite
    ]
    await update.message.reply_text(
        "Seleziona la partita da modificare:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ConversationHandler.END

async def modifica_partita_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data.startswith("mod_"):
        partita_id = int(query.data.split("_")[1])
        context.user_data['modifica_id'] = partita_id
        keyboard = [
            [InlineKeyboardButton("Squadra A", callback_data="campo_squadra_a")],
            [InlineKeyboardButton("Squadra B", callback_data="campo_squadra_b")],
            [InlineKeyboardButton("Risultato", callback_data="campo_risultato")],
            [InlineKeyboardButton("Marcatori", callback_data="campo_gol")],
            [InlineKeyboardButton("Assist", callback_data="campo_assist")]
        ]
        await query.edit_message_text(
            "Quale campo vuoi modificare?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return MODIFICA_CAMPO

async def modifica_campo_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['campo_modifica'] = query.data.replace("campo_", "")
    await query.edit_message_text("Inserisci il nuovo valore:")
    return MODIFICA_VALORE

async def modifica_valore(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_annulla(update.message.text):
        return await annulla(update, context)
    chat_id = update.effective_chat.id
    campo = context.user_data['campo_modifica']
    partita_id = context.user_data['modifica_id']
    nuovo_valore = update.message.text.strip()
    with get_conn() as conn:
        with conn.cursor() as c:
            if campo in ['squadra_a', 'squadra_b', 'risultato']:
                c.execute(f'UPDATE partite SET {campo} = %s WHERE id = %s AND chat_id = %s', (nuovo_valore, partita_id, chat_id))
            elif campo == 'gol' or campo == 'assist':
                c.execute('SELECT squadra_a, squadra_b, risultato FROM partite WHERE id = %s AND chat_id = %s', (partita_id, chat_id))
                row = c.fetchone()
                squadra_a = row[0].split(',')
                squadra_b = row[1].split(',')
                risultato = row[2]
                c.execute('SELECT giocatori.nome, prestazioni.gol, prestazioni.assist, prestazioni.squadra FROM prestazioni JOIN giocatori ON prestazioni.giocatore_id = giocatori.id WHERE partita_id = %s AND prestazioni.chat_id = %s', (partita_id, chat_id))
                prestazioni = c.fetchall()
                if campo == 'gol':
                    nuovo_gol = parse_stats(nuovo_valore)
                    assist_esist = {nome: a for nome, g, a, sq in prestazioni}
                    gol_esist = {nome: g for nome, g, a, sq in prestazioni}
                else:
                    nuovo_assist = parse_stats(nuovo_valore)
                    gol_esist = {nome: g for nome, g, a, sq in prestazioni}
                    assist_esist = {nome: a for nome, g, a, sq in prestazioni}
                c.execute('DELETE FROM prestazioni WHERE partita_id = %s AND chat_id = %s', (partita_id, chat_id))
                gol_a, gol_b = map(int, risultato.split('-'))
                for nome in squadra_a:
                    c.execute('SELECT id FROM giocatori WHERE nome=%s AND chat_id=%s', (nome, chat_id))
                    giocatore_id = c.fetchone()[0]
                    g = nuovo_gol.get(nome, gol_esist.get(nome,0)) if campo == 'gol' else gol_esist.get(nome,0)
                    a = nuovo_assist.get(nome, assist_esist.get(nome,0)) if campo == 'assist' else assist_esist.get(nome,0)
                    c.execute('INSERT INTO prestazioni (partita_id, giocatore_id, squadra, gol, assist, vittoria, pareggio, sconfitta, chat_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)',
                              (partita_id, giocatore_id, 'A', g, a, int(gol_a>gol_b), int(gol_a==gol_b), int(gol_a<gol_b), chat_id))
                for nome in squadra_b:
                    c.execute('SELECT id FROM giocatori WHERE nome=%s AND chat_id=%s', (nome, chat_id))
                    giocatore_id = c.fetchone()[0]
                    g = nuovo_gol.get(nome, gol_esist.get(nome,0)) if campo == 'gol' else gol_esist.get(nome,0)
                    a = nuovo_assist.get(nome, assist_esist.get(nome,0)) if campo == 'assist' else assist_esist.get(nome,0)
                    c.execute('INSERT INTO prestazioni (partita_id, giocatore_id, squadra, gol, assist, vittoria, pareggio, sconfitta, chat_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)',
                              (partita_id, giocatore_id, 'B', g, a, int(gol_b>gol_a), int(gol_a==gol_b), int(gol_b<gol_a), chat_id))
    await update.message.reply_text("✅ Modifica effettuata.")
    await menu(update, context)
    return ConversationHandler.END

def main():
    token = os.environ.get('TOKEN') or "INSERISCI_IL_TUO_TOKEN"
    app = Application.builder().token(token).build()

    conv_nuova = ConversationHandler(
        entry_points=[CommandHandler('nuovapartita', nuova_partita)],
        states={
            SQUADRE: [MessageHandler(filters.TEXT, squadre)],
            DATA: [MessageHandler(filters.TEXT, data_partita)],
            RISULTATO: [MessageHandler(filters.TEXT, risultato)],
            GOL: [MessageHandler(filters.TEXT, gol)],
            ASSIST: [MessageHandler(filters.TEXT, assist)],
        },
        fallbacks=[CommandHandler('annulla', annulla), MessageHandler(filters.TEXT, annulla)],
        allow_reentry=True
    )

    conv_aggiungi = ConversationHandler(
        entry_points=[CommandHandler('aggiungi_giocatore', aggiungi_giocatore)],
        states={
            AGGIUNGI_GIOCATORE: [MessageHandler(filters.TEXT, aggiungi_giocatore_salva)],
        },
        fallbacks=[CommandHandler('annulla', annulla), MessageHandler(filters.TEXT, annulla)],
        allow_reentry=True
    )

    conv_partita = ConversationHandler(
        entry_points=[CommandHandler('partita', partita)],
        states={
            20: [MessageHandler(filters.TEXT, mostra_partita)],
        },
        fallbacks=[CommandHandler('annulla', annulla), MessageHandler(filters.TEXT, annulla)],
        allow_reentry=True
    )

    conv_elimina = ConversationHandler(
        entry_points=[CommandHandler('elimina_partita', elimina_partita)],
        states={
            ELIMINA_PARTITA_SELEZIONE: [MessageHandler(filters.TEXT, elimina_partita_data)],
        },
        fallbacks=[CommandHandler('annulla', annulla), MessageHandler(filters.TEXT, annulla)],
        allow_reentry=True
    )

    conv_modifica = ConversationHandler(
        entry_points=[CommandHandler('modifica_partita', modifica_partita)],
        states={
            MODIFICA_PARTITA_SELEZIONE: [MessageHandler(filters.TEXT, modifica_partita_data)],
            MODIFICA_CAMPO: [CallbackQueryHandler(modifica_campo_callback)],
            MODIFICA_VALORE: [MessageHandler(filters.TEXT, modifica_valore)],
        },
        fallbacks=[CommandHandler('annulla', annulla), MessageHandler(filters.TEXT, annulla)],
        allow_reentry=True
    )

    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('menu', menu))
    app.add_handler(conv_nuova)
    app.add_handler(conv_aggiungi)
    app.add_handler(CommandHandler('giocatori', giocatori))
    app.add_handler(CommandHandler('statistiche', statistiche))
    app.add_handler(conv_partita)
    app.add_handler(CommandHandler('partite', tutte_le_partite))
    app.add_handler(conv_elimina)
    app.add_handler(CallbackQueryHandler(elimina_partita_callback, pattern="^del_"))
    app.add_handler(conv_modifica)
    app.add_handler(CallbackQueryHandler(modifica_partita_callback, pattern="^mod_"))
    app.add_handler(CommandHandler('annulla', annulla))
    app.add_handler(MessageHandler(filters.TEXT, annulla))

    app.run_polling()

if __name__ == '__main__':
    main()