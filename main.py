import os
import time
import sqlite3
import threading
import json
from flask import Flask
import telebot
from telebot import types

# --- YAPILANDIRMA ---
MAIN_BOT_TOKEN = "8873671833:AAE8ht6JFoznlt_XaGDUPfntNXNOn7yz1Gc"
CORE_ADMINS = [6534222591]
DB_NAME = 'yetki.db'

# --- VERİTABANI KURULUMU ---
def db_setup():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS yetkililer (user_id INTEGER PRIMARY KEY)')
    c.execute('CREATE TABLE IF NOT EXISTS klonlar (token TEXT PRIMARY KEY, user_id INTEGER)')
    c.execute('CREATE TABLE IF NOT EXISTS global_ayarlar (anahtar TEXT PRIMARY KEY, deger TEXT)')
    # Medyaları JSON string olarak saklamak için tablo
    c.execute('CREATE TABLE IF NOT EXISTS hafiza_medya (user_id INTEGER PRIMARY KEY, medya_data TEXT)')
    c.execute('INSERT OR IGNORE INTO global_ayarlar (anahtar, deger) VALUES ("gecikme", "0.1")')
    conn.commit()
    conn.close()

db_setup()

# --- VERİTABANI FONKSİYONLARI ---
def get_authorized():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    c = conn.cursor()
    c.execute('SELECT user_id FROM yetkililer')
    rows = c.fetchall()
    conn.close()
    auths = {r[0] for r in rows}
    auths.update(CORE_ADMINS)
    return auths

def add_auth_to_db(user_id):
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    c = conn.cursor()
    c.execute('INSERT OR IGNORE INTO yetkililer (user_id) VALUES (?)', (user_id,))
    conn.commit()
    conn.close()

def remove_auth_from_db(user_id):
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    c = conn.cursor()
    c.execute('DELETE FROM yetkililer WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()

def save_clone_token(token, user_id):
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    c = conn.cursor()
    c.execute('INSERT OR IGNORE INTO klonlar (token, user_id) VALUES (?, ?)', (token, user_id))
    conn.commit()
    conn.close()

def get_all_clones():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    c = conn.cursor()
    c.execute('SELECT token FROM klonlar')
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows]

def get_global_delay():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    c = conn.cursor()
    c.execute('SELECT deger FROM global_ayarlar WHERE anahtar = "gecikme"')
    row = c.fetchone()
    conn.close()
    return float(row[0]) if row else 0.1

def update_global_delay(value):
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    c = conn.cursor()
    c.execute('UPDATE global_ayarlar SET deger = ? WHERE anahtar = "gecikme"', (str(value),))
    conn.commit()
    conn.close()

# Medya Kaydetme ve Çekme Fonksiyonları
def save_user_media_to_db(user_id, media_list):
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    c = conn.cursor()
    # Sadece telegramın kopyalayabilmesi için gerekli tipleri saklıyoruz
    serialized = []
    for msg in media_list:
        data = {"chat_id": msg.chat.id, "message_id": msg.message_id}
        if msg.photo: data["type"] = "photo"
        elif msg.video: data["type"] = "video"
        elif msg.animation: data["type"] = "animation"
        serialized.append(data)
    
    c.execute('INSERT OR REPLACE INTO hafiza_medya (user_id, medya_data) VALUES (?, ?)', (user_id, json.dumps(serialized)))
    conn.commit()
    conn.close()

def load_user_media_from_db(user_id):
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    c = conn.cursor()
    c.execute('SELECT medya_data FROM hafiza_medya WHERE user_id = ?', (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return json.loads(row[0])
    return []

def is_core(user_id):
    return user_id in CORE_ADMINS

def is_authorized(user_id):
    return user_id in get_authorized()

# --- HAFIZA VE STATE YÖNETİMİ ---
temp_collecting_media = {} # Anlık medya yüklemesi yapanların listesi
active_loops = {}   
clone_threads = {}  
clone_info = {}     
setup_states = {}   
panel_cp_states = {}

# --- KLON DÖNGÜSÜ ---
def register_clone_handlers(bot):
    @bot.message_handler(commands=['stop'])
    def stop_process(message):
        if not is_authorized(message.from_user.id): return
        args = message.text.split()
        if len(args) < 2: return
        try:
            target_id = int(args[1])
            active_loops[target_id] = False
            bot.reply_to(message, "islem durduruldu.")
        except: pass

def start_copy_loop(bot, chat_id, user_id, limit, media_list):
    try:
        chat_info = bot.get_chat(chat_id)
        chat_name = chat_info.title
    except:
        chat_name = str(chat_id)
        
    active_loops[chat_id] = True
    current_delay = get_global_delay()
    
    try:
        bot.send_message(user_id, f"[{bot.get_me().first_name}] {chat_name} icin islem baslatti. Gecikme: {current_delay}s")
    except: pass

    t = threading.Thread(target=loop_sender, args=(bot, chat_id, user_id, limit, chat_name, media_list))
    t.daemon = True
    t.start()

def loop_sender(bot, chat_id, user_id, limit, chat_name, media_list):
    sent_count = 0
    while active_loops.get(chat_id) and sent_count < limit:
        for media_data in media_list:
            if not active_loops.get(chat_id) or sent_count >= limit: break
            try:
                # Hafızadan gelen sözlük verisiyle kopyalama yapılıyor
                bot.copy_message(chat_id, media_data["chat_id"], media_data["message_id"])
                sent_count += 1
                time.sleep(get_global_delay())
            except:
                time.sleep(get_global_delay())
    active_loops[chat_id] = False
    try:
        bot.send_message(user_id, f"[{bot.get_me().first_name}] {chat_name} grubuna {sent_count} medya gonderdi ve bitti.")
    except: pass

# --- ANA BOT MANTIĞI VE MERKEZİ YÖNETİM ---
main_bot = telebot.TeleBot(MAIN_BOT_TOKEN)

def get_main_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=1)
    btn_panel_cp = types.InlineKeyboardButton("🚀 botlari hizli yonet (/gcp)", callback_data="panel_cp_start")
    btn_update_media = types.InlineKeyboardButton("🖼️ medyalarini guncelle / yukle", callback_data="media_upload_start")
    btn_clone = types.InlineKeyboardButton("yeni bot klonla", callback_data="clone_start")
    btn_speed = types.InlineKeyboardButton("global hiz ayari", callback_data="speed_panel")
    markup.add(btn_panel_cp, btn_update_media, btn_clone, btn_speed)
    return markup

@main_bot.message_handler(commands=['start'], chat_types=['private'])
def main_start(message):
    if not is_authorized(message.from_user.id): return
    main_bot.reply_to(
        message, 
        "merhaba klonlayici kontrol merkezine hos geldin.",
        reply_markup=get_main_keyboard()
    )

# --- MEDYA YÜKLEME / GÜNCELLEME SİHİRBAZI ---
@main_bot.callback_query_handler(func=lambda call: call.data == "media_upload_start")
def start_media_upload(call):
    uid = call.from_user.id
    if not is_authorized(uid): return
    temp_collecting_media[uid] = []
    main_bot.edit_message_text(
        "Sistem için varsayılan medyaları yükleme alanı:\n\n"
        "Lütfen kaydetmek istediğiniz tüm medyaları peş peşe bu chata yollayın.\n"
        "Yükleme işiniz tamamen bittiğinde chata /done yazın.",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id
    )

# --- MERKEZİ HIZLI YÖNETİM PANELİ (/gcp) ---
@main_bot.message_handler(commands=['gcp'], chat_types=['private'])
@main_bot.callback_query_handler(func=lambda call: call.data == "panel_cp_start")
def main_panel_cp_init(target):
    uid = target.from_user.id if isinstance(target, telebot.types.Message) else target.from_user.id
    chat_id = target.chat.id if isinstance(target, telebot.types.Message) else target.message.chat.id
    if not is_authorized(uid): return
    
    clones = get_all_clones()
    if not clones:
        msg = "Sistemde kayitli klon bot yok. Once bot klonlayin."
        if isinstance(target, telebot.types.Message): main_bot.reply_to(target, msg)
        else: main_bot.edit_message_text(msg, chat_id, target.message.message_id, reply_markup=get_main_keyboard())
        return

    markup = types.InlineKeyboardMarkup(row_width=1)
    for token in clones:
        info = clone_info.get(token, {"first_name": "Bilinmeyen Bot"})
        short_id = token.split(":")[0]
        markup.add(types.InlineKeyboardButton(f"🤖 {info.get('first_name')}", callback_data=f"selbot_{short_id}"))
    markup.add(types.InlineKeyboardButton("❌ iptal", callback_data="main_menu"))

    msg_text = "Hızlı Yönetim: Görevlendirmek istediğiniz klon botu seçin:"
    if isinstance(target, telebot.types.Message):
        main_bot.send_message(chat_id, msg_text, reply_markup=markup)
    else:
        main_bot.edit_message_text(msg_text, chat_id, target.message.message_id, reply_markup=markup)

@main_bot.callback_query_handler(func=lambda call: call.data.startswith("selbot_"))
def handle_bot_selection(call):
    uid = call.from_user.id
    if not is_authorized(uid): return
    
    short_id = call.data.split("_")[1]
    clones = get_all_clones()
    selected_token = None
    
    for token in clones:
        if token.split(":")[0] == short_id:
            selected_token = token
            break
            
    if not selected_token or selected_token not in clone_threads:
        main_bot.answer_callback_query(call.id, "Bot aktif degil veya bulunamadi.")
        return

    # Veritabanında kayıtlı medyaları kontrol et
    saved_media = load_user_media_from_db(uid)
    if not saved_media:
        main_bot.edit_message_text(
            "Hata: Sistemde kayıtlı varsayılan medya bulunamadı! Önce ana menüden 'Medyalarını Güncelle / Yükle' butonuna basarak medyaları kaydetmelisin.",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=get_main_keyboard()
        )
        return

    # Doğrudan grup id isteme adımına geçiliyor
    panel_cp_states[uid] = {
        "step": "waiting_group_id",
        "token": selected_token,
        "media": saved_media
    }
    
    main_bot.edit_message_text(
        f"Seçilen Bot: {clone_info[selected_token]['first_name']}\n"
        f"Hafızadaki Varsayılan Medya: {len(saved_media)} adet\n\n"
        "👉 1. ADIM: Medyaların kopyalanacağı HEDEF GRUP ID'sini yazın (Örn: -100123456):",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id
    )

# --- ORTAK STATE YAKALAYICI VE GİRDİ YÖNETİMİ ---
@main_bot.message_handler(func=lambda msg: msg.from_user.id in panel_cp_states or msg.from_user.id in temp_collecting_media, content_types=['text', 'photo', 'video', 'animation'])
def handle_global_states(message):
    uid = message.from_user.id
    
    # EĞER VARYAYILAN MEDYA YÜKLEME STATE'İNDEYSE:
    if uid in temp_collecting_media:
        if message.content_type in ['photo', 'video', 'animation']:
            temp_collecting_media[uid].append(message)
            return
            
        if message.content_type == 'text' and message.text.strip() == "/done":
            if not temp_collecting_media[uid]:
                main_bot.reply_to(message, "Hiç medya göndermediniz. İptal etmek için /cancel yazın.")
                return
            
            # Veritabanına kalıcı kaydet
            save_user_media_to_db(uid, temp_collecting_media[uid])
            total = len(temp_collecting_media[uid])
            temp_collecting_media.pop(uid, None)
            
            main_bot.reply_to(message, f"✅ Başarılı! {total} adet medya varsayılan olarak kaydedildi. Artık /gcp yazdığında direkt bu medyalar kullanılacak.", reply_markup=get_main_keyboard())
            return
            
        if message.content_type == 'text' and message.text.strip() == "/cancel":
            temp_collecting_media.pop(uid, None)
            main_bot.reply_to(message, "Medya yükleme işlemi iptal edildi.", reply_markup=get_main_keyboard())
            return
        return

    # EĞER /GCP KONTROL STATE'İNDEYSE:
    state = panel_cp_states[uid]
    step = state["step"]

    if message.content_type == 'text' and message.text.strip() == "/cancel":
        panel_cp_states.pop(uid, None)
        main_bot.reply_to(message, "İşlem iptal edildi.", reply_markup=get_main_keyboard())
        return

    if step == "waiting_group_id":
        try:
            state["target_chat_id"] = int(message.text.strip())
            state["step"] = "waiting_limit"
            main_bot.reply_to(message, "👉 2. ADIM: Toplam kaç adet medya gönderilsin? (Limit girin):")
        except ValueError:
            main_bot.reply_to(message, "Geçersiz Grup ID'si. Sadece sayısal ID girin:")

    elif step == "waiting_limit":
        try:
            limit = int(message.text.strip())
            token = state["token"]
            bot_instance = clone_threads[token]
            
            # Klon bot üzerinden kayıtlı medyalarla döngüyü tetikle
            start_copy_loop(bot_instance, state["target_chat_id"], uid, limit, state["media"])
            
            main_bot.reply_to(
                message, 
                f"🚀 Komut iletildi!\n\n"
                f"Görevli Bot: {clone_info[token]['first_name']}\n"
                f"Hafızadan Alınan Medya: {len(state['media'])} adet\n"
                f"Limit: {limit} adet\n\n"
                f"İşlem arka planda başlatıldı.",
                reply_markup=get_main_keyboard()
            )
            panel_cp_states.pop(uid, None)
        except ValueError:
            main_bot.reply_to(message, "Geçersiz limit sayısı. Sadece tam sayı girin:")

# --- DİĞER ALTYAPI FONKSİYONLARI ---
@main_bot.callback_query_handler(func=lambda call: call.data.startswith("speed_"))
def handle_speed_callbacks(call):
    uid = call.from_user.id
    if not is_authorized(uid): return
    if call.data == "speed_panel":
        current = get_global_delay()
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("turbo (0.01s)", callback_data="speed_set_0.01"),
            types.InlineKeyboardButton("hizli (0.05s)", callback_data="speed_set_0.05"),
            types.InlineKeyboardButton("normal (0.1s)", callback_data="speed_set_0.1"),
            types.InlineKeyboardButton("guvenli (0.5s)", callback_data="speed_set_0.5"),
            types.InlineKeyboardButton("yavas (1.0s)", callback_data="speed_set_1.0"),
            types.InlineKeyboardButton("geri don", callback_data="main_menu")
        )
        main_bot.edit_message_text(f"global hiz ayarlama paneli\n\nguncel gecikme suresi: {current} saniye", call.message.chat.id, call.message.message_id, reply_markup=markup)
    elif call.data.startswith("speed_set_"):
        new_val = float(call.data.split("_")[-1])
        update_global_delay(new_val)
        main_panel_cp_init(call)

@main_bot.callback_query_handler(func=lambda call: call.data == "main_menu")
def callback_main_menu(call):
    main_bot.edit_message_text("merhaba klonlayici panele hos geldin.", call.message.chat.id, call.message.message_id, reply_markup=get_main_keyboard())

@main_bot.callback_query_handler(func=lambda call: call.data == "clone_start")
def callback_clone_start(call):
    uid = call.from_user.id
    setup_states[uid] = {"step": "waiting_token"}
    main_bot.edit_message_text("1. adim: lutfen klonlamak istediginiz botun token adresini gonderin.", call.message.chat.id, call.message.message_id)

@main_bot.message_handler(func=lambda msg: msg.from_user.id in setup_states, content_types=['text', 'photo'])
def handle_setup_steps(message):
    uid = message.from_user.id
    state = setup_states[uid]
    step = state["step"]

    if step == "waiting_token":
        token = message.text.strip() if message.text else ""
        if ":" not in token:
            main_bot.reply_to(message, "gecersiz token.")
            return
        state["token"] = token
        state["step"] = "waiting_name"
        main_bot.reply_to(message, "2. adim: bot ismi (gecmek icin /pass):")
    elif step == "waiting_name":
        state["name"] = None if message.text == "/pass" else message.text
        state["step"] = "waiting_bio"
        main_bot.reply_to(message, "3. adim: bot biyografisi (gecmek icin /pass):")
    elif step == "waiting_bio":
        state["bio"] = None if message.text == "/pass" else message.text
        state["step"] = "waiting_photo"
        main_bot.reply_to(message, "4. adim: profil fotografi gonderin (gecmek icin /pass):")
    elif step == "waiting_photo":
        photo_id = message.photo[-1].file_id if message.content_type == 'photo' else None
        token = state["token"]
        try:
            temp_bot = telebot.TeleBot(token)
            if state["name"]: temp_bot.set_my_name(state["name"])
            if state["bio"]:
                temp_bot.set_my_description(state["bio"])
                temp_bot.set_my_short_description(state["bio"])
            if photo_id:
                file_info = main_bot.get_file(photo_id)
                downloaded_file = main_bot.download_file(file_info.file_path)
                temp_bot.set_my_profile_photo(downloaded_file)
            save_clone_token(token, uid)
            start_clone_bot(token)
            main_bot.reply_to(message, "Bot başarıyla klonlandı!")
        except Exception as e:
            main_bot.reply_to(message, f"Hata: {e}")
        setup_states.pop(uid, None)

@main_bot.message_handler(commands=['bots'])
def list_cloned_bots(message):
    if not is_authorized(message.from_user.id): return
    clones = get_all_clones()
    if not clones:
        main_bot.reply_to(message, "Klon bot yok.")
        return
    text = f"Toplam kayıtlı bot: {len(clones)}\n\n"
    for idx, token in enumerate(clones, 1):
        info = clone_info.get(token, {"username": "Yükleniyor", "first_name": "Bilinmeyen"})
        text += f"{idx}. {info['first_name']} (@{info['username']})\n"
    main_bot.reply_to(message, text)

# --- YETKİLENDİRME KOMUTLARI ---
@main_bot.message_handler(commands=['amcik'])
def add_auth(message):
    if not is_core(message.from_user.id): return
    try:
        user_id = int(message.text.split()[1])
        add_auth_to_db(user_id)
        main_bot.reply_to(message, f"{user_id} yetkilendirildi.")
    except: pass

@main_bot.message_handler(commands=['yarrak'])
def remove_auth(message):
    if not is_core(message.from_user.id): return
    try:
        user_id = int(message.text.split()[1])
        if is_core(user_id): return
        remove_auth_from_db(user_id)
        main_bot.reply_to(message, f"{user_id} yetkisi kaldirildi.")
    except: pass

def start_clone_bot(token):
    if token in clone_threads: return
    try:
        bot = telebot.TeleBot(token)
        bot_me = bot.get_me()
        clone_info[token] = {
            "username": bot_me.username,
            "first_name": bot_me.first_name
        }
        register_clone_handlers(bot)
        
        def run_polling():
            try: bot.infinity_polling(timeout=20, long_polling_timeout=10)
            except: time.sleep(5); run_polling()

        t = threading.Thread(target=run_polling)
        t.daemon = True
        t.start()
        clone_threads[token] = bot
    except Exception as e:
        print(f"Klon baslatma hatası: {e}")

# --- FLASK SERVER ---
app = Flask(__name__)
@app.route('/')
def health_check(): return "Sistem aktif.", 200

if __name__ == '__main__':
    saved_clones = get_all_clones()
    for tok in saved_clones: start_clone_bot(tok)

    def run_main_bot():
        try: main_bot.infinity_polling(timeout=20, long_polling_timeout=10)
        except: time.sleep(5); run_main_bot()

    t_main = threading.Thread(target=run_main_bot)
    t_main.daemon = True
    t_main.start()
    
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
