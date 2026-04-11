import os
import asyncio
import logging
import uuid
from flask import Flask
from threading import Thread
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, ConversationHandler, filters

logging.basicConfig(level=logging.INFO)
web_app = Flask(__name__)

@web_app.route('/')
def home():
    return "bot is live", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host='0.0.0.0', port=port)

TOKEN = os.getenv("BOT_TOKEN")
GET_NAME, GET_ARTIST, GET_COVER = range(3)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("send file")
    return GET_NAME

async def cancel_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ud = context.user_data
    for key in ['path', 'out', 'cov']:
        if key in ud and os.path.exists(ud[key]): os.remove(ud[key])
    context.user_data.clear()
    await update.message.reply_text("transaction canceled. /start for new")
    return ConversationHandler.END

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file = update.message.audio or update.message.voice or update.message.video or update.message.document
    if not file: return
    
    tid = str(uuid.uuid4())[:4] # daha kisa id
    ext = ".tmp"
    if hasattr(file, 'file_name') and file.file_name:
        ext = os.path.splitext(file.file_name)[1]
    
    file_path = f"{tid}{ext}"
    file_obj = await file.get_file()
    await file_obj.download_to_drive(file_path)
    
    context.user_data.update({'path': file_path, 'tid': tid})
    await update.message.reply_text("send name")
    return GET_NAME

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['name'] = update.message.text.lower()
    await update.message.reply_text("send artist")
    return GET_ARTIST

async def get_artist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['artist'] = update.message.text.lower()
    await update.message.reply_text("send cover or /skip")
    return GET_COVER

async def process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ud = context.user_data
    tid = ud['tid']
    is_skip = update.message.text and "/skip" in update.message.text
    
    proc_msg = await update.message.reply_text("processing...")
    
    out, cov = f"o{tid}.mp3", f"c{tid}.jpg"
    has_cov = False

    if not is_skip and update.message.photo:
        p = await update.message.photo[-1].get_file()
        await p.download_to_drive(cov)
        has_cov = True

    # hizlandirilmis ffmpeg komutu
    # -preset ultrafast ve -threads 0 maksimum hiz saglar
    if has_cov:
        cmd = f'ffmpeg -y -threads 0 -i "{ud["path"]}" -i "{cov}" -map 0:a -map 1:0 -id3v2_version 3 -metadata title="{ud["name"]}" -metadata artist="{ud["artist"]}" -codec:a libmp3lame -preset ultrafast -b:a 128k "{out}"'
    else:
        cmd = f'ffmpeg -y -threads 0 -i "{ud["path"]}" -vn -metadata title="{ud["name"]}" -metadata artist="{ud["artist"]}" -codec:a libmp3lame -preset ultrafast -b:a 128k "{out}"'
    
    p_exec = await asyncio.create_subprocess_shell(cmd)
    await p_exec.communicate()

    with open(out, 'rb') as f:
        await update.message.reply_audio(audio=f, title=ud["name"], performer=ud["artist"])
    
    await update.message.reply_text("done. /start for new")
    
    # aninda temizlik
    for f_p in [ud['path'], out, cov]:
        if os.path.exists(f_p): os.remove(f_p)
        
    context.user_data.clear()
    return ConversationHandler.END

if __name__ == '__main__':
    Thread(target=run_flask, daemon=True).start()
    app = ApplicationBuilder().token(TOKEN).build()
    
    conv = ConversationHandler(
        entry_points=[MessageHandler(filters.AUDIO | filters.VIDEO | filters.VOICE | filters.Document.ALL, handle_file)],
        states={
            GET_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            GET_ARTIST: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_artist)],
            GET_COVER: [MessageHandler(filters.PHOTO | filters.Regex("/skip"), process)],
        },
        fallbacks=[CommandHandler("cancel", cancel_action), CommandHandler("start", start)],
        conversation_timeout=300
    )
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv)
    app.run_polling()
