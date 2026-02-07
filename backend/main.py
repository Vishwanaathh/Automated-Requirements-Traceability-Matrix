from fastapi import FastAPI, HTTPException, Depends, Header
from pydantic import BaseModel
import mysql.connector
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime, timedelta
from jose import jwt, JWTError

SECRET_KEY = "77777"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

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
    
    username:str
    password:str
    role:str

app = FastAPI(title="RTM Backend")

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
def register(data:RegisterData):
    db=get_db()
    cursor=db.cursor(dictionary=True)
    cursor.execute("INSERT INTO users VALUES (%s,%s,%s)",(data.username,data.password,data.role))
    db.commit()
    return {"message":"User Registered"}

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
