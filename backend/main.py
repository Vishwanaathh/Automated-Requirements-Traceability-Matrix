from fastapi import FastAPI, HTTPException, Depends, Header
from pydantic import BaseModel
import mysql.connector
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime, timedelta
from jose import jwt, JWTError
from google import genai
import json
import re
from dotenv import load_dotenv
import os

# ---------------- ENV ----------------
load_dotenv()
SECRET_KEY = os.getenv("SECRET_KEY", "77777")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

# Initialize Gemini AI client
client = genai.Client(api_key=GEMINI_API_KEY)

# ---------------- Database ----------------
def get_db():
    return mysql.connector.connect(
        host="localhost",
        port=3306,
        user="root",
        password="",
        database="rtm"
    )

# ---------------- MODELS ----------------
class LoginData(BaseModel):
    username: str
    password: str

class Requirement(BaseModel):
    title: str
    description: str
    priority: str

class TestCase(BaseModel):
    title: str
    description: str
    expected_result: str
    status: str

class RTMmap(BaseModel):
    reqid: int
    testid: int

class RegisterData(BaseModel):
    username: str
    password: str
    role: str

class FileUpload(BaseModel):
    text: str

# ---------------- APP ----------------
app = FastAPI(title="RTM Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------- AUTH ----------------
def create_access_token(data: dict):
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    data.update({"exp": expire})
    return jwt.encode(data, SECRET_KEY, algorithm=ALGORITHM)

def verify_token(authorization: str = Header(...)):
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid token")
    token = authorization.split(" ")[1]
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

# ---------------- AUTH ROUTES ----------------
@app.post("/register")
def register(data: RegisterData):
    db = get_db()
    cursor = db.cursor()
    cursor.execute(
        "INSERT INTO users VALUES (%s,%s,%s)",
        (data.username, data.password, data.role)
    )
    db.commit()
    cursor.close()
    db.close()
    return {"message": "User Registered"}

@app.post("/login")
def login(data: LoginData):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute(
        "SELECT * FROM users WHERE username=%s AND password=%s",
        (data.username, data.password)
    )
    user = cursor.fetchone()
    cursor.close()
    db.close()

    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token({
        "username": user["username"],
        "role": user["role"]
    })

    return {"access_token": token}

@app.get("/")
def welcome():
    return {"message": "Welcome to RTM backend"}

# ---------------- CORE ROUTES ----------------
@app.post("/requirement")
def add_requirement(data: Requirement, user=Depends(verify_token)):
    db = get_db()
    cursor = db.cursor()
    cursor.execute(
        "INSERT INTO requirements (title, description, priority) VALUES (%s,%s,%s)",
        (data.title, data.description, data.priority)
    )
    db.commit()
    cursor.close()
    db.close()
    return {"message": "Requirement added"}

@app.post("/testcase")
def add_testcase(data: TestCase, user=Depends(verify_token)):
    db = get_db()
    cursor = db.cursor()
    cursor.execute(
        "INSERT INTO test_cases (title, description, expected_result, status) VALUES (%s,%s,%s,%s)",
        (data.title, data.description, data.expected_result, data.status)
    )
    db.commit()
    cursor.close()
    db.close()
    return {"message": "Test Case added"}

@app.post("/rtmmap")
def link_rtm(data: RTMmap, user=Depends(verify_token)):
    db = get_db()
    cursor = db.cursor()
    cursor.execute(
        "INSERT INTO requirement_testcase_map (requirement_id, testcase_id) VALUES (%s,%s)",
        (data.reqid, data.testid)
    )
    db.commit()
    cursor.close()
    db.close()
    return {"message": "Successfully linked"}

# ---------------- FETCH DATA ----------------
def fetch_data():
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM requirements")
    requirements = cursor.fetchall()
    cursor.execute("SELECT * FROM test_cases")
    testcases = cursor.fetchall()
    cursor.close()
    db.close()
    return requirements, testcases

# ---------------- GEMINI AI ----------------
def generate_rtm_mapping(requirements, testcases):
    req_text = "\n".join([f"{r['id']}: {r['title']} - {r['description']}" for r in requirements])
    tc_text = "\n".join([f"{t['id']}: {t['title']} - {t['description']}" for t in testcases])

    prompt = f"""
Match each requirement with relevant test cases.

Requirements:
{req_text}

Test Cases:
{tc_text}

Return ONLY valid JSON:
[
  {{"reqid": 1, "testids": [1,2]}}
]
"""
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt
    )
    return response.text

# ---------------- AUTO RTM ----------------
@app.post("/auto-rtm")
def auto_rtm(user=Depends(verify_token)):
    requirements, testcases = fetch_data()
    ai_output = generate_rtm_mapping(requirements, testcases)
    cleaned = re.sub(r"```json|```", "", ai_output).strip()
    try:
        mapping = json.loads(cleaned)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Invalid AI response: {cleaned}")

    db = get_db()
    cursor = db.cursor()
    for item in mapping:
        reqid = item.get("reqid")
        testids = item.get("testids", [])
        for tid in testids:
            try:
                cursor.execute(
                    "INSERT INTO requirement_testcase_map (requirement_id, testcase_id) VALUES (%s,%s)",
                    (reqid, tid)
                )
            except: 
                pass
    db.commit()
    cursor.close()
    db.close()
    return {"message": "AI RTM mapping completed"}

# ---------------- AUTO RTM FROM FILE ----------------
@app.post("/auto-rtm-file")
def auto_rtm_file(data: FileUpload, user=Depends(verify_token)):
    db = get_db()
    cursor = db.cursor()

    requirements = []
    testcases = []
    lines = data.text.splitlines()
    for line in lines:
        line = line.strip()
        if not line: 
            continue
        if line.startswith("R:"):
            parts = line[2:].split("|")
            title = parts[0].strip()
            desc = parts[1].strip() if len(parts) > 1 else ""
            priority = parts[2].strip() if len(parts) > 2 else "Medium"
            cursor.execute(
                "INSERT INTO requirements (title, description, priority) VALUES (%s,%s,%s)",
                (title, desc, priority)
            )
            requirements.append({"id": cursor.lastrowid, "title": title, "description": desc})
        elif line.startswith("T:"):
            parts = line[2:].split("|")
            title = parts[0].strip()
            desc = parts[1].strip() if len(parts) > 1 else ""
            expected = parts[2].strip() if len(parts) > 2 else ""
            status = parts[3].strip() if len(parts) > 3 else "Pending"
            cursor.execute(
                "INSERT INTO test_cases (title, description, expected_result, status) VALUES (%s,%s,%s,%s)",
                (title, desc, expected, status)
            )
            testcases.append({"id": cursor.lastrowid, "title": title, "description": desc})

    db.commit()

    ai_output = generate_rtm_mapping(requirements, testcases)
    cleaned = re.sub(r"```json|```", "", ai_output).strip()
    try:
        mapping = json.loads(cleaned)
    except Exception as e:
        cursor.close()
        db.close()
        raise HTTPException(status_code=500, detail=f"Invalid AI response: {cleaned}")

    for item in mapping:
        reqid = item.get("reqid")
        testids = item.get("testids", [])
        for tid in testids:
            try:
                cursor.execute(
                    "INSERT INTO requirement_testcase_map (requirement_id, testcase_id) VALUES (%s,%s)",
                    (reqid, tid)
                )
            except: 
                pass

    db.commit()
    cursor.close()
    db.close()
    return {"message": "File uploaded and AI RTM mapping completed"}

# ---------------- VIEW ----------------
@app.get("/requirements")
def get_requirements(user=Depends(verify_token)):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM requirements")
    rows = cursor.fetchall()
    cursor.close()
    db.close()
    return [{"id": r[0], "title": r[1], "description": r[2], "priority": r[3]} for r in rows]

@app.get("/testcases")
def get_testcases(user=Depends(verify_token)):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM test_cases")
    rows = cursor.fetchall()
    cursor.close()
    db.close()
    return [{"id": r[0], "title": r[1], "description": r[2], "expected_result": r[3], "status": r[4]} for r in rows]

@app.get("/rtm")
def full_rtm(user=Depends(verify_token)):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        SELECT r.id, r.title, t.id, t.title, t.status
        FROM requirement_testcase_map m
        JOIN requirements r ON m.requirement_id = r.id
        JOIN test_cases t ON m.testcase_id = t.id
        ORDER BY r.id, t.id
    """)
    rows = cursor.fetchall()
    cursor.close()
    db.close()
    return [{
        "requirement_id": r[0],
        "requirement_title": r[1],
        "testcase_id": r[2],
        "testcase_title": r[3],
        "status": r[4]
    } for r in rows]