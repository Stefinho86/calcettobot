import sqlite3
from telegram import Update, InputFile
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ConversationHandler, ContextTypes
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table

SQUADRE, DATA, RISULTATO, GOL, ASSIST = range(5)

def init_db():
    conn = sqlite3.connect('calcetto.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS giocatori (id INTEGER PRIMARY KEY, nome TEXT UNIQUE)''')
    c.execute('''CREATE TABLE IF NOT EXISTS partite (id INTEGER PRIMARY KEY, data TEXT, squadra_a TEXT, squadra_b TEXT, risultato TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS prestazioni (id INTEGER PRIMARY KEY, partita_id INTEGER, giocatore_id INTEGER, squadra TEXT, gol INTEGER, assist INTEGER, vittoria INTEGER, pareggio INTEGER, sconfitta INTEGER)''')
    conn.commit()
    conn.close()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Benvenuto! Inserisci i nomi dei 5 giocatori della Squadra A separati da virgola.")
    context.user_data['step'] = 0
    return SQUADRE

async def squadre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data['step'] == 0:
        context.user_data['squadra_a'] = [n.strip() for n in update.message.text.split(',')]
        await update.message.reply_text("Inserisci i nomi dei 5 giocatori della Squadra B separati da virgola.")
        context.user_data['step'] = 1
        return SQUADRE
    else:
        context.user_data['squadra_b'] = [n.strip() for n in update.message.text.split(',')]
        await update.message.reply_text("Inserisci la data della partita (YYYY-MM-DD).")
        return DATA

async def data_partita(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['data'] = update.message.text
    await update.message.reply_text("Inserisci il risultato della partita (es. 5-4).")
    return RISULTATO

async def risultato(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['risultato'] = update.message.text
    await update.message.reply_text("Inserisci i marcatori (es. Rossi:2, Bianchi:1, Verdi:2).")
    return GOL

async def gol(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['gol'] = update.message.text
    await update.message.reply_text("Inserisci gli assist (es. Neri:1, Rossi:2, Verdi:1).")
    return ASSIST

async def assist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['assist'] = update.message.text
    salva_partita(context.user_data)
    await update.message.reply_text("Partita salvata! Vuoi ricevere il PDF delle statistiche? Scrivi /statistiche.")
    return ConversationHandler.END

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

async def statistiche(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect('calcetto.db')
    c = conn.cursor()
    c.execute('SELECT nome, COUNT(prestazioni.id), SUM(gol), SUM(assist), SUM(vittoria), SUM(pareggio), SUM(sconfitta) FROM giocatori LEFT JOIN prestazioni ON giocatori.id = prestazioni.giocatore_id GROUP BY nome')
    rows = c.fetchall()
    data = [['Nome', 'Presenze', 'Gol', 'Assist', 'Vittorie', 'Pareggi', 'Sconfitte']]
    for row in rows:
        data.append(list(row))
    conn.close()
    filename = 'statistiche.pdf'
    genera_pdf(data, filename)
    await update.message.reply_document(InputFile(filename))

def genera_pdf(data, filename):
    doc = SimpleDocTemplate(filename, pagesize=letter)
    table = Table(data)
    doc.build([table])

def main():
    init_db()
    import os
    app = Application.builder().token(os.environ['TOKEN']).build()
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            SQUADRE: [MessageHandler(filters.TEXT & ~filters.COMMAND, squadre)],
            DATA: [MessageHandler(filters.TEXT & ~filters.COMMAND, data_partita)],
            RISULTATO: [MessageHandler(filters.TEXT & ~filters.COMMAND, risultato)],
            GOL: [MessageHandler(filters.TEXT & ~filters.COMMAND, gol)],
            ASSIST: [MessageHandler(filters.TEXT & ~filters.COMMAND, assist)],
        },
        fallbacks=[]
    )
    app.add_handler(conv_handler)
    app.add_handler(CommandHandler('statistiche', statistiche))
    app.run_polling()

if __name__ == '__main__':
    main()