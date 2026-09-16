"""A small, in-memory personal expense tracker."""

from __future__ import annotations

import csv
from datetime import date as calendar_date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from io import StringIO
import json
import os
from pathlib import Path
import re
import tempfile


class ExpenseTracker:
    """Keep expenses in insertion order with stable, one-based integer IDs."""

    def __init__(self) -> None:
        self._expenses: list[dict[str, int | str]] = []
        self._next_id = 1

    def add(self, amount: object, category: str, date: str, note: str = "") -> int:
        """Add an expense and return its ID."""
        try:
            money = Decimal(str(amount)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        except (InvalidOperation, ValueError) as exc:
            raise ValueError("amount must be a positive monetary value") from exc
        if not money.is_finite() or money <= 0:
            raise ValueError("amount must be positive after rounding to cents")
        if not isinstance(category, str) or not category.strip():
            raise ValueError("category must not be blank")
        if not isinstance(date, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            raise ValueError("date must be an ISO date (YYYY-MM-DD)")
        try:
            calendar_date.fromisoformat(date)
        except ValueError as exc:
            raise ValueError("date must be a valid ISO date") from exc
        expense_id = self._next_id
        self._expenses.append(
            {"id": expense_id, "amount": str(money), "category": category,
             "date": date, "note": note}
        )
        self._next_id += 1
        return expense_id

    def list(self) -> list[dict[str, int | str]]:
        """Return ID-ordered copies of the expense records."""
        return [expense.copy() for expense in self._expenses]

    def update(
        self, id: int, *, amount: object = None, category: str | None = None,
        date: str | None = None, note: str | None = None,
    ) -> bool:
        """Change supplied fields of an expense, preserving its ID."""
        if type(id) is not int:
            return False
        index = next((i for i, expense in enumerate(self._expenses)
                      if expense["id"] == id), None)
        if index is None:
            return False
        current = self._expenses[index]
        staged = ExpenseTracker()
        staged.add(
            current["amount"] if amount is None else amount,
            current["category"] if category is None else category,
            current["date"] if date is None else date,
            current["note"] if note is None else note,
        )
        replacement = staged._expenses[0]
        replacement["id"] = id
        self._expenses[index] = replacement
        return True

    def delete(self, id: int) -> bool:
        """Remove an expense by ID without making that ID reusable."""
        if type(id) is not int:
            return False
        for index, expense in enumerate(self._expenses):
            if expense["id"] == id:
                del self._expenses[index]
                return True
        return False

    def filter(self, category: str) -> list[dict[str, int | str]]:
        """Return expenses in a category, ignoring case and outer spaces."""
        if not isinstance(category, str):
            raise ValueError("category must be a string")
        requested = category.strip().casefold()
        return [
            expense.copy()
            for expense in self._expenses
            if str(expense["category"]).strip().casefold() == requested
        ]

    def monthly(self, month: str) -> str:
        """Return the exact total for a calendar month as a two-decimal string."""
        if not isinstance(month, str) or not re.fullmatch(r"\d{4}-\d{2}", month):
            raise ValueError("month must be YYYY-MM")
        try:
            calendar_date.fromisoformat(f"{month}-01")
        except ValueError as exc:
            raise ValueError("month must be a valid calendar month") from exc
        total = sum(
            (Decimal(str(expense["amount"])) for expense in self._expenses
             if str(expense["date"])[:7] == month),
            Decimal("0.00"),
        )
        return str(total)

    def summary(self, month: str) -> dict[str, str | int | dict[str, str]]:
        """Summarize one calendar month by stored category name."""
        total = self.monthly(month)
        by_category: dict[str, Decimal] = {}
        count = 0
        for expense in self._expenses:
            if str(expense["date"])[:7] != month:
                continue
            count += 1
            category = str(expense["category"])
            by_category[category] = by_category.get(category, Decimal("0.00")) + Decimal(
                str(expense["amount"])
            )
        return {
            "month": month,
            "count": count,
            "total": total,
            "by_category": {name: str(amount) for name, amount in by_category.items()},
        }

    def to_csv(self) -> str:
        """Export all expenses as CSV text in ID order."""
        output = StringIO(newline="")
        writer = csv.writer(output, lineterminator="\n")
        columns = ("id", "amount", "category", "date", "note")
        writer.writerow(columns)
        writer.writerows([expense[column] for column in columns] for expense in self._expenses)
        return output.getvalue()

    def from_csv(self, text: str) -> int:
        """Import a CSV export atomically, assigning new IDs to its rows."""
        if not isinstance(text, str):
            raise ValueError("CSV input must be text")
        staged = ExpenseTracker()
        seen_ids: set[int] = set()
        try:
            rows = csv.reader(StringIO(text, newline=""), strict=True)
            if next(rows, None) != ["id", "amount", "category", "date", "note"]:
                raise ValueError("invalid CSV header")
            for row in rows:
                if len(row) != 5 or not row[0].isdecimal() or int(row[0]) <= 0:
                    raise ValueError("invalid CSV row")
                source_id = int(row[0])
                if source_id in seen_ids:
                    raise ValueError("duplicate CSV ID")
                seen_ids.add(source_id)
                staged.add(row[1], row[2], row[3], row[4])
        except csv.Error as exc:
            raise ValueError("malformed CSV") from exc
        for expense in staged._expenses:
            self.add(expense["amount"], str(expense["category"]),
                     str(expense["date"]), str(expense["note"]))
        return len(staged._expenses)

    def save(self, path: str | os.PathLike[str]) -> None:
        """Atomically save the ledger and next ID as UTF-8 JSON."""
        target = Path(path)
        payload = {"records": self._expenses, "next_id": self._next_id}
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as file:
                json.dump(payload, file, ensure_ascii=False, indent=2)
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    @classmethod
    def load(cls, path: str | os.PathLike[str]) -> ExpenseTracker:
        """Load a saved ledger, rejecting invalid records or ID state."""
        with open(path, encoding="utf-8") as file:
            try:
                payload = json.load(file)
            except json.JSONDecodeError as exc:
                raise ValueError("invalid tracker JSON") from exc
        if not isinstance(payload, dict) or set(payload) != {"records", "next_id"}:
            raise ValueError("invalid tracker data")
        records = payload["records"]
        next_id = payload["next_id"]
        if not isinstance(records, list) or type(next_id) is not int or next_id < 1:
            raise ValueError("invalid tracker data")
        tracker = cls()
        last_id = 0
        for record in records:
            if not isinstance(record, dict) or set(record) != {
                "id", "amount", "category", "date", "note"
            }:
                raise ValueError("invalid expense record")
            record_id = record["id"]
            if type(record_id) is not int or record_id <= last_id:
                raise ValueError("expense IDs must be positive and ordered")
            if not isinstance(record["amount"], str) or not isinstance(record["note"], str):
                raise ValueError("invalid expense record")
            tracker.add(record["amount"], record["category"], record["date"], record["note"])
            if tracker._expenses[-1]["amount"] != record["amount"]:
                raise ValueError("amount must be a two-decimal string")
            tracker._expenses[-1]["id"] = record_id
            last_id = record_id
        if next_id <= last_id:
            raise ValueError("next ID must exceed all saved IDs")
        tracker._next_id = next_id
        return tracker
