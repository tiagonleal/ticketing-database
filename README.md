# Ticketing & Voting Database

Database design, a REST API and data analysis for an event ticketing and voting system.
Group project for *Databases* at Instituto Superior Técnico (2025/26).

## Highlights
- **PostgreSQL schema** with integrity constraints enforced by **triggers** and **PL/pgSQL functions**.
- **REST API** in **Flask** (`app/app.py`): connection pooling (`psycopg_pool`) and rate limiting (`flask-limiter`).
- **Query optimisation:** indexes justified with `EXPLAIN` plans.
- **Analytics:** a materialised view and OLAP queries with `CUBE`.

## Contents
| Path | Contents |
|---|---|
| `project.ipynb` | Schema, constraints, queries, indexes and analytics (with results) |
| `app/app.py` | REST API (`/zona/<id>/`, `/recinto/<id>/voto/<ticket>/`, `/venda/`, `/ping`) |
| `data/vendas.sql` | Synthetic data generation |

The API reads the database location from the `DATABASE_URL` environment variable.
