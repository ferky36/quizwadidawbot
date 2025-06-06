import logging
import json
import random
import requests
import csv
import io
import os
import asyncio
# from aiohttp import web
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes

logging.basicConfig(level=logging.INFO)

# Data
sessions = {}  # session per chat_id
scores_db = "scores_db.json"

# Load previous scores from file
def load_scores():
    try:
        with open(scores_db, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

# Save scores to file
def save_scores():
    with open(scores_db, "w", encoding="utf-8") as f:
        json.dump(global_scores, f, indent=4)

# Global score dictionary
global_scores = load_scores()

# Load questions from Google Sheets
def load_questions_from_sheet(url):
    response = requests.get(url)
    response.raise_for_status()

    questions = []
    reader = csv.DictReader(io.StringIO(response.text))
    for row in reader:
        correct_index = ["A", "B", "C", "D"].index(row["Correct"].strip().upper())
        options = [row["A"], row["B"], row["C"], row["D"]]
        questions.append({
            "question": row["Question"],
            "options": options,
            "answer": options[correct_index]
        })
    return questions

sheet_url = "https://docs.google.com/spreadsheets/d/1iG0yUxbWU90wY7p3vpaoc0YPUJIsFjxx9Icnf4I2l14/export?format=csv&gid=1745206204"
all_questions_master = load_questions_from_sheet(sheet_url)


# Start (new entrypoint)
async def start_quiz_wadidaw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("""🧠 Selamat datang di sesi Quiz Wadidaw!
    
    Berikut List command quiz wadidaw:
    /quizwadidaw -> munculin bot quiz
    /joinquiz -> jojn quiz
    /questionstatus -> liat status pertanyaan
    /myscore -> liat score sementara
    /leaderboard -> liat total score di grup
    /restartquiz -> restart quiz
    /listpemain -> buat liat list pemain yg udah join quiz

    Ketik /joinquiz untuk bergabung ke sesi terlebih dahulu.""")

# List players who joined the quiz
async def list_players(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    session = sessions.get(chat_id)

    if not session or not session["participants"]:
        await update.message.reply_text("❗ Belum ada pemain yang bergabung.")
        return

    player_list = "👥 Pemain yang sudah bergabung:\n"
    for user_id in session["participants"]:
        try:
            user = await context.bot.get_chat(user_id)
            player_list += f"- {user.first_name}\n"
        except:
            player_list += f"- User ID: {user_id}\n"

    await update.message.reply_text(player_list)

# Join
async def join_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    session = sessions.setdefault(chat_id, {
        "participants": set(),
        "scores": {},
        "started": False,
        "index": 0,
        "answers": {},
        "limit": None,
        "questions": [],
        "waiting_limit_selection": False
    })

    if session["started"]:
        await update.message.reply_text("❗ Quiz sudah dimulai. Kamu tidak bisa bergabung sekarang.")
        return

    session["participants"].add(user.id)
    session["user_names"] = session.get("user_names", {})
    session["user_names"][user.id] = user.first_name

    session["scores"][user.id] = 0
    await update.message.reply_text(f"✅ {user.first_name} telah bergabung ke sesi quiz.\n\nKetik /startquiznow untuk memulai sesi quiz.")

# Choose max questions per session
async def set_question_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("5 soal", callback_data="limit_5")],
        [InlineKeyboardButton("10 soal", callback_data="limit_10")],
        [InlineKeyboardButton("15 soal", callback_data="limit_15")],
        [InlineKeyboardButton("20 soal", callback_data="limit_20")],
    ]
    await update.message.reply_text("📊 Pilih jumlah soal per sesi:", reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_limit_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = query.message.chat_id
    session = sessions.setdefault(chat_id, {
        "participants": set(),
        "scores": {},
        "started": False,
        "index": 0,
        "answers": {},
        "limit": None,
        "questions": [],
        "waiting_limit_selection": True
    })

    await query.answer()

    if session.get("waiting_limit_selection") and query.data.startswith("limit_"):
        session["limit"] = int(query.data.split("_")[1])
        session["waiting_limit_selection"] = False

        keyboard = [[InlineKeyboardButton("🚀 Mulai Quiz Sekarang", callback_data="start_quiz")]]
        await query.edit_message_text(
            f"✅ Jumlah soal per sesi ditetapkan ke {session['limit']}.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

# Mulai Quiz setelah pilih limit
async def start_quiz_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = query.message.chat_id
    session = sessions.get(chat_id)

    if not session or session.get("started"):
        await query.answer("Quiz sudah dimulai.", show_alert=True)
        return

    session["started"] = True
    session["index"] = 0
    session["answers"] = {}
    session["questions"] = random.sample(all_questions_master, session["limit"])

    await query.answer()
    await query.edit_message_text("🚀 Quiz dimulai sekarang!")
    await send_question_to_group(context, chat_id)

# Start Quiz Now
async def start_quiz_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    session = sessions.setdefault(chat_id, {
        "participants": set(),
        "scores": {},
        "started": False,
        "index": 0,
        "answers": {},
        "limit": None,
        "questions": [],
        "waiting_limit_selection": False
    })

    if session["started"]:
        await update.message.reply_text("❗ Quiz sudah berjalan.")
        return

    if not session["participants"]:
        await update.message.reply_text("❗ Tidak ada peserta yang bergabung.")
        return

    session["waiting_limit_selection"] = True
    await set_question_limit(update, context)

#fungsi timer
async def timeout_question(context, chat_id, seconds):
    await asyncio.sleep(seconds)
    session = sessions.get(chat_id)

    print(f"[DEBUG] [timeout_question] Timer selesai untuk chat_id {chat_id}")

    if not session:
        print("[DEBUG] [timeout_question] Tidak ada session.")
        return

    if not session.get("question_active", False):
        print("[DEBUG] [timeout_question] Soal sudah tidak aktif (mungkin sudah dijawab?), tapi tetap lanjut ke next question.")
        # return

    print(f"[DEBUG] [timeout_question] Menandai soal sebagai selesai.")
    session["question_active"] = False
    await show_correct_and_continue(context, chat_id, timeout=True)



#fungsi send question ke grup
async def send_question_to_group(context, chat_id):
    session = sessions[chat_id]
    print(f"[DEBUG] Soal ke-{session['index'] + 1} sudah dikirim setelah timeout.")
    session = sessions[chat_id]
    question = session["questions"][session["index"]]

    options = question["options"]
    random.shuffle(options)
    keyboard = [[InlineKeyboardButton(opt, callback_data=opt)] for opt in options]

    session["question_active"] = True
    session["answer_order"] = []

    # ⏱️ Kirim soal dan simpan message_id
    msg = await context.bot.send_message(
        chat_id=chat_id,
        text=f"❓ Soal {session['index'] + 1}:\n{question['question']}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    session["current_message_id"] = msg.message_id

    print(f"[DEBUG] Soal ke-{session['index'] + 1} dikirim ke chat_id {chat_id}")

    # ⏱️ Mulai timer 15 detik untuk soal ini
    session["timeout_task"] = asyncio.create_task(timeout_question(context, chat_id, 15))

# Handle Answer
async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = query.message.chat_id
    session = sessions[chat_id]
    user_id = query.from_user.id
    await query.answer()

    if not session["started"]:
        await query.message.reply_text("❗ Quiz belum dimulai. Gunakan /startquiznow")
        return

    if not session.get("question_active", False) or query.message.message_id != session.get("current_message_id"):
        await query.message.reply_text("❗ Waktu menjawab sudah habis atau soal sudah berganti.")
        return

    if user_id not in session["participants"]:
        await query.message.reply_text("❗ Kamu tidak terdaftar sebagai peserta quiz ini.")
        return

    if user_id in session["answers"]:
        await query.message.reply_text("❗ Kamu sudah menjawab soal ini.")
        return

    session["answers"][user_id] = query.data

    if "answer_order" not in session:
        session["answer_order"] = []
    session["answer_order"].append(user_id)

    # Jika semua sudah jawab → langsung lanjut
    if len(session["answers"]) == len(session["participants"]):
        session["question_active"] = False  # 🔐 kunci soal

        # 🔥 Batalin timeout
        timeout_task = session.get("timeout_task")
        if timeout_task and not timeout_task.done():
            timeout_task.cancel()

        await show_correct_and_continue(context, chat_id)


# /questionstatus command
async def show_question_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    session = sessions.get(chat_id)
    
    if not session:
        await update.message.reply_text("❗ Sesi quiz belum dimulai.")
        return

    if not session["started"]:
        await update.message.reply_text("❗ Quiz belum dimulai.")
        return

    answered_users = [user_id for user_id in session["participants"] if user_id in session["answers"]]
    not_answered_users = [user_id for user_id in session["participants"] if user_id not in session["answers"]]

    # Prepare the message
    answered_msg = "✅ Pengguna yang sudah menjawab:\n"
    not_answered_msg = "❌ Pengguna yang belum menjawab:\n"

    # Add answered users
    for uid in answered_users:
        try:
            user = await context.bot.get_chat(uid)
            answered_msg += f"- {user.first_name}\n"
        except:
            answered_msg += f"- User ID: {uid}\n"

    # Add not answered users
    for uid in not_answered_users:
        try:
            user = await context.bot.get_chat(uid)
            not_answered_msg += f"- {user.first_name}\n"
        except:
            not_answered_msg += f"- User ID: {uid}\n"

    # Send the status messages
    await update.message.reply_text(answered_msg)
    await update.message.reply_text(not_answered_msg)


# Show correct and go to next
async def show_correct_and_continue(context, chat_id, timeout=False):
    print(f"[DEBUG] Masuk show_correct_and_continue | timeout={timeout}")

    session = sessions[chat_id]
    question = session["questions"][session["index"]]
    correct = question["answer"]
    result_text = "⏰ Waktu habis!\n\n📢 Hasil Jawaban:\n" if timeout else "📢 Hasil Jawaban:\n"

    

    # Batalkan timeout kalau masih jalan
    timeout_task = session.get("timeout_task")
    logging.info(f"timeout_task: {timeout_task}")
    if timeout_task and not timeout_task.done():
        timeout_task.cancel()

    # List pengguna yang jawab benar dalam urutan kecepatan
    correct_users_ordered = []

    for uid in session["answer_order"]:
        selected = session["answers"].get(uid)
        if selected == correct:
            correct_users_ordered.append(uid)

    for uid in session["answers"]:
        selected = session["answers"].get(uid)
        try:
            user = await context.bot.get_chat(uid)
            name = user.first_name
        except:
            name = f"User {uid}"

        if selected == correct:
            if uid in correct_users_ordered:
                rank = correct_users_ordered.index(uid)
                if rank == 0:
                    points = 5
                elif rank == 1:
                    points = 3
                else:
                    points = 1
                session["scores"][uid] += points
                result_text += f"✅ {name} menjawab benar! (+{points})\n"
            else:
                result_text += f"✅ {name} menjawab benar!\n"
        else:
            result_text += f"❌ {name} salah.\n"

    result_text += f"\nJawaban yang benar adalah: {correct}"

    print(f"[DEBUG] result_text: {result_text}")
    # Cek siapa yang belum jawab (tidak termasuk ke bagian salah)
    unanswered = [uid for uid in session["participants"] if uid not in session["answers"]]
    print(f"[DEBUG] unanswered: {unanswered}")
    if unanswered:
        names = []
        for uid in unanswered:
            name = session.get("user_names", {}).get(uid)
            print(f"[DEBUG] unanswered: {name}")
            if not name:
                try:
                    user = await context.bot.get_chat(uid)
                    name = user.first_name
                except:
                    name = f"User tidak dikenal (ID: {uid})"
            names.append(name)
        result_text += "\n\n🚫 Belum menjawab:\n" + "\n".join(names)

    # Tambahkan info tambahan
    result_text += "\n\nℹ️ Ketik /myscore untuk melihat skor sementara kamu."
    result_text += "\nℹ️ Ketik /questionstatus untuk melihat siapa aja yg sudah/belum jawab soal."
    result_text += "\n\n➡️ Kita lanjut ke soal berikutnya ya..."
    
    print(f"[DEBUG] result_text tambahan: {result_text}")

    await context.bot.send_message(chat_id=chat_id, text=result_text)

    # 🔐 Reset flag sebelum lanjut
    session["question_active"] = False
    print(f"[DEBUG] Menambah index dari {session['index']}")
    session["index"] += 1
    session["answers"] = {}
    session["answer_order"] = []
    
    print(f"[DEBUG] Siap lanjut ke soal berikutnya. Index: {session['index']}, Limit: {session['limit']}")

    if session["index"] < session["limit"]:
        await send_question_to_group(context, chat_id)
        print(f"[DEBUG] Soal ke-{session['index'] + 1} dikirim setelah timeout.")
    else:
        print("[DEBUG] Sesi quiz selesai. Tidak lanjut soal.")
        await show_final_scores(context, chat_id)


# Update global scores
def update_global_scores(chat_id, local_scores):
    chat_id = str(chat_id)

    if chat_id not in global_scores:
        global_scores[chat_id] = {}

    for user_id, score in local_scores.items():
        user_id = str(user_id)
        if user_id in global_scores[chat_id]:
            global_scores[chat_id][user_id] += score
        else:
            global_scores[chat_id][user_id] = score

    save_scores()


# Show final leaderboard
# Show final leaderboard
async def show_final_scores(context, chat_id):
    session = sessions[chat_id]
    msg = "🏁 Sesi selesai! Skor akhir:\n"
    sorted_scores = sorted(session["scores"].items(), key=lambda x: x[1], reverse=True)

    for i, (uid, score) in enumerate(sorted_scores, 1):
        try:
            user = await context.bot.get_chat(uid)
            msg += f"{i}. {user.first_name} - {score} poin\n"
        except:
            msg += f"{i}. (user ID: {uid}) - {score} poin\n"

    # Add the message for starting a new session
    msg += "\nKetik /quizwadidaw untuk memulai sesi game baru lagi!"

    await context.bot.send_message(chat_id=chat_id, text=msg)


    # ✅ Update global score SEKARANG
    update_global_scores(chat_id, session["scores"])


    # Kosongkan session setelah selesai
    # session.clear()
    del sessions[chat_id]


# /myscore
# /myscore
async def my_score(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    user_id = str(update.effective_user.id)

    # Cek jika ada sesi aktif di grup
    session = sessions.get(int(chat_id))
    if session and session.get("started") and user_id in session["scores"]:
        # Ambil skor sementara dari sesi aktif
        score = session["scores"].get(user_id, 0)
        await update.message.reply_text(f"📊 Skor kamu saat ini di sesi ini: {score} poin")
        return

    # Kalau tidak ada sesi aktif, cek skor global
    score = global_scores.get(chat_id, {}).get(user_id)
    if score is None:
        await update.message.reply_text("❗ Kamu belum memiliki skor di grup ini.")
    else:
        await update.message.reply_text(f"📊 Skor kamu di grup ini: {score} poin")


# /leaderboard command to show global leaderboard
async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    chat_scores = global_scores.get(chat_id)

    if not chat_scores:
        await update.message.reply_text("❗ Belum ada skor untuk grup ini.")
        return

    sorted_scores = sorted(chat_scores.items(), key=lambda x: x[1], reverse=True)
    leaderboard_msg = "🏆 Leaderboard Grup Ini:\n"
    for i, (user_id, score) in enumerate(sorted_scores, 1):
        try:
            user = await context.bot.get_chat(user_id)
            leaderboard_msg += f"{i}. {user.first_name} - {score} poin\n"
        except:
            leaderboard_msg += f"{i}. (user ID: {user_id}) - {score} poin\n"

    await update.message.reply_text(leaderboard_msg)

# Restart game (reset session)
async def restart_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    session = sessions.get(chat_id)
    
    if not session:
        await update.message.reply_text("❗ Sesi quiz belum dimulai.")
        return

    # Clear the session and scores
    session.clear()
    del sessions[chat_id]

    await update.message.reply_text("🔄 Sesi quiz telah di-reset. Kamu bisa mulai quiz lagi dengan /quizwadidaw!")

# Webhook handler
# async def webhook_handler(request):
#     data = await request.json()
#     update = Update.de_json(data, app.bot)
#     await app.update_queue.put(update)
#     return web.Response()

# Main
# TOKEN = os.environ.get("BOT_TOKEN")
# WEBHOOK_URL = os.environ.get("WEBHOOK_URL")

def main():
    global app
    # app = ApplicationBuilder().token("TOKEN").build()
    app = ApplicationBuilder().token("8054761920:AAGVaOnzt6MbvOamAca3HhxGDqZy6Ml2FA0").build()

    # Tambahkan semua handler seperti sebelumnya
    app.add_handler(CommandHandler("quizwadidaw", start_quiz_wadidaw))
    app.add_handler(CommandHandler("joinquiz", join_quiz))
    app.add_handler(CommandHandler("setlimit", set_question_limit))
    app.add_handler(CommandHandler("startquiznow", start_quiz_now))
    app.add_handler(CommandHandler("questionstatus", show_question_status))
    app.add_handler(CommandHandler("myscore", my_score))
    app.add_handler(CommandHandler("leaderboard", leaderboard))
    app.add_handler(CommandHandler("restartquiz", restart_quiz))
    app.add_handler(CommandHandler("listpemain", list_players)) 
    app.add_handler(CallbackQueryHandler(handle_answer, pattern="^(?!limit_)(?!start_quiz).+"))
    app.add_handler(CallbackQueryHandler(handle_limit_selection, pattern="^limit_.*"))
    app.add_handler(CallbackQueryHandler(start_quiz_button, pattern="^start_quiz$"))

    # Run polling
    app.run_polling()


if __name__ == "__main__":
    main()

