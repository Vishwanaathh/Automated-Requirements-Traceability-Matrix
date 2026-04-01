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

load_dotenv()

SECRET_KEY = "77777"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

API_KEY = os.getenv("GEMINI_API_KEY")

if not API_KEY:
    raise Exception("GEMINI_API_KEY not found")

client = genai.Client(api_key=API_KEY.strip())

def get_db():
    return mysql.connector.connect(
        host="localhost",
        port=3306,
        user="root",
        password="",
        database="rtm"
    )

class LoginData(BaseModel):
    username: str
    password: str

class RegisterData(BaseModel):
    username: str
    password: str
    role: str

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

class FileUpload(BaseModel):
    text: str

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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

@app.post("/register")
def register(data: RegisterData):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("INSERT INTO users VALUES (%s,%s,%s)",
                   (data.username, data.password, data.role))
    db.commit()
    cursor.close()
    db.close()
    return {"message": "User Registered"}

@app.post("/login")
def login(data: LoginData):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM users WHERE username=%s AND password=%s",
                   (data.username, data.password))
    user = cursor.fetchone()
    cursor.close()
    db.close()

    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token({"username": user["username"], "role": user["role"]})
    return {"access_token": token}

@app.get("/")
def home():
    return {"message": "RTM Backend Running"}

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
    return {"message": "Linked"}

def fetch_data():
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM requirements")
    req = cursor.fetchall()
    cursor.execute("SELECT * FROM test_cases")
    tc = cursor.fetchall()
    cursor.close()
    db.close()
    return req, tc

def generate_mapping(req, tc):
    prompt = f"""
Match requirements to test cases.

Requirements:
{req}

Test Cases:
{tc}

Return ONLY JSON:
[{{"reqid":1,"testids":[1,2]}}]
"""
    res = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt
    )
    return res.text

@app.post("/auto-rtm-srs")
def auto_rtm_srs(data: FileUpload, user=Depends(verify_token)):
    db = get_db()
    cursor = db.cursor()

    extract_prompt = f"""
You are an expert QA engineer.

From this SRS document:
{data.text}

Extract:
1. Requirements
2. Test cases

Return JSON:
{{
  "requirements":[{{"title":"","description":""}}],
  "testcases":[{{"title":"","description":"","expected":""}}]
}}
"""

    res = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=extract_prompt
    )

    cleaned = re.sub(r"```json|```", "", res.text).strip()

    try:
        parsed = json.loads(cleaned)
    except:
        raise HTTPException(status_code=500, detail=f"AI returned invalid JSON:\n{cleaned}")

    for r in parsed.get("requirements", []):
        cursor.execute(
            "INSERT INTO requirements (title, description, priority) VALUES (%s,%s,%s)",
            (r["title"], r["description"], "Medium")
        )

    for t in parsed.get("testcases", []):
        cursor.execute(
            "INSERT INTO test_cases (title, description, expected_result, status) VALUES (%s,%s,%s,%s)",
            (t["title"], t["description"], t.get("expected",""), "Pending")
        )

    db.commit()

    req, tc = fetch_data()

    try:
        mapping = json.loads(re.sub(r"```json|```", "", generate_mapping(req, tc)))
    except:
        raise HTTPException(status_code=500, detail="Mapping failed")

    for m in mapping:
        for tid in m.get("testids", []):
            try:
                cursor.execute(
                    "INSERT INTO requirement_testcase_map (requirement_id, testcase_id) VALUES (%s,%s)",
                    (m["reqid"], tid)
                )
            except:
                pass

    db.commit()
    cursor.close()
    db.close()

    return {"message": "SRS processed and RTM generated"}

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
def get_rtm(user=Depends(verify_token)):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        SELECT r.id, r.title, t.id, t.title, t.status
        FROM requirement_testcase_map m
        JOIN requirements r ON m.requirement_id = r.id
        JOIN test_cases t ON m.testcase_id = t.id
        ORDER BY r.id
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

@app.delete("/clear-db")
def clear_db(user=Depends(verify_token)):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SET FOREIGN_KEY_CHECKS=0")
    cursor.execute("TRUNCATE requirement_testcase_map")
    cursor.execute("TRUNCATE requirements")
    cursor.execute("TRUNCATE test_cases")
    cursor.execute("SET FOREIGN_KEY_CHECKS=1")
    db.commit()
    cursor.close()
    db.close()
    return {"message": "Database cleared"}