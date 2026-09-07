# Task DAG

Tasks move through queued, ready, running, waiting, blocked, completed, failed, or cancelled. A task becomes ready only when every dependency is completed. Missing dependencies and cycles fail validation before dispatch. Receipts are the preferred downstream context boundary.

