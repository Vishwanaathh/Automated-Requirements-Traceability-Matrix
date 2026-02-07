from fastapi import FastAPI
from pydantic import BaseModel
import mysql.connector
from fastapi.middleware.cors import CORSMiddleware

conn = mysql.connector.connect(
    host='localhost',
    port=3306,
    user='root',
    password='',
    database='rtm'
)
cursor = conn.cursor()

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


app = FastAPI(title="RTM Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def welcome():
    return {"message": "Welcome to RTM backend"}


@app.post("/requirement")
def add_requirement(data: Requirement):
    sql = "INSERT INTO requirements (title, description, priority) VALUES (%s,%s,%s)"
    cursor.execute(sql, (data.title, data.description, data.priority))
    conn.commit()
    return {"message": "Requirement added"}


@app.post("/testcase")
def add_testcase(data: TestCase):
    sql = "INSERT INTO test_cases (title, description, expected_result, status) VALUES (%s,%s,%s,%s)"
    cursor.execute(sql, (data.title, data.description, data.expected_result, data.status))
    conn.commit()
    return {"message": "Test Case added"}


@app.post("/rtmmap")
def link_rtm(data: RTMmap):
    sql = "INSERT INTO requirement_testcase_map (requirement_id, testcase_id) VALUES (%s,%s)"
    cursor.execute(sql, (data.reqid, data.testid))
    conn.commit()
    return {"message": "Successfully linked"}


@app.get("/requirements")
def get_requirements():
    cursor.execute("SELECT * FROM requirements")
    rows = cursor.fetchall()
    return [
        {"id": r[0], "title": r[1], "description": r[2], "priority": r[3]}
        for r in rows
    ]


@app.get("/testcases")
def get_testcases():
    cursor.execute("SELECT * FROM test_cases")
    rows = cursor.fetchall()
    return [
        {"id": r[0], "title": r[1], "description": r[2], "expected_result": r[3], "status": r[4]}
        for r in rows
    ]


@app.get("/rtm")
def full_rtm():
    sql = """
    SELECT
        r.id AS requirement_id,
        r.title AS requirement_title,
        t.id AS testcase_id,
        t.title AS testcase_title,
        t.status
    FROM requirement_testcase_map m
    JOIN requirements r ON m.requirement_id = r.id
    JOIN test_cases t ON m.testcase_id = t.id
    ORDER BY r.id, t.id
    """
    cursor.execute(sql)
    rows = cursor.fetchall()
    return [
        {
            "requirement_id": r[0],
            "requirement_title": r[1],
            "testcase_id": r[2],
            "testcase_title": r[3],
            "status": r[4]
        }
        for r in rows
    ]
