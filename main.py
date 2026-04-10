import os, subprocess, threading, uuid, asyncio
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from telegram.request import HTTPXRequest

# Flask Health Check
app = Flask(__name__)
@app.route('/')
def health(): return "OK", 200

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# Bot States
NAME, ARTIST, COVER = range(3)

def process_audio_sync(path, out, cv, name, artist):
    try:
        # En temel ve en sağlam FFmpeg komutu
        cmd = ['ffmpeg', '-y', '-i', path]
        
        if cv and os.path.exists(cv):
            cmd.extend(['-i', cv, '-map', '0:a', '-map', '1:v', '-c:v', 'copy', '-id3v2_version', '3'])
        else:
            cmd.extend(['-map', '0:a'])

        cmd.extend([
            '-c:a', 'libmp3lame', '-b:a', '320k',
            '-metadata', f'title={name}',
            '-metadata', f'artist={artist}',
            out
        ])
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        return result.returncode == 0
    except:
        return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("send audio or video file")
    return NAME

async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message.audio or update.message.voice or update.message.video or update.message.document
    if not msg: return
    
    uid = str(uuid.uuid4())[:8]
    path = f"in_{uid}"
    context.user_data.clear()
    
    file = await msg.get_file()
    await file.download_to_drive(path)
    
    context.user_data.update({'path': path, 'uid': uid})
    await update.message.reply_text("send new song name")
    return NAME

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.text or update.message.text.startswith('/'): return NAME
    context.user_data['name'] = update.message.text.strip()
    await update.message.reply_text("send new artist name")
    return ARTIST

async def get_artist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.text or update.message.text.startswith('/'): return ARTIST
    context.user_data['artist'] = update.message.text.strip()
    await update.message.reply_text("send cover photo or /skip")
    return COVER

async def finalize(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("processing...")
    ud = context.user_data
    uid, path = ud.get('uid'), ud.get('path')
    name, artist = ud.get('name', 'unknown'), ud.get('artist', 'unknown')
    out, cv = f"out_{uid}.mp3", None

    if update.message.photo:
        p = await update.message.photo[-1].get_file()
        cv = f"cv_{uid}.jpg"
        await p.download_to_drive(cv)

    loop = asyncio.get_event_loop()
    success = await loop.run_in_executor(None, process_audio_sync, path, out, cv, name, artist)

    if success and os.path.exists(out):
        with open(out, 'rb') as f:
            await update.message.reply_audio(audio=f, title=name, performer=artist, write_timeout=300)
        await update.message.reply_text("done. /start for new")
    else:
        await update.message.reply_text("error: processing failed")

    for f in [path, out, cv]:
        if f and os.path.exists(f): os.remove(f)
    context.user_data.clear()
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("editing process stopped. /start for new")
    return ConversationHandler.END

def main():
    token = os.environ.get('BOT_TOKEN')
    t_request = HTTPXRequest(connect_timeout=300, read_timeout=300)
    application = Application.builder().token(token).concurrent_updates(True).request(t_request).build()
    
    conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.AUDIO | filters.VOICE | filters.VIDEO | filters.Document.ALL, handle_media),
            CommandHandler('start', start)
        ],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            ARTIST: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_artist)],
            COVER: [
                MessageHandler(filters.PHOTO | filters.Document.IMAGE, finalize),
                CommandHandler('skip', finalize),
                CommandHandler('start', cancel)
            ],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        allow_reentry=True
    )
    
    application.add_handler(conv)
    application.run_polling()

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    main()
