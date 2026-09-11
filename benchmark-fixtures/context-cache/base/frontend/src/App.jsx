import React, { useEffect, useState } from "react";

export function App() {
  const [expenses, setExpenses] = useState([]);
  const [error, setError] = useState("");
  useEffect(() => {
    fetch("/expenses").then((response) => response.json()).then(setExpenses).catch(() => setError("Unable to load expenses"));
  }, []);
  if (error) return <p role="alert">{error}</p>;
  return <main><h1>Expenses</h1><p>{expenses.length} recorded</p></main>;
}
