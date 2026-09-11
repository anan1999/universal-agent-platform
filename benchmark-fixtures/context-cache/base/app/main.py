from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


DATABASE = Path(__file__).resolve().parents[1] / "expenses.sqlite3"
app = FastAPI(title="Pocket Expense")


class ExpenseIn(BaseModel):
    amount: float = Field(gt=0)
    category: str = Field(min_length=1)
    description: str = ""
    date: date


def connect() -> sqlite3.Connection:
    database = sqlite3.connect(DATABASE)
    database.row_factory = sqlite3.Row
    database.execute(
        "CREATE TABLE IF NOT EXISTS expenses ("
        "id INTEGER PRIMARY KEY, amount REAL NOT NULL, category TEXT NOT NULL, "
        "description TEXT NOT NULL, date TEXT NOT NULL)"
    )
    return database


@app.post("/expenses", status_code=201)
def create_expense(expense: ExpenseIn):
    with connect() as database:
        cursor = database.execute(
            "INSERT INTO expenses(amount,category,description,date) VALUES(?,?,?,?)",
            (expense.amount, expense.category, expense.description, expense.date.isoformat()),
        )
        row = database.execute("SELECT * FROM expenses WHERE id=?", (cursor.lastrowid,)).fetchone()
    return dict(row)


@app.get("/expenses")
def list_expenses():
    with connect() as database:
        return [dict(row) for row in database.execute("SELECT * FROM expenses ORDER BY date DESC, id DESC")]


@app.delete("/expenses/{expense_id}", status_code=204)
def delete_expense(expense_id: int):
    with connect() as database:
        cursor = database.execute("DELETE FROM expenses WHERE id=?", (expense_id,))
    if not cursor.rowcount:
        raise HTTPException(404, "expense not found")
