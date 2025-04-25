import logging
import json
import random
import requests
import csv
import io
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
from flask import Flask, request

logging.basicConfig(level=logging.INFO)

# Data
sessions = {}  # session per chat_id
scores_db = "scores_db.json"

# Load questions
# with open("questions.json", "r", encoding="utf-8") as f:
#     all_questions_master = json.load(f)



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

# Global score dictionary (keeps track of all quiz scores across all groups)
global_scores = load_scores()

#load questions from Google Sheets
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

sheet_url = "https://docs.google.com/spreadsheets/d/1iG0yUxbWU90wY7p3vpaoc0YPUJIsFjxx9Icnf4I2l14/export?format=csv&gid=0"
all_questions_master = load_questions_from_sheet(sheet_url)

# Flask app
app = Flask(__name__)

# Webhook endpoint
@app.route('/webhook', methods=['POST'])
def webhook():
    update = Update.de_json(request.get_json(force=True), bot)
    application.process_update(update)
    return 'ok'

# Start (new entrypoint)
async def start_quiz_wadidaw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("""🧠 Selamat datang di sesi Quiz Wadidaw!

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

# Send question to group
# async def send_question_to_group(context, chat_id):
#     session = sessions[chat_id]
#     question = session["questions"][session["index"]]
#     keyboard = [[InlineKeyboardButton(opt, callback_data=opt)] for opt in question["options"]]

#     try:
#         await context.bot.send_message(
#             chat_id=chat_id,
#             text=f"❓ Soal {session['index'] + 1}:\n{question['question']}",
#             reply_markup=InlineKeyboardMarkup(keyboard)
#         )
#     except Exception as e:
#         logging.warning(f"Gagal kirim soal ke grup: {e}")

async def send_question_to_group(context, chat_id):
    session = sessions[chat_id]
    question = session["questions"][session["index"]]
    
    # Randomize the options
    options = question["options"]
    random.shuffle(options)  # Shuffle the options randomly

    # Create the keyboard with randomized options
    keyboard = [[InlineKeyboardButton(opt, callback_data=opt)] for opt in options]

    try:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"❓ Soal {session['index'] + 1}:\n{question['question']}",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        logging.warning(f"Gagal kirim soal: {e}")


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

    if user_id not in session["participants"]:
        await query.message.reply_text("❗ Kamu tidak terdaftar sebagai peserta quiz ini.")
        return

    if user_id in session["answers"]:
        await query.message.reply_text("❗ Kamu sudah menjawab soal ini.")
        return
        
    # Pastikan answer_order ada
    if "answer_order" not in session:
        session["answer_order"] = []

    # Lalu lanjut logika
    if user_id not in session["answer_order"]:
        session["answer_order"].append(user_id)

    session["answers"][user_id] = query.data



    if len(session["answers"]) == len(session["participants"]):
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
# async def show_correct_and_continue(context, chat_id):
#     session = sessions[chat_id]
#     question = session["questions"][session["index"]]
#     correct = question["answer"]
#     result_text = "📢 Hasil Jawaban:\n"

#     for uid in session["participants"]:
#         selected = session["answers"].get(uid)
#         try:
#             user = await context.bot.get_chat(uid)
#             name = user.first_name
#         except:
#             name = f"User {uid}"

#         if selected == correct:
#             result_text += f"✅ {name} menjawab benar!\n"
#             session["scores"][uid] += 1
#         else:
#             result_text += f"❌ {name} salah.\n"

#     result_text += f"\nJawaban yang benar adalah: {correct}"
#     await context.bot.send_message(chat_id=chat_id, text=result_text)

#     # Update global score
#     # update_global_scores(chat_id, session["scores"])

#     await context.bot.send_message(
#         chat_id=chat_id,
#         text="ℹ️ Ketik /myscore untuk melihat skor sementara kamu.\nℹ️ Ketik /questionstatus untuk melihat siapa aja yg sudah/belum jawab soal."
#     )

#     session["index"] += 1
#     session["answers"] = {}

#     if session["index"] < session["limit"]:
#         await send_question_to_group(context, chat_id)
#     else:
#         await show_final_scores(context, chat_id)


# Show correct and go to next
async def show_correct_and_continue(context, chat_id):
    session = sessions[chat_id]
    question = session["questions"][session["index"]]
    correct = question["answer"]
    result_text = "📢 Hasil Jawaban:\n"

    # List pengguna yang jawab benar dalam urutan kecepatan
    correct_users_ordered = []

    for uid in session["answer_order"]:
        selected = session["answers"].get(uid)
        if selected == correct:
            correct_users_ordered.append(uid)

    for idx, uid in enumerate(session["participants"]):
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
    await context.bot.send_message(chat_id=chat_id, text=result_text)

    await context.bot.send_message(
        chat_id=chat_id,
        text="ℹ️ Ketik /myscore untuk melihat skor sementara kamu.\nℹ️ Ketik /questionstatus untuk melihat siapa aja yg sudah/belum jawab soal."
    )

    session["index"] += 1
    session["answers"] = {}
    session["answer_order"] = []

    if session["index"] < session["limit"]:
        await send_question_to_group(context, chat_id)
    else:
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


# Main
def main():
    global bot
    bot = ApplicationBuilder().token("8054761920:AAGVaOnzt6MbvOamAca3HhxGDqZy6Ml2FA0").build()

    # Add handlers
    bot.add_handler(CommandHandler("quizwadidaw", start_quiz_wadidaw))
    bot.add_handler(CommandHandler("joinquiz", join_quiz))
    bot.add_handler(CommandHandler("setlimit", set_question_limit))
    bot.add_handler(CommandHandler("startquiznow", start_quiz_now))
    bot.add_handler(CommandHandler("questionstatus", show_question_status))
    bot.add_handler(CommandHandler("myscore", my_score))
    bot.add_handler(CommandHandler("leaderboard", leaderboard))
    bot.add_handler(CommandHandler("restartquiz", restart_quiz))
    bot.add_handler(CommandHandler("listpemain", list_players)) 
    bot.add_handler(CallbackQueryHandler(handle_answer, pattern="^(?!limit_)(?!start_quiz).+"))
    bot.add_handler(CallbackQueryHandler(handle_limit_selection, pattern="^limit_.*"))
    bot.add_handler(CallbackQueryHandler(start_quiz_button, pattern="^start_quiz$"))

    # Set webhook
    PORT = int(os.environ.get('PORT', 5000))
    bot.run_webhook(listen="0.0.0.0", port=PORT, url_path='8054761920:AAGVaOnzt6MbvOamAca3HhxGDqZy6Ml2FA0')
    app.run(host='0.0.0.0', port=PORT)

if __name__ == "__main__":
    main()
