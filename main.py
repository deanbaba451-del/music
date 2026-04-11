import os
import random
from flask import Flask
from threading import Thread
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

app = Flask(__name__)

@app.route('/')
def home():
    return "altyapi canavar gibi"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

TOKEN = "8702532263:AAGEaRUxZ1OvmrW1qLSgpZnNV-Aec_buJ-8"
ALLOWED_USERS = [8321677959, 7842559876]
DORA_ID = 7842559876

# KATRİLYONLUK DEVASA KÜFÜR MATRİSİ
k1 = ["dora", "lan dora", "yagli dora", "pislik dora", "oglum dora", "kes sesini dora", "les dora", "saci bitli dora", "amk dorasi", "yag ficsi dora", "pasli dora", "kokusmus dora", "ahır kokulu dora", "yag tulumu dora", "it dölü dora"]
k2 = ["o yagli saclarina yigit bosalsin", "saclarini yika amk cocugu", "o saclar ne lan yag ficisi", "yigit o saclarina dol doksun", "sacin les gibi kokuyor amk", "yigit saclarina asilsin senin", "o sac tellerin yagdan birbirine girmis amk", "sacin ahir gibi kokuyor", "yigit kafandaki yaga kaysin", "sacin vicik vicik amk", "yigit o saclarinda sörf yapsin", "sacindaki yagla yemek yapilir amk", "yigit sacina bosa gitsin", "saclarin les kumesi gibi", "yigit o saclarini dölle yikasin", "sacindan sızan yagi sikeyim", "yigit o sacini döl havuzuna cevirsin"]
k3 = ["git banyo yap", "les herif", "yag ficsi", "pislik", "igrenc yaratik", "rezil", "amk evladi", "it soyu", "suratina sicayim", "asagilik", "midesiz", "tipsiz amk", "yag tulumu", "geber git", "kokusmus it", "lağım faresi"]
k4 = ["amk", "lan", "serefsiz", "it", "kopek", "yavsak", "pic", "ezik", "pislik", "mikrop", "gavat", "ibne", "orospu cocugu"]
k5 = ["yigit seni silsin", "sacini sikeyim", "o kafa ne amk", "yigit kafana bosalsin", "yaglı kafanı sikeyim", "git öl amk", "pis herif"]

async def handle_logic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user:
        return

    user_id = update.effective_user.id

    # 1. MEDYA TEMIZLIGI (8321677959 ve 7842559876 için)
    if user_id in ALLOWED_USERS:
        if not update.message.text:
            try:
                await update.message.delete()
                return 
            except:
                pass

    # 2. DORA YAZARSA KUFUR YAĞMURU
    if user_id == DORA_ID:
        # 5 farklı grubun rastgele birleşimi
        msg = f"{random.choice(k1)} {random.choice(k2)} {random.choice(k3)} {random.choice(k4)} {random.choice(k5)}".lower()
        await update.message.reply_text(msg)

if __name__ == "__main__":
    Thread(target=run_flask).start()
    
    app_bot = ApplicationBuilder().token(TOKEN).build()
    app_bot.add_handler(MessageHandler(filters.ALL, handle_logic))
    
    print("devasa havuz aktif, dora yandi.")
    app_bot.run_polling()
