import os
import time
import sqlite3
import threading
import json
import requests
from flask import Flask
import telebot
from telebot import types

# --- yapılandırma ---
main_bot_token = "8873671833:AAEq9hhwJzIGFckNTZHr2JPWb7twbFVmJE8"
core_admins = [8942149499]
db_name = 'yetki.db'

# --- veritabanı kurulumu ---
def db_setup():
    conn = sqlite3.connect(db_name, check_same_thread=False)
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS yetkililer (user_id INTEGER PRIMARY KEY)')
    c.execute('CREATE TABLE IF NOT EXISTS klonlar (token TEXT PRIMARY KEY, user_id INTEGER)')
    c.execute('CREATE TABLE IF NOT EXISTS global_ayarlar (anahtar TEXT PRIMARY KEY, deger TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS hafiza_medya (user_id INTEGER PRIMARY KEY, medya_data TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS varsayilan_profil (user_id INTEGER PRIMARY KEY, name TEXT, bio TEXT, photo_id TEXT)')
    c.execute('INSERT OR IGNORE INTO global_ayarlar (anahtar, deger) VALUES ("gecikme", "0.1")')
    conn.commit()
    conn.close()

db_setup()

# --- veritabanı fonksiyonları ---
def get_authorized():
    conn = sqlite3.connect(db_name, check_same_thread=False)
    c = conn.cursor()
    c.execute('SELECT user_id FROM yetkililer')
    rows = c.fetchall()
    conn.close()
    auths = {r[0] for r in rows}
    auths.update(core_admins)
    return auths

def add_auth_to_db(user_id):
    conn = sqlite3.connect(db_name, check_same_thread=False)
    c = conn.cursor()
    c.execute('INSERT OR IGNORE INTO yetkililer (user_id) VALUES (?)', (user_id,))
    conn.commit()
    conn.close()

def remove_auth_from_db(user_id):
    conn = sqlite3.connect(db_name, check_same_thread=False)
    c = conn.cursor()
    c.execute('DELETE FROM yetkililer WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()

def save_clone_token(token, user_id):
    conn = sqlite3.connect(db_name, check_same_thread=False)
    c = conn.cursor()
    c.execute('INSERT OR IGNORE INTO klonlar (token, user_id) VALUES (?, ?)', (token, user_id))
    conn.commit()
    conn.close()

def get_all_clones():
    conn = sqlite3.connect(db_name, check_same_thread=False)
    c = conn.cursor()
    c.execute('SELECT token FROM klonlar')
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows]

def get_global_delay():
    conn = sqlite3.connect(db_name, check_same_thread=False)
    c = conn.cursor()
    c.execute('SELECT deger FROM global_ayarlar WHERE anahtar = "gecikme"')
    row = c.fetchone()
    conn.close()
    return float(row[0]) if row else 0.1

def update_global_delay(value):
    conn = sqlite3.connect(db_name, check_same_thread=False)
    c = conn.cursor()
    c.execute('UPDATE global_ayarlar SET deger = ? WHERE anahtar = "gecikme"', (str(value),))
    conn.commit()
    conn.close()

def save_user_media_to_db(user_id, media_list):
    conn = sqlite3.connect(db_name, check_same_thread=False)
    c = conn.cursor()
    serialized = []
    for msg in media_list:
        data = {"chat_id": msg.chat.id, "message_id": msg.message_id}
        serialized.append(data)
    c.execute('INSERT OR REPLACE INTO hafiza_medya (user_id, medya_data) VALUES (?, ?)', (user_id, json.dumps(serialized)))
    conn.commit()
    conn.close()

def load_user_media_from_db(user_id):
    conn = sqlite3.connect(db_name, check_same_thread=False)
    c = conn.cursor()
    c.execute('SELECT medya_data FROM hafiza_medya WHERE user_id = ?', (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return json.loads(row[0])
    return []

def save_default_profile(user_id, name, bio, photo_id):
    conn = sqlite3.connect(db_name, check_same_thread=False)
    c = conn.cursor()
    c.execute('INSERT OR REPLACE INTO varsayilan_profil (user_id, name, bio, photo_id) VALUES (?, ?, ?, ?)', (user_id, name, bio, photo_id))
    conn.commit()
    conn.close()

def load_default_profile(user_id):
    conn = sqlite3.connect(db_name, check_same_thread=False)
    c = conn.cursor()
    c.execute('SELECT name, bio, photo_id FROM varsayilan_profil WHERE user_id = ?', (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {"name": row[0], "bio": row[1], "photo_id": row[2]}
    return None

def set_bot_profile_photo(token, photo_bytes):
    try:
        url = f"https://api.telegram.org/bot{token}/setChatPhoto"
        bot_id = token.split(":")[0]
        files = {'photo': ('photo.jpg', photo_bytes, 'image/jpeg')}
        data = {'chat_id': bot_id}
        res = requests.post(url, data=data, files=files)
        return res.json().get("ok", False)
    except:
        return False

def is_core(user_id):
    return user_id in core_admins

def is_authorized(user_id):
    return user_id in get_authorized()

# --- hafıza ve state yönetimi ---
temp_collecting_media = {} 
active_loops = {}   
clone_threads = {}  
clone_info = {}     
setup_states = {}   
profile_states = {}

# --- klon handlers ve döngü mekanizması ---
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

def start_mass_copy_loop(chat_id, user_id, limit, media_list):
    active_loops[chat_id] = True
    clones = get_all_clones()
    
    for token in clones:
        if token in clone_threads:
            bot_instance = clone_threads[token]
            t = threading.Thread(target=individual_bot_sender, args=(bot_instance, chat_id, user_id, limit, media_list))
            t.daemon = True
            t.start()

def individual_bot_sender(bot, chat_id, user_id, limit, media_list):
    sent_count = 0
    while active_loops.get(chat_id) and sent_count < limit:
        for media_data in media_list:
            if not active_loops.get(chat_id) or sent_count >= limit: break
            try:
                bot.copy_message(chat_id, media_data["chat_id"], media_data["message_id"])
                sent_count += 1
                time.sleep(get_global_delay())
            except:
                time.sleep(get_global_delay())
    try:
        bot.send_message(user_id, f"{bot.get_me().first_name} isimli klon hedeflenen gruba gönderimini tamamladı.")
    except: pass

# --- ana bot mantığı ---
main_bot = telebot.TeleBot(main_bot_token)

def get_main_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("medyaları güncelle", callback_data="media_upload_start"),
        types.InlineKeyboardButton("yeni bot klonla", callback_data="clone_start"),
        types.InlineKeyboardButton("global hız ayarı", callback_data="speed_panel")
    )
    return markup

@main_bot.message_handler(commands=['start'], chat_types=['private'])
def main_start(message):
    if not is_authorized(message.from_user.id): return
    main_bot.reply_to(
        message, 
        "merhaba, kontrol merkezine hoş geldiniz. yapmak istediğiniz işlemi aşağıdaki butonlardan seçebilirsiniz.",
        reply_markup=get_main_keyboard()
    )

@main_bot.message_handler(commands=['profile'], chat_types=['private'])
def init_profile_setup(message):
    uid = message.from_user.id
    if not is_authorized(uid): return
    profile_states[uid] = {"step": "waiting_default_name"}
    main_bot.reply_to(message, "varsayılan profil oluşturma sihirbazı. lütfen tüm botlar için ortak kullanılacak varsayılan ismi gönderiniz:")

@main_bot.callback_query_handler(func=lambda call: call.data == "media_upload_start")
def start_media_upload(call):
    uid = call.from_user.id
    if not is_authorized(uid): return
    temp_collecting_media[uid] = []
    main_bot.edit_message_text(
        "varsayılan medya yükleme alanı aktif edilmiştir. lütfen kaydetmek istediğiniz medyaları peş peşe gönderiniz. işleminiz bittiğinde /done yazınız.",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id
    )

@main_bot.message_handler(commands=['gcp'], chat_types=['private'])
def handle_mass_gcp(message):
    uid = message.from_user.id
    if not is_authorized(uid): return
    
    args = message.text.split()
    if len(args) != 3:
        main_bot.reply_to(message, "hatalı kullanım. doğrusu: /gcp <grup_id> <adet> şeklindedir.")
        return
        
    try:
        target_chat_id = int(args[1])
        limit = int(args[2])
    except ValueError:
        main_bot.reply_to(message, "grup id ve adet parametreleri sayısal değerler olmalıdır.")
        return
        
    saved_media = load_user_media_from_db(uid)
    if not saved_media:
        main_bot.reply_to(message, "sistemde kayıtlı medya bulunamadı. lütfen önce butonları kullanarak medyaları yükleyiniz.")
        return
        
    clones = get_all_clones()
    if not clones:
        main_bot.reply_to(message, "sistemde kayıtlı aktif klon bot bulunmamaktadır.")
        return
        
    main_bot.reply_to(message, f"kitlesel saldırı başlatıldı. toplam {len(clones)} adet bot hedef gruba eş zamanlı olarak saldırıyor.")
    start_mass_copy_loop(target_chat_id, uid, limit, saved_media)

@main_bot.message_handler(func=lambda msg: msg.from_user.id in temp_collecting_media or msg.from_user.id in setup_states or msg.from_user.id in profile_states, content_types=['text', 'photo', 'video', 'animation'])
def handle_global_states(message):
    uid = message.from_user.id
    
    if uid in temp_collecting_media:
        if message.content_type in ['photo', 'video', 'animation']:
            temp_collecting_media[uid].append(message)
            return
            
        if message.content_type == 'text' and message.text.strip() == "/done":
            if not temp_collecting_media[uid]:
                main_bot.reply_to(message, "herhangi bir medya göndermediniz.")
                return
            save_user_media_to_db(uid, temp_collecting_media[uid])
            total = len(temp_collecting_media[uid])
            temp_collecting_media.pop(uid, None)
            main_bot.reply_to(message, f"işlem başarılı. toplam {total} adet medya varsayılan olarak sisteme kaydedildi.", reply_markup=get_main_keyboard())
            return

    elif uid in profile_states:
        p_state = profile_states[uid]
        p_step = p_state["step"]
        
        if p_step == "waiting_default_name":
            p_state["name"] = message.text.strip()
            p_state["step"] = "waiting_default_bio"
            main_bot.reply_to(message, "lütfen tüm botlar için ortak kullanılacak varsayılan biyografiyi gönderiniz:")
        elif p_step == "waiting_default_bio":
            p_state["bio"] = message.text.strip()
            p_state["step"] = "waiting_default_photo"
            main_bot.reply_to(message, "lütfen tüm botlar için ortak kullanılacak varsayılan profil fotoğrafını gönderiniz:")
        elif p_step == "waiting_default_photo":
            if message.content_type != 'photo':
                main_bot.reply_to(message, "lütfen geçerli bir fotoğraf gönderiniz:")
                return
            photo_id = message.photo[-1].file_id
            save_default_profile(uid, p_state["name"], p_state["bio"], photo_id)
            profile_states.pop(uid, None)
            main_bot.reply_to(message, "varsayılan profil ayarları başarıyla veritabanına kaydedildi. artık yeni bot eklediğinizde bu profil otomatik olarak yüklenecektir.", reply_markup=get_main_keyboard())

    elif uid in setup_states:
        state = setup_states[uid]
        step = state["step"]
        
        if step == "waiting_token":
            token = message.text.strip() if message.text else ""
            if ":" not in token:
                main_bot.reply_to(message, "geçersiz token formatı girdiniz.")
                return
            
            main_bot.reply_to(message, "işlemler uygulanıyor, lütfen bekleyiniz.")
            try:
                temp_bot = telebot.TeleBot(token)
                
                default_prof = load_default_profile(uid)
                if default_prof:
                    if default_prof["name"]: 
                        temp_bot.set_my_name(default_prof["name"])
                    if default_prof["bio"]:
                        temp_bot.set_my_description(default_prof["bio"])
                        temp_bot.set_my_short_description(default_prof["bio"])
                    if default_prof["photo_id"]:
                        file_info = main_bot.get_file(default_prof["photo_id"])
                        downloaded_file = main_bot.download_file(file_info.file_path)
                        set_bot_profile_photo(token, downloaded_file)
                
                save_clone_token(token, uid)
                start_clone_bot(token)
                
                main_bot.reply_to(message, "bot başarıyla klonlandı ve varsayılan profil ayarları uygulandı. yeni bot eklemek için start komutunu kullanın.", reply_markup=get_main_keyboard())
            except Exception as e:
                main_bot.reply_to(message, f"bir hata oluştu: {str(e)}\nyeni bot eklemek için start komutunu kullanın.", reply_markup=get_main_keyboard())
            setup_states.pop(uid, None)

@main_bot.callback_query_handler(func=lambda call: call.data.startswith("speed_"))
def handle_speed_callbacks(call):
    uid = call.from_user.id
    if not is_authorized(uid): return
    if call.data == "speed_panel":
        current = get_global_delay()
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("turbo (0.01s)", callback_data="speed_set_0.01"),
            types.InlineKeyboardButton("hızlı (0.05s)", callback_data="speed_set_0.05"),
            types.InlineKeyboardButton("normal (0.1s)", callback_data="speed_set_0.1"),
            types.InlineKeyboardButton("güvenli (0.5s)", callback_data="speed_set_0.5"),
            types.InlineKeyboardButton("yavaş (1.0s)", callback_data="speed_set_1.0"),
            types.InlineKeyboardButton("geri dön", callback_data="main_menu")
        )
        main_bot.edit_message_text(f"global hız ayarlama paneli. güncel gecikme süresi: {current} saniye.", call.message.chat.id, call.message.message_id, reply_markup=markup)
    elif call.data.startswith("speed_set_"):
        new_val = float(call.data.split("_")[-1])
        update_global_delay(new_val)
        main_bot.edit_message_text(f"hız güncellendi. güncel gecikme süresi: {new_val} saniye.", call.message.chat.id, call.message.message_id, reply_markup=get_main_keyboard())

@main_bot.callback_query_handler(func=lambda call: call.data == "main_menu")
def callback_main_menu(call):
    main_bot.edit_message_text("merhaba, kontrol merkezine hoş geldiniz.", call.message.chat.id, call.message.message_id, reply_markup=get_main_keyboard())

@main_bot.callback_query_handler(func=lambda call: call.data == "clone_start")
def callback_clone_start(call):
    uid = call.from_user.id
    setup_states[uid] = {"step": "waiting_token"}
    main_bot.edit_message_text("lütfen klonlamak istediğiniz botun token adresini gönderiniz.", call.message.chat.id, call.message.message_id)

@main_bot.message_handler(commands=['bots'])
def list_cloned_bots(message):
    if not is_authorized(message.from_user.id): return
    clones = get_all_clones()
    if not clones:
        main_bot.reply_to(message, "sistemde kayıtlı klon bot bulunmamaktadır.")
        return
    text = f"toplam kayıtlı bot sayısı: {len(clones)}\n\n"
    for idx, token in enumerate(clones, 1):
        info = clone_info.get(token, {"username": "yükleniyor", "first_name": "bilinmeyen"})
        text += f"{idx}. {info['first_name']} (@{info['username']})\n"
    main_bot.reply_to(message, text)

@main_bot.message_handler(commands=['amcik'])
def add_auth(message):
    if not is_core(message.from_user.id): return
    try:
        user_id = int(message.text.split()[1])
        add_auth_to_db(user_id)
        main_bot.reply_to(message, f"{user_id} numaralı kullanıcı yetkilendirildi.")
    except: pass

@main_bot.message_handler(commands=['yarrak'])
def remove_auth(message):
    if not is_core(message.from_user.id): return
    try:
        user_id = int(message.text.split()[1])
        if is_core(user_id): return
        remove_auth_from_db(user_id)
        main_bot.reply_to(message, f"{user_id} numaralı kullanıcının yetkisi kaldırıldı.")
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
        print(f"klon başlatma hatası: {e}")

# --- flask server ---
app = Flask(__name__)

@app.route('/')
def health_check(): 
    return "sistem aktif.", 200

# gunicorn worker ayağa kalktığında thread döngüsünü tetikler
def initialize_all_services():
    try:
        saved_clones = get_all_clones()
        for tok in saved_clones: start_clone_bot(tok)
    except Exception as e:
        print(f"klonlar başlatılırken hata: {e}")

    def run_main_bot():
        try: main_bot.infinity_polling(timeout=20, long_polling_timeout=10)
        except Exception as e: 
            print(f"ana bot poling hatası: {e}")
            time.sleep(5); run_main_bot()

    t_main = threading.Thread(target=run_main_bot)
    t_main.daemon = True
    t_main.start()

initialize_all_services()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))

