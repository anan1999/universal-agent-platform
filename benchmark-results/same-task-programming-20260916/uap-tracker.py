"""A small, in-memory personal expense tracker."""

from __future__ import annotations

import csv
from datetime import date as calendar_date
from decimal import Decimal, InvalidOperation
from io import StringIO
import json
import os
from pathlib import Path
import re
import tempfile


class ExpenseTracker:
    """Keep expenses in insertion order with stable, one-based IDs."""

    def __init__(self) -> None:
        self._expenses: list[dict[str, int | str]] = []
        self._next_id = 1

    def add(self, amount: object, category: str, date: str, note: str = "") -> int:
        """Add an expense and return its ID."""
        if not isinstance(category, str) or not category.strip():
            raise ValueError("category must not be blank")
        if not isinstance(date, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) is None:
            raise ValueError("date must be an ISO date (YYYY-MM-DD)")
        try:
            calendar_date.fromisoformat(date)
        except ValueError as exc:
            raise ValueError("date must be a valid ISO date") from exc
        try:
            money = Decimal(str(amount)).quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError("amount must be a valid number") from exc
        if not money.is_finite() or money <= 0:
            raise ValueError("amount must be positive")
        expense_id = self._next_id
        self._expenses.append(
            {
                "id": expense_id,
                "amount": str(money),
                "category": category,
                "date": date,
                "note": note,
            }
        )
        self._next_id += 1
        return expense_id

    def list(self) -> list[dict[str, int | str]]:
        """Return ID-ordered copies of the stored expense records."""
        return [expense.copy() for expense in self._expenses]

    def delete(self, id: int) -> bool:
        """Delete an expense without making its ID available again."""
        for index, expense in enumerate(self._expenses):
            if expense["id"] == id:
                del self._expenses[index]
                return True
        return False

    def update(
        self,
        id: int,
        *,
        amount: object | None = None,
        category: str | None = None,
        date: str | None = None,
        note: str | None = None,
    ) -> bool:
        """Update an existing expense after validating the complete record."""
        for index, expense in enumerate(self._expenses):
            if expense["id"] != id:
                continue
            staged = ExpenseTracker()
            staged.add(
                expense["amount"] if amount is None else amount,
                str(expense["category"]) if category is None else category,
                str(expense["date"]) if date is None else date,
                str(expense["note"]) if note is None else note,
            )
            replacement = staged._expenses[0]
            replacement["id"] = id
            self._expenses[index] = replacement
            return True
        return False

    def filter(self, category: str) -> list[dict[str, int | str]]:
        """Return expenses in a category, ignoring case and surrounding spaces."""
        key = category.strip().casefold()
        return [
            expense.copy()
            for expense in self._expenses
            if str(expense["category"]).strip().casefold() == key
        ]

    def monthly(self, month: str) -> str:
        """Return the exact total for a calendar month as a two-decimal string."""
        if not isinstance(month, str) or re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month) is None:
            raise ValueError("month must be YYYY-MM")
        total = sum(
            (Decimal(str(expense["amount"])) for expense in self._expenses
             if str(expense["date"])[:7] == month),
            Decimal("0.00"),
        )
        return str(total.quantize(Decimal("0.01")))

    def summary(self, month: str) -> dict[str, str | int | dict[str, str]]:
        """Summarize one calendar month by its stored category names."""
        total = self.monthly(month)  # Also validates the month.
        category_totals: dict[str, Decimal] = {}
        count = 0
        for expense in self._expenses:
            if str(expense["date"])[:7] != month:
                continue
            count += 1
            category = str(expense["category"])
            category_totals[category] = category_totals.get(category, Decimal("0.00")) + Decimal(
                str(expense["amount"])
            )
        return {
            "month": month,
            "count": count,
            "total": total,
            "by_category": {name: str(value.quantize(Decimal("0.01")))
                            for name, value in category_totals.items()},
        }

    def to_csv(self) -> str:
        """Export all expenses as CSV text in ID order."""
        output = StringIO(newline="")
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(("id", "amount", "category", "date", "note"))
        for expense in self._expenses:
            writer.writerow(expense[key] for key in ("id", "amount", "category", "date", "note"))
        return output.getvalue()

    def from_csv(self, text: str) -> int:
        """Import an app CSV atomically, assigning fresh IDs."""
        if not isinstance(text, str):
            raise ValueError("CSV input must be text")
        staged = ExpenseTracker()
        seen_ids: set[int] = set()
        try:
            reader = csv.reader(StringIO(text, newline=""), strict=True)
            if next(reader, None) != ["id", "amount", "category", "date", "note"]:
                raise ValueError("invalid CSV header")
            for row in reader:
                if len(row) != 5 or re.fullmatch(r"[1-9]\d*", row[0]) is None:
                    raise ValueError("invalid CSV row")
                source_id = int(row[0])
                if source_id in seen_ids:
                    raise ValueError("duplicate CSV ID")
                seen_ids.add(source_id)
                staged.add(row[1], row[2], row[3], row[4])
        except csv.Error as exc:
            raise ValueError("invalid CSV text") from exc
        for expense in staged._expenses:
            imported = expense.copy()
            imported["id"] = self._next_id
            self._expenses.append(imported)
            self._next_id += 1
        return len(staged._expenses)

    def save(self, path: str | os.PathLike[str]) -> None:
        """Atomically write the ledger and next ID as UTF-8 JSON."""
        destination = Path(path)
        temporary: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=destination.parent,
                prefix=f".{destination.name}.", suffix=".tmp", delete=False,
            ) as output:
                temporary = output.name
                json.dump(
                    {"next_id": self._next_id, "expenses": self._expenses},
                    output, ensure_ascii=False,
                )
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, destination)
        finally:
            if temporary is not None and os.path.exists(temporary):
                os.unlink(temporary)

    @classmethod
    def load(cls, path: str | os.PathLike[str]) -> ExpenseTracker:
        """Restore a saved ledger, rejecting invalid JSON records."""
        with open(path, encoding="utf-8") as source:
            data = json.load(source)
        if not isinstance(data, dict) or set(data) != {"next_id", "expenses"}:
            raise ValueError("invalid tracker data")
        next_id, records = data["next_id"], data["expenses"]
        if type(next_id) is not int or next_id < 1 or not isinstance(records, list):
            raise ValueError("invalid tracker data")
        tracker = cls()
        previous_id = 0
        for record in records:
            if not isinstance(record, dict) or set(record) != {"id", "amount", "category", "date", "note"}:
                raise ValueError("invalid expense record")
            record_id = record["id"]
            if type(record_id) is not int or record_id <= previous_id or record_id >= next_id:
                raise ValueError("invalid expense ID")
            if not isinstance(record["amount"], str) or not isinstance(record["note"], str):
                raise ValueError("invalid expense record")
            tracker.add(record["amount"], record["category"], record["date"], record["note"])
            if tracker._expenses[-1]["amount"] != record["amount"]:
                raise ValueError("invalid expense amount")
            tracker._expenses[-1]["id"] = record_id
            previous_id = record_id
        tracker._next_id = next_id
        return tracker
