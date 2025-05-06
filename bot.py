import os
import sqlite3
from telegram import (
    Update, 
    InputFile, 
    ReplyKeyboardMarkup, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup
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
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table

SQUADRE, DATA, RISULTATO, GOL, ASSIST = range(5)
MODIFICA_PARTITA_SELEZIONE, MODIFICA_CAMPO, MODIFICA_VALORE = range(5,8)
ELIMINA_PARTITA_SELEZIONE = 8

# ------ DATABASE ------
def init_db():
    conn = sqlite3.connect('calcetto.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS giocatori (id INTEGER PRIMARY KEY, nome TEXT UNIQUE)''')
    c.execute('''CREATE TABLE IF NOT EXISTS partite (id INTEGER PRIMARY KEY, data TEXT, squadra_a TEXT, squadra_b TEXT, risultato TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS prestazioni (id INTEGER PRIMARY KEY, partita_id INTEGER, giocatore_id INTEGER, squadra TEXT, gol INTEGER, assist INTEGER, vittoria INTEGER, pareggio INTEGER, sconfitta INTEGER)''')
    conn.commit()
    conn.close()

def salva_partita(data):
    conn = sqlite3.connect('calcetto.db')
    c = conn.cursor()
    for nome in data['squadra_a'] + data['squadra_b']:
        c.execute('INSERT OR IGNORE INTO giocatori (nome) VALUES (?)', (nome,))
    c.execute('INSERT INTO partite (data, squadra_a, squadra_b, risultato) VALUES (?, ?, ?, ?)',
              (data['data'], ','.join(data['squadra_a']), ','.join(data['squadra_b']), data['risultato']))
    partita_id = c.lastrowid
    gol = parse_stats(data['gol'])
    assist = parse_stats(data['assist'])
    gol_a, gol_b = map(int, data['risultato'].split('-'))
    for nome in data['squadra_a']:
        giocatore_id = c.execute('SELECT id FROM giocatori WHERE nome=?', (nome,)).fetchone()[0]
        c.execute('INSERT INTO prestazioni (partita_id, giocatore_id, squadra, gol, assist, vittoria, pareggio, sconfitta) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                  (partita_id, giocatore_id, 'A', gol.get(nome,0), assist.get(nome,0), int(gol_a>gol_b), int(gol_a==gol_b), int(gol_a<gol_b)))
    for nome in data['squadra_b']:
        giocatore_id = c.execute('SELECT id FROM giocatori WHERE nome=?', (nome,)).fetchone()[0]
        c.execute('INSERT INTO prestazioni (partita_id, giocatore_id, squadra, gol, assist, vittoria, pareggio, sconfitta) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                  (partita_id, giocatore_id, 'B', gol.get(nome,0), assist.get(nome,0), int(gol_b>gol_a), int(gol_a==gol_b), int(gol_b<gol_a)))
    conn.commit()
    conn.close()

def parse_stats(s):
    d = {}
    for item in s.split(','):
        if ':' in item:
            nome, num = item.split(':')
            d[nome.strip()] = int(num)
    return d

# ------ BOT HANDLERS ------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "Benvenuto nel bot delle statistiche di calcetto! ⚽️\n"
        "Comandi disponibili:\n"
        "/nuovapartita - Inserisci una nuova partita\n"
        "/statistiche - Scarica le statistiche complete\n"
        "/partita - Estrai una partita per data\n"
        "/elimina_partita - Elimina una partita\n"
        "/modifica_partita - Modifica una partita\n"
        "Puoi usare questi comandi anche nei gruppi!"
    )
    await update.message.reply_text(text)

# ---- Inserimento nuova partita con tastiera ----
async def nuova_partita(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Inserisci i nomi dei 5 giocatori della Squadra A, separati da virgola:",
        reply_markup=ReplyKeyboardMarkup([["/annulla"]], resize_keyboard=True, one_time_keyboard=True)
    )
    context.user_data['step'] = 0
    return SQUADRE

async def squadre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data['step'] == 0:
        context.user_data['squadra_a'] = [n.strip() for n in update.message.text.split(',')]
        await update.message.reply_text("Inserisci i nomi dei 5 giocatori della Squadra B, separati da virgola:")
        context.user_data['step'] = 1
        return SQUADRE
    else:
        context.user_data['squadra_b'] = [n.strip() for n in update.message.text.split(',')]
        await update.message.reply_text("Inserisci la data della partita (YYYY-MM-DD):")
        return DATA

async def data_partita(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['data'] = update.message.text
    await update.message.reply_text("Inserisci il risultato della partita (es. 5-4):")
    return RISULTATO

async def risultato(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['risultato'] = update.message.text
    await update.message.reply_text("Inserisci i marcatori (es. Rossi:2, Bianchi:1, Verdi:2):")
    return GOL

async def gol(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['gol'] = update.message.text
    await update.message.reply_text("Inserisci gli assist (es. Neri:1, Rossi:2, Verdi:1):")
    return ASSIST

async def assist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['assist'] = update.message.text
    salva_partita(context.user_data)
    await update.message.reply_text(
        "✅ Partita salvata!\nScrivi /statistiche per ricevere il PDF delle statistiche o /start per tornare al menù.",
        reply_markup=ReplyKeyboardMarkup([["/statistiche", "/start"]], resize_keyboard=True, one_time_keyboard=True)
    )
    return ConversationHandler.END

async def annulla(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Operazione annullata.", reply_markup=None)
    return ConversationHandler.END

# ---- Statistiche (PDF) ----
async def statistiche(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect('calcetto.db')
    c = conn.cursor()
    c.execute('SELECT nome, COUNT(prestazioni.id), SUM(gol), SUM(assist), SUM(vittoria), SUM(pareggio), SUM(sconfitta) FROM giocatori LEFT JOIN prestazioni ON giocatori.id = prestazioni.giocatore_id GROUP BY nome')
    rows = c.fetchall()
    data = [['Nome', 'Presenze', 'Gol', 'Assist', 'Vittorie', 'Pareggi', 'Sconfitte']]
    for row in rows:
        data.append([str(x) if x is not None else '0' for x in row])
    conn.close()
    filename = "statistiche.pdf"
    genera_pdf(data, filename)
    with open(filename, "rb") as f:
        await update.message.reply_document(
            document=InputFile(f, filename=filename, mimetype="application/pdf"),
            caption="📊 Statistiche calcetto"
        )

def genera_pdf(data, filename):
    doc = SimpleDocTemplate(filename, pagesize=letter)
    table = Table(data)
    doc.build([table])

# ---- Estrai singola partita ----
async def partita(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Inserisci la data della partita che vuoi visualizzare (YYYY-MM-DD):")
    return 20

async def mostra_partita(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data_richiesta = update.message.text.strip()
    conn = sqlite3.connect('calcetto.db')
    c = conn.cursor()
    c.execute('SELECT id, squadra_a, squadra_b, risultato FROM partite WHERE data = ?', (data_richiesta,))
    row = c.fetchone()
    if not row:
        await update.message.reply_text("❌ Nessuna partita trovata per questa data.")
        conn.close()
        return ConversationHandler.END
    partita_id, squadra_a, squadra_b, risultato = row
    # Statistiche marcatori e assist
    c.execute('SELECT giocatori.nome, prestazioni.gol, prestazioni.assist, prestazioni.squadra FROM prestazioni JOIN giocatori ON prestazioni.giocatore_id = giocatori.id WHERE partita_id = ?', (partita_id,))
    dettagli = c.fetchall()
    tabella = [['Nome', 'Squadra', 'Gol', 'Assist']]
    for nome, gol, assist, squadra in dettagli:
        tabella.append([nome, squadra, str(gol), str(assist)])
    conn.close()
    # Costruisci testo riassuntivo
    testo = f"📅 Partita del {data_richiesta}\nRisultato: {risultato}\nSquadra A: {squadra_a}\nSquadra B: {squadra_b}\n"
    testo += "\nMarcatori e assist:\n"
    for r in tabella[1:]:
        testo += f"{r[0]} (Squadra {r[1]}): Gol {r[2]}, Assist {r[3]}\n"
    await update.message.reply_text(testo)
    return ConversationHandler.END

# ---- Elimina partita ----
async def elimina_partita(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Chiede la data e mostra le partite di quella data (potrebbero essercene più di una)
    await update.message.reply_text("Inserisci la data della partita da eliminare (YYYY-MM-DD):")
    return ELIMINA_PARTITA_SELEZIONE

async def elimina_partita_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data_richiesta = update.message.text.strip()
    conn = sqlite3.connect('calcetto.db')
    c = conn.cursor()
    c.execute('SELECT id, squadra_a, squadra_b, risultato FROM partite WHERE data = ?', (data_richiesta,))
    partite = c.fetchall()
    if not partite:
        await update.message.reply_text("❌ Nessuna partita trovata per questa data.")
        conn.close()
        return ConversationHandler.END
    # Se più partite, mostra pulsanti
    keyboard = [
        [InlineKeyboardButton(f"{p[1]} vs {p[2]} ({p[3]})", callback_data=f"del_{p[0]}")]
        for p in partite
    ]
    await update.message.reply_text(
        "Seleziona la partita da eliminare:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    conn.close()
    return ConversationHandler.END

async def elimina_partita_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data.startswith("del_"):
        partita_id = int(query.data.split("_")[1])
        conn = sqlite3.connect('calcetto.db')
        c = conn.cursor()
        c.execute('DELETE FROM prestazioni WHERE partita_id = ?', (partita_id,))
        c.execute('DELETE FROM partite WHERE id = ?', (partita_id,))
        conn.commit()
        conn.close()
        await query.edit_message_text("✅ Partita eliminata.")

# ---- Modifica partita ----
async def modifica_partita(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Inserisci la data della partita da modificare (YYYY-MM-DD):")
    return MODIFICA_PARTITA_SELEZIONE

async def modifica_partita_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data_richiesta = update.message.text.strip()
    conn = sqlite3.connect('calcetto.db')
    c = conn.cursor()
    c.execute('SELECT id, squadra_a, squadra_b, risultato FROM partite WHERE data = ?', (data_richiesta,))
    partite = c.fetchall()
    if not partite:
        await update.message.reply_text("❌ Nessuna partita trovata per questa data.")
        conn.close()
        return ConversationHandler.END
    keyboard = [
        [InlineKeyboardButton(f"{p[1]} vs {p[2]} ({p[3]})", callback_data=f"mod_{p[0]}")]
        for p in partite
    ]
    await update.message.reply_text(
        "Seleziona la partita da modificare:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    conn.close()
    return ConversationHandler.END

async def modifica_partita_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data.startswith("mod_"):
        partita_id = int(query.data.split("_")[1])
        context.user_data['modifica_id'] = partita_id
        # Mostra le opzioni modificabili
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
    campo = context.user_data['campo_modifica']
    partita_id = context.user_data['modifica_id']
    nuovo_valore = update.message.text.strip()
    conn = sqlite3.connect('calcetto.db')
    c = conn.cursor()
    if campo in ['squadra_a', 'squadra_b', 'risultato']:
        c.execute(f'UPDATE partite SET {campo} = ? WHERE id = ?', (nuovo_valore, partita_id))
        conn.commit()
        await update.message.reply_text("✅ Modifica effettuata.")
    elif campo == 'gol' or campo == 'assist':
        # Dobbiamo cancellare e reinserire le prestazioni per questa partita
        c.execute('SELECT squadra_a, squadra_b, risultato FROM partite WHERE id = ?', (partita_id,))
        row = c.fetchone()
        squadra_a = row[0].split(',')
        squadra_b = row[1].split(',')
        risultato = row[2]
        # Prendi anche l'altro campo (se serve), se assist/gol non modificato, riprendi l'esistente
        c.execute('SELECT giocatori.nome, prestazioni.gol, prestazioni.assist, prestazioni.squadra FROM prestazioni JOIN giocatori ON prestazioni.giocatore_id = giocatori.id WHERE partita_id = ?', (partita_id,))
        prestazioni = c.fetchall()
        if campo == 'gol':
            nuovo_gol = parse_stats(nuovo_valore)
            assist_esist = {nome: a for nome, g, a, sq in prestazioni}
        else:
            nuovo_assist = parse_stats(nuovo_valore)
            gol_esist = {nome: g for nome, g, a, sq in prestazioni}
        # cancella le prestazioni esistenti
        c.execute('DELETE FROM prestazioni WHERE partita_id = ?', (partita_id,))
        gol_a, gol_b = map(int, risultato.split('-'))
        for nome in squadra_a:
            giocatore_id = c.execute('SELECT id FROM giocatori WHERE nome=?', (nome,)).fetchone()[0]
            g = nuovo_gol.get(nome, gol_esist[nome]) if campo == 'gol' else gol_esist.get(nome,0)
            a = nuovo_assist.get(nome, assist_esist[nome]) if campo == 'assist' else assist_esist.get(nome,0)
            c.execute('INSERT INTO prestazioni (partita_id, giocatore_id, squadra, gol, assist, vittoria, pareggio, sconfitta) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                      (partita_id, giocatore_id, 'A', g, a, int(gol_a>gol_b), int(gol_a==gol_b), int(gol_a<gol_b)))
        for nome in squadra_b:
            giocatore_id = c.execute('SELECT id FROM giocatori WHERE nome=?', (nome,)).fetchone()[0]
            g = nuovo_gol.get(nome, gol_esist[nome]) if campo == 'gol' else gol_esist.get(nome,0)
            a = nuovo_assist.get(nome, assist_esist[nome]) if campo == 'assist' else assist_esist.get(nome,0)
            c.execute('INSERT INTO prestazioni (partita_id, giocatore_id, squadra, gol, assist, vittoria, pareggio, sconfitta) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                      (partita_id, giocatore_id, 'B', g, a, int(gol_b>gol_a), int(gol_a==gol_b), int(gol_b<gol_a)))
        conn.commit()
        await update.message.reply_text("✅ Modifica effettuata.")
    conn.close()
    return ConversationHandler.END

# ---- MAIN ----
def main():
    init_db()
    token = os.environ.get('TOKEN') or "INSERISCI_IL_TUO_TOKEN"
    app = Application.builder().token(token).build()

    conv_nuova = ConversationHandler(
        entry_points=[CommandHandler('nuovapartita', nuova_partita)],
        states={
            SQUADRE: [MessageHandler(filters.TEXT & ~filters.COMMAND, squadre)],
            DATA: [MessageHandler(filters.TEXT & ~filters.COMMAND, data_partita)],
            RISULTATO: [MessageHandler(filters.TEXT & ~filters.COMMAND, risultato)],
            GOL: [MessageHandler(filters.TEXT & ~filters.COMMAND, gol)],
            ASSIST: [MessageHandler(filters.TEXT & ~filters.COMMAND, assist)],
        },
        fallbacks=[CommandHandler('annulla', annulla)],
        allow_reentry=True
    )

    conv_partita = ConversationHandler(
        entry_points=[CommandHandler('partita', partita)],
        states={
            20: [MessageHandler(filters.TEXT & ~filters.COMMAND, mostra_partita)],
        },
        fallbacks=[CommandHandler('annulla', annulla)],
        allow_reentry=True
    )

    conv_elimina = ConversationHandler(
        entry_points=[CommandHandler('elimina_partita', elimina_partita)],
        states={
            ELIMINA_PARTITA_SELEZIONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, elimina_partita_data)],
        },
        fallbacks=[CommandHandler('annulla', annulla)],
        allow_reentry=True
    )

    conv_modifica = ConversationHandler(
        entry_points=[CommandHandler('modifica_partita', modifica_partita)],
        states={
            MODIFICA_PARTITA_SELEZIONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, modifica_partita_data)],
            MODIFICA_CAMPO: [CallbackQueryHandler(modifica_campo_callback)],
            MODIFICA_VALORE: [MessageHandler(filters.TEXT & ~filters.COMMAND, modifica_valore)],
        },
        fallbacks=[CommandHandler('annulla', annulla)],
        allow_reentry=True
    )

    app.add_handler(CommandHandler('start', start))
    app.add_handler(conv_nuova)
    app.add_handler(CommandHandler('statistiche', statistiche))
    app.add_handler(conv_partita)
    app.add_handler(conv_elimina)
    app.add_handler(CallbackQueryHandler(elimina_partita_callback, pattern="^del_"))
    app.add_handler(conv_modifica)
    app.add_handler(CallbackQueryHandler(modifica_partita_callback, pattern="^mod_"))
    app.add_handler(CommandHandler('annulla', annulla))

    app.run_polling()

if __name__ == '__main__':
    main()