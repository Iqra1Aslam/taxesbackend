import time
from fastapi import FastAPI, Query, HTTPException,Header, Depends
from fastapi.middleware.cors import CORSMiddleware
import re, os
from form_fields import FORM_FIELDS
from pydantic import BaseModel, EmailStr, Field
from pymongo import MongoClient
from passlib.context import CryptContext
import stripe
from datetime import datetime
from bson import ObjectId
import smtplib
import random
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta

from dotenv import load_dotenv
load_dotenv()
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
# ---------------- FASTAPI APP ----------------
app = FastAPI(title="Tax Filing Assistant")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

INTERVIEW_FILE = "interview.py"

# ---------------- QUESTIONS ----------------
QUESTIONS = [
    ("status", "What is your filing status? (single, married, head_of_household)"),
    ("itemizing", "Do you plan to itemize deductions? (yes/no)"),
    ("over_65", "Are you over 65? (yes/no)"),
    ("spouse_over_65", "Is your spouse over 65? (yes/no or none)"),
    ("kids", "How many kids do you have?"),
    ("dependents", "How many dependents do you have (excluding kids)?"),
    ("s_loans", "Do you have student loans? (yes/no)"),
    ("cap_gains", "Do you have capital gains? (yes/no)"),
    ("have_rr", "Do you have retirement accounts? (yes/no)"),
    ("self_emp", "Are you self-employed? (yes/no)")
]

# ---------------- STATE ----------------
user_state = {"step": 0, "answers": {}}


# ---------------- UTILITIES ----------------
def update_interview_file(data: dict):
    """Save answers to interview.py"""
    lines = ["# Auto-updated by API\n"]
    for k, v in data.items():
        if isinstance(v, str):
            lines.append(f'{k}="{v}"\n')
        elif isinstance(v, bool):
            lines.append(f"{k}={'True' if v else 'False'}\n")
        else:
            lines.append(f"{k}={v}\n")
    lines.append('show_optional_zeros=True\n')
    lines.append('debug=True\n')
    with open(INTERVIEW_FILE, "w") as f:
        f.writelines(lines)


def parse_user_reply(reply: str):
    """Simple parser for yes/no/numbers/text."""
    t = reply.strip().lower()
    if t in ["yes", "y", "true"]: return True
    if t in ["no", "n", "false"]: return False
    if t.isdigit(): return int(t)
    for word in ["single", "married", "head_of_household"]:
        if word in t:
            return word
    return t


def get_next_question(answers):
    """Find next applicable question."""
    status = answers.get("status")
    defaults = {"spouse_over_65": False, "kids": 0, "dependents": 0}
    for field, question in QUESTIONS:
        if field in answers:
            continue

        skip = False
        if status == "single" and field in ["spouse_over_65", "kids", "dependents"]:
            skip = True
        elif status == "married" and field == "dependents" and answers.get("kids") == 0:
            skip = True
        elif status == "head_of_household" and field == "spouse_over_65":
            skip = True
        if field == "dependents" and answers.get("kids") == 0:
            skip = True

        if skip:
            if field in defaults:
                answers[field] = defaults[field]
            continue

        return field, question
    return None, None


# ---------------- MAIN ENDPOINT ----------------
# @app.get("/chat")
# def chat_with_user(reply: str = Query(None, description="User reply text")):
#     global user_state

#     # Start conversation
#     if reply is None:
#         user_state = {"step": 0, "answers": {}}
#         first_field, first_q = QUESTIONS[0]
#         greeting = (
#             "👋 Hi there! I’m your Tax Filing Assistant. "
#             "I’ll ask a few quick questions to prepare your tax info.\n\n"
#         )
#         return {"bot": f"{greeting}{first_q}"}

#     # Identify current question
#     current_field, _ = QUESTIONS[user_state["step"]]
#     parsed_value = parse_user_reply(reply)

#     # Validate numeric responses
#     numeric_keywords = ["dependents", "kids"]
#     if any(k in current_field for k in numeric_keywords):
#         try:
#             parsed_value = int(parsed_value)
#         except:
#             return {
#                 "bot": f"❌ Please enter a valid number for {current_field}.",
#                 "retry": True
#             }

#     # Save answer
#     user_state["answers"][current_field] = parsed_value

#     # Find next question
#     next_field, next_q = get_next_question(user_state["answers"])

#     if next_field:
#         user_state["step"] = [f for f, _ in QUESTIONS].index(next_field)

#         # ✅ Only show explanation for certain fields
#         if next_field in ["itemizing", "cap_gains", "have_rr"]:
#             explanations = {
#                 "itemizing": "Itemizing means listing specific deductions (like mortgage interest or charity donations) instead of taking the standard deduction.",
#                 "cap_gains": "Capital gains are profits you make from selling assets like stocks or property — they can affect your tax rate.",
#                 "have_rr": "Having a retirement account means you either save money for retirement or may need to report any money you took out."
#             }
#             explanation = explanations.get(next_field)
#             return {
#                 "bot": f"{explanation}\n\nNow, {next_q}",
#                 "collected": user_state["answers"]
#             }

#         # Default path
#         return {"bot": next_q, "collected": user_state["answers"]}

#     # End of form
#     update_interview_file(user_state["answers"])
#     return {
#         "bot": "✅ Thanks! All your answers have been recorded successfully.",
#         "final_data": user_state["answers"]
#     }


@app.post("/calculate")
def calculate_tax():
    try:
        import io, contextlib, importlib

        taxes = importlib.import_module("taxes")
        interview = importlib.reload(importlib.import_module("interview"))
        inform = importlib.reload(importlib.import_module("inform"))

        # ✅ Step 1: Load cells.py (defines cell and cell_list)
        exec(open("cells.py").read(), globals())

        # ✅ Step 2: Load taxforms.py (depends on cell definitions)
        exec(open("taxforms.py").read(), globals())

        # ✅ Step 3: Run computations silently
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            taxes.setup_inform(print_out=False)
            taxes.cell_list["f1040_refund"].compute()
            taxes.cell_list["f1040_tax_owed"].compute()
            taxes.cell_list["f8582_carryover_to_next_year"].compute()

        # ✅ Step 4: Extract only needed final values
        refund = taxes.cell_list.get("f1040_refund").value if "f1040_refund" in taxes.cell_list else None
        tax_owed = taxes.cell_list.get("f1040_tax_owed").value if "f1040_tax_owed" in taxes.cell_list else None
        carryover = taxes.cell_list.get("f8582_carryover_to_next_year").value if "f8582_carryover_to_next_year" in taxes.cell_list else None

        # ✅ Step 5: Return only summarized results — no internal logs
        return {
            "message": "Tax calculation completed successfully ✅",
            "note": (
        "Here's what your results mean:\n"
        "- A positive refund means you'll receive that amount back.\n"
        "- A positive tax owed means you still need to pay that amount.\n"
        "- 'Carryover to next year' represents losses or credits that can reduce next year's taxes."
    ),
           "results": {
        "refund": round(refund or 0, 2),
        "tax_owed": round(tax_owed or 0, 2),
        "carryover_to_next_year": round(carryover or 0, 2)
    }
        }

    except Exception as e:
        import traceback
        print("ERROR DETAILS:\n", traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

form_state = {"step": 0, "answers": {}}
def get_section_title(field_key: str):
    """Detect schedule/section title from field name"""
    if field_key.startswith("f1040sch1_"):
        return "🟦 Schedule 1 - Additional Income & Adjustments"
    elif field_key.startswith("f1040_"):
        return "🟩 Form 1040 - Main Income"
    elif field_key.startswith("f1040sch2_"):
        return "🟧 Schedule 2 - Additional Taxes"
    elif field_key.startswith("f1040sch3_"):
        return "🟪 Schedule 3 - Nonrefundable Credits"
    elif field_key.startswith("student_loan_ws_"):
        return "🎓 Student Loan Worksheet"
    elif field_key.startswith("f1040_tax_refund_ws_"):
        return "💰 Tax Refund Worksheet"
    elif field_key.startswith("f1040_sched_a_"):
        return "🟫 Schedule A - Itemized Deductions"
    elif field_key.startswith("f1040_sched_c_"):
        return "🟨 Schedule C - Business Income"
    elif field_key.startswith("sched_se_"):
        return "🟩 Schedule SE - Self-Employment"
    elif field_key.startswith("f1040_sched_e_"):
        return "🟧 Schedule E - Rental & Royalties"
    elif field_key.startswith("f4562_"):
        return "🏠 Form 4562 - Depreciation"
    # 🆕 Added sections below:
    elif field_key.startswith("f8582_"):
        return "📘 Form 8582 - Passive Activity Loss Limitations"
    elif field_key.startswith("f8863_"):
        return "🎓 Form 8863 - Education Credits (American Opportunity & Lifetime Learning)"
    elif field_key.startswith("ctc_sch8812_"):
        return "👶 Schedule 8812 - Child Tax Credit"
    return "📄 General Information"

def update_form_file(data: dict):
    """Write all form fields to inform.py"""
    lines = ["# Auto-generated IRS form data\n"]
    for k, v in data.items():
        if isinstance(v, str) and not v.replace('.', '', 1).isdigit():
            lines.append(f'{k}="{v}"\n')
        else:
            lines.append(f"{k}={v}\n")
    with open("inform.py", "w") as f:
        f.writelines(lines)

# @app.get("/form_chat")
# def form_chat(reply: str = Query(None, description="User reply text")):
#     global form_state
#     field_names = list(FORM_FIELDS.keys())

#     if reply is None:
#         form_state = {"step": 0, "answers": {}}
#         first_field = field_names[0]
#         section_title = get_section_title(first_field)
#         return {
#             "bot": f"{section_title}\n\n{FORM_FIELDS[first_field]}",
#             "section": section_title,
#         }

#     current_field = field_names[form_state["step"]]

#     if current_field in form_state["answers"]:
#         return {
#             "bot": f"⚠️ You’ve already answered '{current_field.replace('_', ' ')}'. Please wait for the next question.",
#             "field": current_field,
#             "retry": False,
#         }

#     reply = str(reply).strip()

#     # ✅ Step: Strict numeric validation (no Gemini)
#     try:
#         parsed_value = float(reply)
#     except ValueError:
#         return {
#             "bot": f"❌ Invalid input. Please enter a valid numeric value for '{current_field.replace('_', ' ')}'.",
#             "retry": True,
#             "field": current_field,
#             "example": "For example: 5000 or 1200.75",
#         }

#     if parsed_value < 0:
#         return {
#             "bot": f"❌ Negative values are not allowed for '{current_field.replace('_', ' ')}'.",
#             "retry": True,
#             "field": current_field,
#             "example": "For example: 5000 or 1200.75",
#         }

#     form_state["answers"][current_field] = parsed_value

#     if form_state["step"] + 1 < len(field_names):
#         form_state["step"] += 1
#         next_field = field_names[form_state["step"]]
#         next_section = get_section_title(next_field)
#         prev_section = get_section_title(current_field)

#         transition_message = None
#         if next_section != prev_section:
#             transition_message = f"✅ Finished {prev_section}\nNow starting {next_section}."

#         response = {
#             "bot": FORM_FIELDS[next_field],
#             "collected": form_state["answers"],
#             "section": next_section,
#         }

#         if transition_message:
#             response["transition"] = transition_message
#         return response

#     update_form_file(form_state["answers"])
#     return {
#         "bot": f"🎉 All values collected and saved successfully!",
#         "final_data": form_state["answers"],
#     }
# @app.get("/form_chat")
# def form_chat(reply: str = Query(None, description="User reply text")):
#     global form_state
#     field_names = list(FORM_FIELDS.keys())

#     if reply is None:
#         form_state = {"step": 0, "answers": {}}
#         first_field = field_names[0]
#         section_title = get_section_title(first_field)
#         return {
#             "bot": f"{section_title}\n\n{FORM_FIELDS[first_field]}",
#             "section": section_title,
#         }

#     current_field = field_names[form_state["step"]]

#     # ✅ If already answered
#     if current_field in form_state["answers"]:
#         return {
#             "bot": f"⚠️ You’ve already answered '{current_field.replace('_', ' ')}'. Please wait for the next question.",
#             "field": current_field,
#             "retry": False,
#         }

#     reply = str(reply).strip().lower()
#     question_text = FORM_FIELDS[current_field].lower()

#     # ✅ Step 1: Detect yes/no questions
#     if "(yes/no)" in question_text:
#         if reply in ["yes", "y"]:
#             parsed_value = True
#         elif reply in ["no", "n"]:
#             parsed_value = False
#         else:
#             return {
#                 "bot": f"❌ Invalid input. Please answer 'yes' or 'no' for '{current_field.replace('_', ' ')}'.",
#                 "retry": True,
#                 "field": current_field,
#                 "example": "For example: yes or no",
#             }

#     # ✅ Step 2: Otherwise, expect numeric input
#     else:
#         try:
#             parsed_value = float(reply)
#         except ValueError:
#             return {
#                 "bot": f"❌ Invalid input. Please enter a valid numeric value for '{current_field.replace('_', ' ')}'.",
#                 "retry": True,
#                 "field": current_field,
#                 "example": "For example: 5000 or 1200.75",
#             }

#         if parsed_value < 0:
#             return {
#                 "bot": f"❌ Negative values are not allowed for '{current_field.replace('_', ' ')}'.",
#                 "retry": True,
#                 "field": current_field,
#                 "example": "For example: 5000 or 1200.75",
#             }

#     # ✅ Save the parsed answer
#     form_state["answers"][current_field] = parsed_value

#     # ✅ Move to next question
#     if form_state["step"] + 1 < len(field_names):
#         form_state["step"] += 1
#         next_field = field_names[form_state["step"]]
#         next_section = get_section_title(next_field)
#         prev_section = get_section_title(current_field)

#         transition_message = None
#         if next_section != prev_section:
#             transition_message = f"✅ Finished {prev_section}\nNow starting {next_section}."

#         response = {
#             "bot": FORM_FIELDS[next_field],
#             "collected": form_state["answers"],
#             "section": next_section,
#         }
#         if transition_message:
#             response["transition"] = transition_message
#         return response

#     update_form_file(form_state["answers"])
#     return {
#         "bot": f"🎉 All values collected and saved successfully!",
#         "final_data": form_state["answers"],
#     }

# ------------------- MongoDB Connection -------------------

# Get the MongoDB URI from environment
mongo_uri = os.getenv("MONGO_URI")

# Initialize MongoDB client
client = MongoClient(mongo_uri)
db = client["tax_app"]
users_collection = db["users"]
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ------------------- Models -------------------
class Signup(BaseModel):
    name: str
    email: EmailStr
    password: str 
    # = Field(..., min_length=6, max_length=20)

class Signin(BaseModel):
    email: EmailStr
    password: str 
    # = Field(..., min_length=6, max_length=20)
import jwt
from datetime import datetime, timedelta

SECRET_KEY = "your_secret_key"
ALGORITHM = "HS256"
# 🟢 Signup API
# @app.post("/signup")
# def signup(user: Signup):
#     existing_user = users_collection.find_one({"email": user.email})
#     if existing_user:
#         raise HTTPException(status_code=400, detail="User already exist")

#     # Hash password before saving
#     hashed_pw = pwd_context.hash(user.password)
#     user_data = {
#         "name": user.name,
#         "email": user.email,
#         "password": hashed_pw
#     }

#     # Insert new user into DB
#     users_collection.insert_one(user_data)

#     # ✅ Return message + user info
#     return {
#         "message": "Signup successful",
#         "user": {
#             "name": user.name,
#             "email": user.email
#         }
#     }
@app.post("/signup")
def signup(user: Signup):
    existing_user = users_collection.find_one({"email": user.email})
    if existing_user:
        raise HTTPException(status_code=400, detail="User already exist")

    hashed_pw = pwd_context.hash(user.password)
    user_data = {
        "name": user.name,
        "email": user.email,
        "password": hashed_pw
    }
    users_collection.insert_one(user_data)

    # ✅ Create JWT token (2–3 lines)
    payload = {"email": user.email, "exp": datetime.utcnow() + timedelta(hours=2)}
    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

    # ✅ Return message + user info + token
    return {
        "message": "Signup successful",
        "user": {"name": user.name, "email": user.email},
        "token": token
    }
# def get_user_from_token(authorization: str = Header(None)):
#     if not authorization:
#         raise HTTPException(status_code=401, detail="Missing token")

#     token = authorization.replace("Bearer ", "")
#     try:
#         decoded = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
#         return decoded["email"]
#     except jwt.ExpiredSignatureError:
#         raise HTTPException(status_code=401, detail="Token expired")
#     except jwt.InvalidTokenError:
#         raise HTTPException(status_code=401, detail="Invalid token")
def get_user_from_token(token: str):
    if not token:
        raise HTTPException(status_code=401, detail="Missing token")

    try:
        decoded = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return decoded["email"]
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

user_sessions = {}
@app.get("/chat")
def chat_with_user(
    reply: str = Query(None, description="User reply text"),
    email: str = Depends(get_user_from_token)  # ✅ Get user from JWT
):
    # Initialize user session if not exist
    if email not in user_sessions:
        user_sessions[email] = {"step": 0, "answers": {}}

    user_state = user_sessions[email]

    # Start conversation
    if reply is None:
        user_state["step"] = 0
        user_state["answers"] = {}
        first_field, first_q = QUESTIONS[0]
        greeting = f"👋 Hi! I’m your Tax Filing Assistant.\n\n"
        return {"bot": f"{greeting}{first_q}"}

    # Identify current question
    current_field, _ = QUESTIONS[user_state["step"]]
    parsed_value = parse_user_reply(reply)

    # Validate numeric responses
    numeric_keywords = ["dependents", "kids"]
    if any(k in current_field for k in numeric_keywords):
        try:
            parsed_value = int(parsed_value)
        except:
            return {
                "bot": f"❌ Please enter a valid number for {current_field}.",
                "retry": True
            }

    # Save answer
    user_state["answers"][current_field] = parsed_value

    # Find next question
    next_field, next_q = get_next_question(user_state["answers"])

    if next_field:
        user_state["step"] = [f for f, _ in QUESTIONS].index(next_field)

        explanations = {
            "itemizing": "Itemizing means listing specific deductions like mortgage interest or charity donations.",
            "cap_gains": "Capital gains are profits from selling assets like stocks or property.",
            "have_rr": "Having a retirement account means saving for retirement or reporting withdrawals."
        }

        if next_field in explanations:
            return {
                "bot": f"{explanations[next_field]}\n\nNow, {next_q}",
                "collected": user_state["answers"]
            }

        return {"bot": next_q, "collected": user_state["answers"]}

    # End of form
    update_interview_file(user_state["answers"])
    return {
        "bot": f"✅ Thanks {email}! All your answers have been recorded successfully.",
        "final_data": user_state["answers"]
    }

# 🗂️ Each user has their own session state
user_form_sessions = {}
@app.get("/form_chat")
def form_chat(
    reply: str = Query(None, description="User reply text"),
    token: str = Query(None, description="JWT token for session"),
):
    user_email = get_user_from_token(token)

    # 🧠 Each user has their own form_state
    if user_email not in user_form_sessions:
        user_form_sessions[user_email] = {"step": 0, "answers": {}}

    form_state = user_form_sessions[user_email]
    field_names = list(FORM_FIELDS.keys())

    # 🟢 Start the conversation
    if reply is None:
        first_field = field_names[0]
        section_title = get_section_title(first_field)
        return {
            "bot": f"{section_title}\n\n{FORM_FIELDS[first_field]}",
            "section": section_title,
        }

    current_field = field_names[form_state["step"]]

    # ✅ If already answered
    if current_field in form_state["answers"]:
        return {
            "bot": f"⚠️ You’ve already answered '{current_field.replace('_', ' ')}'. Please wait for the next question.",
            "field": current_field,
            "retry": False,
        }

    reply = str(reply).strip().lower()
    question_text = FORM_FIELDS[current_field].lower()

    # ✅ Step 1: Detect yes/no questions
    if "(yes/no)" in question_text:
        if reply in ["yes", "y"]:
            parsed_value = True
        elif reply in ["no", "n"]:
            parsed_value = False
        else:
            return {
                "bot": f"❌ Invalid input. Please answer 'yes' or 'no' for '{current_field.replace('_', ' ')}'.",
                "retry": True,
                "field": current_field,
                "example": "For example: yes or no",
            }

    # ✅ Step 2: Otherwise, expect numeric input
    else:
        try:
            parsed_value = float(reply)
        except ValueError:
            return {
                "bot": f"❌ Invalid input. Please enter a valid numeric value for '{current_field.replace('_', ' ')}'.",
                "retry": True,
                "field": current_field,
                "example": "For example: 5000 or 1200.75",
            }

        if parsed_value < 0:
            return {
                "bot": f"❌ Negative values are not allowed for '{current_field.replace('_', ' ')}'.",
                "retry": True,
                "field": current_field,
                "example": "For example: 5000 or 1200.75",
            }

    # ✅ Save answer
    form_state["answers"][current_field] = parsed_value

    # ✅ Move to next question
    if form_state["step"] + 1 < len(field_names):
        form_state["step"] += 1
        next_field = field_names[form_state["step"]]
        next_section = get_section_title(next_field)
        prev_section = get_section_title(current_field)

        transition_message = None
        if next_section != prev_section:
            transition_message = f"✅ Finished {prev_section}\nNow starting {next_section}."

        response = {
            "bot": FORM_FIELDS[next_field],
            "collected": form_state["answers"],
            "section": next_section,
        }
        if transition_message:
            response["transition"] = transition_message
        return response

    # ✅ All done
    update_form_file(form_state["answers"])
    return {
        "bot": f"🎉 All values collected and saved successfully!",
        "final_data": form_state["answers"],
    }

# 🔵 Signin API
@app.post("/signin")
def signin(user: Signin):
    db_user = users_collection.find_one({"email": user.email})
    if not db_user:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    
    # Verify password
    if not pwd_context.verify(user.password, db_user["password"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
     # ✅ Create JWT token (2–3 lines)
    payload = {"email": user.email, "exp": datetime.utcnow() + timedelta(hours=2)}
    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

    return {
        "message": "Signin successful",
        "user": {"name": db_user["name"], "email": db_user["email"]},
         "token": token
    }

payments_collection = db["payments"]
class PaymentIntentCreate(BaseModel):
    email: EmailStr
    amount: int  # in cents (e.g., 1000 = $10)

class PaymentSuccess(BaseModel):
    email: EmailStr
    payment_id: str
    amount: int
# 💳 Create Payment Intent API
@app.post("/create-payment-intent")
def create_payment_intent(data: PaymentIntentCreate):
    # Check if user exists
    user = users_collection.find_one({"email": data.email})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    try:
        # Create Stripe payment intent
        intent = stripe.PaymentIntent.create(
            amount=data.amount,
            currency="usd",
            metadata={"user_id": str(user["_id"]), "email": user["email"]}
        )
        return {"clientSecret": intent["client_secret"]}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ✅ Payment Success API
@app.post("/payment/success")
def payment_success(payment: PaymentSuccess):
    user = users_collection.find_one({"email": payment.email})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Store payment details linked to user
    payment_doc = {
        "user_id": str(user["_id"]),
        "email": user["email"],
        "stripe_payment_id": payment.payment_id,
        "amount": payment.amount,
        "status": "succeeded",
        "created_at": datetime.utcnow(),
    }
    payments_collection.insert_one(payment_doc)

    return {"message": "Payment saved successfully and linked to user."}

#     existing = users_collection.find_one({"email": user["email"]})
#     if existing:
#         return {"message": "Signin successful", "user": {"name": existing["name"], "email": existing["email"]}}
#     new_user = {"name": user["name"], "email": user["email"], "password": None, "isPaid": False}
#     users_collection.insert_one(new_user)
#     # ✅ Create JWT token (2–3 lines)
    
#     return {"message": "Signup successful via Google", "user": {"name": user["name"], "email": user["email"]}}
@app.post("/google-signin")
def google_signin(user: dict):
    existing = users_collection.find_one({"email": user["email"]})

    # ✅ FIXED: user["email"] instead of user.email
    payload = {"email": user["email"], "exp": datetime.utcnow() + timedelta(hours=2)}
    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

    if existing:
        return {
            "message": "Signin successful",
            "token": token,  # ✅ include token here
            "user": {"name": existing["name"], "email": existing["email"]}
        }

    new_user = {
        "name": user["name"],
        "email": user["email"],
        "password": None,
        "isPaid": False
    }
    users_collection.insert_one(new_user)

    return {
        "message": "Signup successful via Google",
        "token": token,  # ✅ include token here too
        "user": {"name": user["name"], "email": user["email"]}
    }
# Temporary in-memory OTP store
otp_store = {}

# ---------- MODELS ----------
class EmailRequest(BaseModel):
    email: EmailStr

class VerifyRequest(BaseModel):
    email: EmailStr
    otp: str

# ---------- HELPER FUNCTIONS ----------
def generate_otp():
    """Generate 4-digit OTP"""
    return str(random.randint(1000, 9999))

def send_email(receiver_email: str, otp: str):
    sender_email = "hafizaiqraaslam1@gmail.com"
    sender_password = "mmcj tsqz kune zwzs"  # Google App Password

    subject = "Your OTP Code"
    body = f"Your One Time Password (OTP) is: {otp}\n\nThis code will expire in 5 minutes."

    message = MIMEMultipart()
    message["From"] = sender_email
    message["To"] = receiver_email
    message["Subject"] = subject
    message.attach(MIMEText(body, "plain"))

    try:
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(sender_email, sender_password)
        server.send_message(message)
        server.quit()
        return True
    except Exception as e:
        print("❌ Email error:", e)
        return False

# ---------- ROUTES ----------
@app.post("/send-otp")
def send_otp(request: EmailRequest):
    email = request.email
    otp = generate_otp()

    if send_email(email, otp):
        # Save OTP in memory with expiration
        otp_store[email] = {
            "otp": otp,
            "expires_at": datetime.utcnow() + timedelta(minutes=5)
        }
        return {"success": True, "message": "OTP sent successfully"}
    else:
        raise HTTPException(status_code=500, detail="Failed to send OTP")

@app.post("/verify-otp")
def verify_otp(request: VerifyRequest):
    record = otp_store.get(request.email)

    if not record:
        raise HTTPException(status_code=400, detail="No OTP found for this email")

    if datetime.utcnow() > record["expires_at"]:
        del otp_store[request.email]
        raise HTTPException(status_code=400, detail="OTP expired")

    if request.otp != record["otp"]:
        raise HTTPException(status_code=400, detail="Invalid OTP")

    # OTP verified — remove from memory
    del otp_store[request.email]
    return {"success": True, "message": "OTP verified successfully"}


# uvicorn test:app --host 0.0.0.0 --port 8000 --reload
# uvicorn main:app --host 0.0.0.0 --port 8000 --reload

